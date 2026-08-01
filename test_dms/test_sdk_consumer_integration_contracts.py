from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from io import BytesIO

import pytest

import dms
from dms.domain.models import DocumentStatus
from test_dms.sdk_test_support import CursorMemoryStore, StreamMemoryObjectStore


_REQUIRED_EXPORTS = {
    "AccessContext",
    "AccessDeniedError",
    "DmsAssemblyPlan",
    "DmsOperationContext",
    "DmsServiceConfigs",
    "DocumentAccessPolicy",
    "DocumentCopyResult",
    "DocumentDeleter",
    "DocumentHealth",
    "DocumentLister",
    "DocumentManagementClient",
    "DocumentReader",
    "DocumentWriter",
    "ManagedResource",
    "OperationEvent",
    "OperationObserver",
    "ResourceCleanupError",
    "ResourceOwnership",
}


def _sdk(*, plan=None, managed_resources=(), service_checks=None):
    return dms.create_sdk_from_components(
        metadata_store=CursorMemoryStore(),
        object_store=StreamMemoryObjectStore(),
        plan=plan,
        managed_resources=managed_resources,
        service_checks=service_checks,
    )


def _upload_bytes(sdk, content: bytes, **kwargs):
    return sdk.upload_document(dms.UploadDocumentRequest(content=content, **kwargs))


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


def test_managed_resources_close_in_reverse_order_once_and_aggregate_failures() -> None:
    calls: list[str] = []

    def failing(name: str):
        def close() -> None:
            calls.append(name)
            raise RuntimeError(name)

        return close

    sdk = _sdk(
        managed_resources=(
            dms.ManagedResource(
                resource="one",
                ownership=dms.ResourceOwnership.SDK,
                close=failing("one"),
            ),
            dms.ManagedResource(
                resource="two",
                ownership=dms.ResourceOwnership.SDK,
                close=failing("two"),
            ),
        )
    )

    with pytest.raises(dms.ResourceCleanupError) as error:
        sdk.close()
    sdk.close()

    assert calls == ["two", "one"]
    assert [str(item) for item in error.value.errors] == ["two", "one"]


@pytest.mark.asyncio
async def test_async_managed_resource_is_closed_once() -> None:
    calls: list[str] = []

    async def close_resource() -> None:
        calls.append("closed")

    sdk = _sdk(
        managed_resources=(
            dms.ManagedResource(
                resource=object(),
                ownership=dms.ResourceOwnership.SDK,
                aclose=close_resource,
            ),
        )
    )

    await sdk.aclose()
    await sdk.aclose()

    assert calls == ["closed"]


def test_startup_failure_rolls_back_managed_resources() -> None:
    calls: list[str] = []

    def fail_healthcheck() -> None:
        raise RuntimeError("not ready")

    with pytest.raises(dms.HealthCheckFailedError):
        _sdk(
            plan=dms.DmsAssemblyPlan(check_on_startup=True),
            managed_resources=(
                dms.ManagedResource(
                    resource=object(),
                    ownership=dms.ResourceOwnership.SDK,
                    close=lambda: calls.append("closed"),
                ),
            ),
            service_checks={"metadata": fail_healthcheck},
        )

    assert calls == ["closed"]


def test_default_sdk_satisfies_public_capability_protocols() -> None:
    sdk = _sdk()

    assert isinstance(sdk, dms.DocumentWriter)
    assert isinstance(sdk, dms.DocumentReader)
    assert isinstance(sdk, dms.DocumentLister)
    assert isinstance(sdk, dms.DocumentDeleter)
    assert isinstance(sdk, dms.DocumentHealth)
    assert isinstance(sdk, dms.DocumentManagementClient)


def test_upload_file_and_known_size_stream_own_only_internally_opened_resources(tmp_path) -> None:
    path = tmp_path / "payload.txt"
    path.write_bytes(b"file payload")
    source = BytesIO(b"stream payload")
    sdk = _sdk()

    file_result = sdk.upload_file(path, document_id="file")
    source_result = sdk.upload_document_stream(dms.UploadDocumentStreamRequest(
        stream=source,
        size=len(b"stream payload"),
        filename="source.txt",
        content_type="text/plain",
        document_id="source",
    ))

    assert file_result.metadata.original_filename == "payload.txt"
    assert file_result.metadata.content_type == "text/plain"
    assert file_result.metadata.file_size == len(b"file payload")
    assert file_result.metadata.checksum
    assert source_result.metadata.file_size == len(b"stream payload")
    assert source.closed is False


