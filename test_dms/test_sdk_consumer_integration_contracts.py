from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from io import BytesIO

import pytest

import dms
from dms.domain.models import DocumentStatus
from test_dms.sdk_test_support import (
    DEFAULT_PARTITION,
    CursorMemoryStore,
    StreamMemoryObjectStore,
)

_REQUIRED_EXPORTS = {
    "DocumentCopyResult",
    "DocumentDeleter",
    "DocumentPartition",
    "DocumentLister",
    "DocumentManagementClient",
    "DocumentReader",
    "DocumentWriter",
    "OperationEvent",
    "OperationObserver",
    "PartitionKind",
}


def _sdk(*, operation_observer=None):
    return dms.DefaultDocumentManagementSDK(
        metadata_store=CursorMemoryStore(),
        object_store=StreamMemoryObjectStore(),
        operation_observer=operation_observer,
    )


def _upload_bytes(sdk, content: bytes, *, partition=DEFAULT_PARTITION, **kwargs):
    return sdk.upload_document(
        dms.UploadDocumentRequest(content=content, **kwargs),
        partition=partition,
    )


def test_public_contract_exports_consumer_integration_types() -> None:
    missing = sorted(name for name in _REQUIRED_EXPORTS if not hasattr(dms, name))
    assert missing == []


def test_public_contract_does_not_expose_environment_configuration_helpers() -> None:
    removed_exports = {
        "EnvironmentDiagnosis",
        "SERVICE_CATALOG",
        "ServiceSetting",
        "diagnose_environment",
        "format_environment_diagnosis",
    }

    assert removed_exports.isdisjoint(vars(dms))


def test_default_sdk_satisfies_public_capability_protocols() -> None:
    sdk = _sdk()

    assert isinstance(sdk, dms.DocumentWriter)
    assert isinstance(sdk, dms.DocumentReader)
    assert isinstance(sdk, dms.DocumentLister)
    assert isinstance(sdk, dms.DocumentDeleter)
    assert isinstance(sdk, dms.DocumentManagementClient)


def test_upload_file_and_known_size_stream_own_only_internally_opened_resources(
    tmp_path,
) -> None:
    path = tmp_path / "payload.txt"
    path.write_bytes(b"file payload")
    source = BytesIO(b"stream payload")
    sdk = _sdk()

    file_result = sdk.upload_file(path, document_id="file", partition=DEFAULT_PARTITION)
    source_result = sdk.upload_document_stream(
        dms.UploadDocumentStreamRequest(
            stream=source,
            size=len(b"stream payload"),
            filename="source.txt",
            content_type="text/plain",
            document_id="source",
        ),
        partition=DEFAULT_PARTITION,
    )

    assert file_result.metadata.original_filename == "payload.txt"
    assert file_result.metadata.content_type == "text/plain"
    assert file_result.metadata.file_size == len(b"file payload")
    assert file_result.metadata.checksum
    assert source_result.metadata.file_size == len(b"stream payload")
    assert source.closed is False


def test_document_and_recovery_iterators_preserve_page_conditions() -> None:
    metadata_store = CursorMemoryStore()
    sdk = dms.DefaultDocumentManagementSDK(
        metadata_store=metadata_store,
        object_store=StreamMemoryObjectStore(),
    )
    for document_id in ("one", "two", "three"):
        _upload_bytes(
            sdk,
            document_id.encode(),
            filename=f"{document_id}.txt",
            content_type="text/plain",
            document_id=document_id,
        )
    failed = sdk.get_internal_document_metadata("two", partition=DEFAULT_PARTITION)
    metadata_store.update_metadata(replace(failed, status=DocumentStatus.FAILED))

    listed = list(sdk.iter_documents(page_size=1, partition=DEFAULT_PARTITION))
    recovery = list(
        sdk.iter_recovery_candidates(
            status=DocumentStatus.FAILED, page_size=1, partition=DEFAULT_PARTITION
        )
    )

    assert {item.document_id for item in listed} == {"one", "two", "three"}
    assert [item.document_id for item in recovery] == ["two"]


def test_copy_document_to_closes_source_and_keeps_sink_open() -> None:
    sdk = _sdk()
    uploaded = _upload_bytes(
        sdk,
        b"copy payload",
        filename="copy.txt",
        content_type="text/plain",
        document_id="copy",
    )
    sink = BytesIO()

    copied = sdk.copy_document_to(
        uploaded.document_id, sink, chunk_size=2, partition=DEFAULT_PARTITION
    )

    assert sink.getvalue() == b"copy payload"
    assert sink.closed is False
    assert copied.bytes_copied == len(b"copy payload")
    assert copied.checksum_verified is True


def test_partition_filters_before_paging_and_covers_internal_reads() -> None:
    sdk = _sdk()
    group_a = dms.DocumentPartition.group("a")
    group_b = dms.DocumentPartition.group("b")
    for document_id, partition in (("a1", group_a), ("b1", group_b), ("a2", group_a)):
        _upload_bytes(
            sdk,
            document_id.encode(),
            filename=f"{document_id}.txt",
            content_type="text/plain",
            document_id=document_id,
            partition=partition,
        )

    first = sdk.list_documents(limit=1, partition=group_a)
    second = sdk.list_documents(
        cursor=first.next_cursor,
        limit=1,
        partition=group_a,
    )

    assert first.has_more is True
    assert [item.document_id for item in first.items + second.items] == ["a2", "a1"]
    with pytest.raises(dms.DocumentNotFoundError):
        sdk.get_document_metadata("b1", partition=group_a)
    with pytest.raises(dms.DocumentNotFoundError):
        sdk.get_internal_document_metadata("b1", partition=group_a)


def test_operation_observer_receives_safe_success_and_failure_events() -> None:
    events = []
    sdk = _sdk(operation_observer=events.append)

    uploaded = _upload_bytes(
        sdk,
        b"payload",
        filename="observed.txt",
        content_type="text/plain",
        document_id="observed",
    )
    with pytest.raises(dms.DocumentNotFoundError):
        sdk.get_document_metadata("missing", partition=DEFAULT_PARTITION)

    assert [(event.operation, event.succeeded) for event in events] == [
        ("upload", True),
        ("metadata.get", False),
    ]
    assert events[0].document_id == uploaded.document_id
    assert events[1].error_code == "document_not_found"
    assert all("storage_key" not in json.dumps(event.to_dict()) for event in events)


def test_observer_failure_does_not_change_document_result() -> None:
    def fail_observer(event) -> None:
        del event
        raise RuntimeError("observer failed")

    sdk = _sdk(operation_observer=fail_observer)

    result = _upload_bytes(
        sdk,
        b"payload",
        filename="safe.txt",
        content_type="text/plain",
    )

    assert result.document_id


def test_remaining_public_results_have_json_compatible_dumps() -> None:
    sdk = _sdk()
    uploaded = _upload_bytes(
        sdk,
        b"payload",
        filename="serializable.txt",
        content_type="text/plain",
        document_id="serializable",
    )
    inspection = sdk.inspect_document(uploaded.document_id, partition=DEFAULT_PARTITION)
    dry_run = sdk.reconcile_documents(
        status=DocumentStatus.FAILED,
        action=dms.RecoveryAction.MARK_FAILED,
        dry_run=True,
        partition=DEFAULT_PARTITION,
    )
    plan = dry_run.to_plan()

    for value in (inspection, dry_run, plan):
        json.dumps(value.to_dict())


def test_partition_cannot_be_bypassed_by_content_delete_or_recovery() -> None:
    sdk = _sdk()
    group_a = dms.DocumentPartition.group("group-a")
    group_b = dms.DocumentPartition.group("group-b")
    uploaded = _upload_bytes(
        sdk,
        b"protected",
        filename="protected.txt",
        content_type="text/plain",
        document_id="protected",
        partition=group_a,
    )

    with pytest.raises(dms.DocumentNotFoundError):
        sdk.get_document_content(uploaded.document_id, partition=group_b)
    with pytest.raises(dms.DocumentNotFoundError):
        sdk.get_document_content_stream(uploaded.document_id, partition=group_b)
    with pytest.raises(dms.DocumentNotFoundError):
        sdk.copy_document_to(uploaded.document_id, BytesIO(), partition=group_b)
    with pytest.raises(dms.DocumentNotFoundError):
        sdk.get_internal_document_metadata(uploaded.document_id, partition=group_b)
    assert (
        sdk.inspect_document(uploaded.document_id, partition=group_b).metadata_exists
        is False
    )
    with pytest.raises(dms.DocumentNotFoundError):
        sdk.delete_document(uploaded.document_id, partition=group_b)
    with pytest.raises(dms.ValidationError):
        sdk.reconcile_document(
            "missing",
            dms.RecoveryAction.PURGE_ORPHAN_OBJECT,
            storage_key="orphan",
            dry_run=True,
            partition=group_b,
        )

    assert (
        sdk.get_document_content(uploaded.document_id, partition=group_a).content
        == b"protected"
    )
    assert (
        sdk.inspect_document(uploaded.document_id, partition=group_a).metadata_exists
        is True
    )
    assert sdk.delete_document(uploaded.document_id, partition=group_a).deleted is True


def test_async_high_level_operations_preserve_sync_contracts(tmp_path) -> None:
    path = tmp_path / "async.txt"
    path.write_bytes(b"async payload")

    async def scenario() -> None:
        sdk = dms.AsyncDocumentManagementSDK(
            dms.DefaultDocumentManagementSDK(
                metadata_store=CursorMemoryStore(),
                object_store=StreamMemoryObjectStore(),
            )
        )
        uploaded = await sdk.upload_file(path, partition=DEFAULT_PARTITION)
        listed = [
            item
            async for item in sdk.iter_documents(
                page_size=1, partition=DEFAULT_PARTITION
            )
        ]
        sink = BytesIO()
        copied = await sdk.copy_document_to(
            uploaded.document_id, sink, chunk_size=2, partition=DEFAULT_PARTITION
        )
        assert [item.document_id for item in listed] == [uploaded.document_id]
        assert sink.getvalue() == b"async payload"
        assert sink.closed is False
        assert copied.checksum_verified is True

    asyncio.run(scenario())


def test_operation_observer_covers_document_operation_categories() -> None:
    events = []
    sdk = _sdk(operation_observer=events.append)
    uploaded = _upload_bytes(
        sdk,
        b"observed",
        filename="observed.txt",
        content_type="text/plain",
        document_id="observed-categories",
    )

    sdk.list_documents(limit=10, partition=DEFAULT_PARTITION)
    sdk.get_document_content(uploaded.document_id, partition=DEFAULT_PARTITION)
    sdk.inspect_document(uploaded.document_id, partition=DEFAULT_PARTITION)
    sdk.delete_document(uploaded.document_id, partition=DEFAULT_PARTITION)

    assert {event.operation for event in events} >= {
        "upload",
        "documents.list",
        "content.get",
        "document.inspect",
        "document.delete",
    }