def test_document_and_recovery_iterators_preserve_page_conditions() -> None:
    metadata_store = CursorMemoryStore()
    sdk = dms.create_sdk_from_components(
        metadata_store=metadata_store,
        object_store=StreamMemoryObjectStore(),
    )
    for document_id in ("one", "two", "three"):
        _upload_bytes(sdk,
            document_id.encode(),
            filename=f"{document_id}.txt",
            content_type="text/plain",
            document_id=document_id,
        )
    failed = sdk.get_internal_document_metadata("two")
    metadata_store.update_metadata(replace(failed, status=DocumentStatus.FAILED))

    listed = list(sdk.iter_documents(page_size=1))
    recovery = list(
        sdk.iter_recovery_candidates(status=DocumentStatus.FAILED, page_size=1)
    )

    assert {item.document_id for item in listed} == {"one", "two", "three"}
    assert [item.document_id for item in recovery] == ["two"]


def test_copy_document_to_closes_source_and_keeps_sink_open() -> None:
    sdk = _sdk()
    uploaded = _upload_bytes(sdk,
        b"copy payload",
        filename="copy.txt",
        content_type="text/plain",
        document_id="copy",
    )
    sink = BytesIO()

    copied = sdk.copy_document_to(uploaded.document_id, sink, chunk_size=2)

    assert sink.getvalue() == b"copy payload"
    assert sink.closed is False
    assert copied.bytes_copied == len(b"copy payload")
    assert copied.checksum_verified is True


def test_access_policy_filters_before_paging_and_covers_privileged_reads() -> None:
    class TenantPolicy:
        def allows(self, *, operation, context, metadata):
            del operation
            return (
                context is not None
                and metadata is not None
                and metadata.extra_metadata.get("tenant") == context.tenant
            )

    sdk = _sdk(plan=dms.DmsAssemblyPlan(access_policy=TenantPolicy()))
    for document_id, tenant in (("a1", "a"), ("b1", "b"), ("a2", "a")):
        _upload_bytes(sdk,
            document_id.encode(),
            filename=f"{document_id}.txt",
            content_type="text/plain",
            document_id=document_id,
            metadata={"tenant": tenant},
        )
    context = dms.AccessContext(subject="user-a", tenant="a")

    first = sdk.list_documents(limit=1, access_context=context)
    second = sdk.list_documents(
        cursor=first.next_cursor,
        limit=1,
        access_context=context,
    )

    assert first.has_more is True
    assert [item.document_id for item in first.items + second.items] == ["a2", "a1"]
    with pytest.raises(dms.AccessDeniedError):
        sdk.get_document_metadata("b1", access_context=context)
    with pytest.raises(dms.AccessDeniedError):
        sdk.get_internal_document_metadata("b1", access_context=context)


def test_scoped_operation_context_supplies_defaults_without_overriding_explicit_values() -> None:
    sdk = _sdk()
    scoped = sdk.scoped(
        dms.DmsOperationContext(
            access=dms.AccessContext(subject="alice", tenant="a"),
            created_by="alice",
            idempotency_scope="tenant-a",
            audit_actor="alice",
            default_metadata={"tenant": "a", "priority": "default"},
        )
    )

    uploaded = _upload_bytes(scoped,
        b"payload",
        filename="scoped.txt",
        content_type="text/plain",
        document_id="scoped",
        created_by="explicit",
        metadata={"priority": "explicit"},
    )

    assert uploaded.metadata.created_by == "explicit"
    assert uploaded.metadata.extra_metadata == {
        "tenant": "a",
        "priority": "explicit",
    }


def test_operation_observer_receives_safe_success_and_failure_events() -> None:
    events = []
    sdk = _sdk(plan=dms.DmsAssemblyPlan(operation_observer=events.append))

    uploaded = _upload_bytes(sdk,
        b"payload",
        filename="observed.txt",
        content_type="text/plain",
        document_id="observed",
    )
    with pytest.raises(dms.DocumentNotFoundError):
        sdk.get_document_metadata("missing")

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

    sdk = _sdk(plan=dms.DmsAssemblyPlan(operation_observer=fail_observer))

    result = _upload_bytes(sdk,
        b"payload",
        filename="safe.txt",
        content_type="text/plain",
    )

    assert result.document_id


def test_remaining_public_results_have_json_compatible_dumps() -> None:
    sdk = _sdk(service_checks={"metadata": lambda: None})
    uploaded = _upload_bytes(sdk,
        b"payload",
        filename="serializable.txt",
        content_type="text/plain",
        document_id="serializable",
    )
    inspection = sdk.inspect_document(uploaded.document_id)
    health = sdk.check_health()
    dry_run = sdk.reconcile_documents(
        status=DocumentStatus.FAILED,
        action=dms.RecoveryAction.MARK_FAILED,
        dry_run=True,
    )
    plan = dry_run.to_plan()

    for value in (inspection, health, dry_run, plan):
        json.dumps(value.to_dict())
    assert health.to_dict()["checked_at"].endswith("+00:00")


def test_access_policy_cannot_be_bypassed_by_content_delete_or_recovery() -> None:
    class TenantPolicy:
        def allows(self, *, operation, context, metadata):
            if metadata is None:
                return context is not None and "recovery-admin" in context.roles
            return (
                context is not None
                and metadata.extra_metadata.get("tenant") == context.tenant
            )

    sdk = _sdk(plan=dms.DmsAssemblyPlan(access_policy=TenantPolicy()))
    uploaded = _upload_bytes(sdk,
        b"protected",
        filename="protected.txt",
        content_type="text/plain",
        document_id="protected",
        metadata={"tenant": "tenant-a"},
    )
    allowed = dms.AccessContext(tenant="tenant-a")
    denied = dms.AccessContext(tenant="tenant-b")

    with pytest.raises(dms.AccessDeniedError):
        sdk.get_document_content(uploaded.document_id, access_context=denied)
    with pytest.raises(dms.AccessDeniedError):
        sdk.get_document_content_stream(uploaded.document_id, access_context=denied)
    with pytest.raises(dms.AccessDeniedError):
        sdk.copy_document_to(uploaded.document_id, BytesIO(), access_context=denied)
    with pytest.raises(dms.AccessDeniedError):
        sdk.get_internal_document_metadata(uploaded.document_id, access_context=denied)
    with pytest.raises(dms.AccessDeniedError):
        sdk.inspect_document(uploaded.document_id, access_context=denied)
    with pytest.raises(dms.AccessDeniedError):
        sdk.delete_document(uploaded.document_id, access_context=denied)
    with pytest.raises(dms.AccessDeniedError):
        sdk.reconcile_document(
            "missing",
            dms.RecoveryAction.PURGE_ORPHAN_OBJECT,
            storage_key="orphan",
            dry_run=True,
            access_context=denied,
        )

    assert sdk.get_document_content(uploaded.document_id, access_context=allowed).content == b"protected"
    assert sdk.inspect_document(uploaded.document_id, access_context=allowed).metadata_exists is True
    assert sdk.delete_document(uploaded.document_id, access_context=allowed).deleted is True


def test_async_high_level_operations_preserve_sync_contracts(tmp_path) -> None:
    path = tmp_path / "async.txt"
    path.write_bytes(b"async payload")

    async def scenario() -> None:
        sdk = dms.create_async_sdk_from_components(
            metadata_store=CursorMemoryStore(),
            object_store=StreamMemoryObjectStore(),
            plan=dms.DmsAssemblyPlan(),
        )
        uploaded = await sdk.upload_file(path)
        listed = [item async for item in sdk.iter_documents(page_size=1)]
        sink = BytesIO()
        copied = await sdk.copy_document_to(uploaded.document_id, sink, chunk_size=2)
        await sdk.aclose()

        assert [item.document_id for item in listed] == [uploaded.document_id]
        assert sink.getvalue() == b"async payload"
        assert sink.closed is False
        assert copied.checksum_verified is True

    asyncio.run(scenario())


def test_operation_observer_covers_document_operation_categories() -> None:
    events = []
    sdk = _sdk(plan=dms.DmsAssemblyPlan(operation_observer=events.append))
    uploaded = _upload_bytes(sdk,
        b"observed",
        filename="observed.txt",
        content_type="text/plain",
        document_id="observed-categories",
    )

    sdk.list_documents(limit=10)
    sdk.get_document_content(uploaded.document_id)
    sdk.inspect_document(uploaded.document_id)
    sdk.check_health()
    sdk.delete_document(uploaded.document_id)

    assert {event.operation for event in events} >= {
        "upload",
        "documents.list",
        "content.get",
        "document.inspect",
        "health.check",
        "document.delete",
    }
