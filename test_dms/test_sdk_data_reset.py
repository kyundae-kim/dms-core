from __future__ import annotations

import json

import pytest

import dms
from dms.domain.interfaces import PutObjectRequest
from test_dms.sdk_test_support import CursorMemoryStore, StreamMemoryObjectStore


class ResettableOperationStore:
    def __init__(self, count: int = 0) -> None:
        self.records = [f"operation-{index}" for index in range(count)]

    def clear_all(self) -> int:
        count = len(self.records)
        self.records.clear()
        return count


class FailingMetadataStore(CursorMemoryStore):
    def clear_all(self) -> int:
        raise RuntimeError("metadata clear failed")


def _sdk(
    *,
    metadata_store=None,
    object_store=None,
    operation_store=None,
    access_policy=None,
    operation_observer=None,
):
    return dms.DefaultDocumentManagementSDK(
        metadata_store=metadata_store or CursorMemoryStore(),
        object_store=object_store or StreamMemoryObjectStore(),
        operation_store=operation_store,
        access_policy=access_policy,
        operation_observer=operation_observer,
    )


def _upload(sdk, document_id: str) -> None:
    sdk.upload_document(
        dms.UploadDocumentRequest(
            document_id=document_id,
            content=document_id.encode(),
            filename=f"{document_id}.txt",
            content_type="text/plain",
        )
    )


def test_clear_all_data_removes_documents_objects_and_upload_operations() -> None:
    metadata_store = CursorMemoryStore()
    object_store = StreamMemoryObjectStore()
    operation_store = ResettableOperationStore(count=2)
    sdk = _sdk(
        metadata_store=metadata_store,
        object_store=object_store,
        operation_store=operation_store,
    )
    _upload(sdk, "one")
    _upload(sdk, "two")
    object_store.put_object(
        PutObjectRequest(
            document_id="orphan",
            storage_key="documents/orphan/orphan.txt",
            content=b"orphan",
            content_type="text/plain",
            filename="orphan.txt",
        )
    )

    result = sdk.clear_all_data()

    assert result.metadata_deleted == 2
    assert result.objects_deleted == 3
    assert result.upload_operations_deleted == 2
    assert result.ready_for_data_load is True
    assert result.total_deleted == 7
    assert sdk.list_documents().items == []
    assert object_store._items == {}
    assert operation_store.records == []
    json.dumps(result.to_dict())


def test_initialize_for_data_load_is_idempotent_and_leaves_empty_store() -> None:
    sdk = _sdk()
    _upload(sdk, "before-load")

    first = sdk.initialize_for_data_load()
    second = sdk.initialize_for_data_load()

    assert first.metadata_deleted == 1
    assert first.ready_for_data_load is True
    assert second.to_dict() == {
        "metadata_deleted": 0,
        "objects_deleted": 0,
        "upload_operations_deleted": 0,
        "ready_for_data_load": True,
        "total_deleted": 0,
    }
    assert sdk.list_documents().items == []


def test_clear_all_data_reports_partial_cleanup_and_continues_other_stores() -> None:
    metadata_store = FailingMetadataStore()
    object_store = StreamMemoryObjectStore()
    operation_store = ResettableOperationStore(count=1)
    sdk = _sdk(
        metadata_store=metadata_store,
        object_store=object_store,
        operation_store=operation_store,
    )
    # Populate the object store directly because metadata clear is intentionally broken.
    object_store.put_object(
        PutObjectRequest(
            document_id="orphan",
            storage_key="documents/orphan/orphan.txt",
            content=b"orphan",
            content_type="text/plain",
            filename="orphan.txt",
        )
    )

    with pytest.raises(dms.DataResetError) as error:
        sdk.clear_all_data()

    assert error.value.result.metadata_deleted == 0
    assert error.value.result.objects_deleted == 1
    assert error.value.result.upload_operations_deleted == 1
    assert error.value.result.ready_for_data_load is False
    assert error.value.failed_stores == ("metadata",)
    assert error.value.errors[0].args == ("metadata clear failed",)
    assert object_store._items == {}
    assert operation_store.records == []


def test_data_reset_observer_reports_partial_readiness() -> None:
    events: list[dms.OperationEvent] = []

    def observe(event: dms.OperationEvent) -> None:
        events.append(event)

    sdk = _sdk(
        metadata_store=FailingMetadataStore(),
        operation_observer=observe,
    )

    with pytest.raises(dms.DataResetError):
        sdk.clear_all_data()

    assert events[-1].operation == "data.clear_all"
    assert events[-1].succeeded is False
    assert events[-1].error_code == "data_reset_failed"
    assert events[-1].conditions == {"ready_for_data_load": False}


def test_default_sdk_satisfies_data_resetter_contract() -> None:
    sdk = _sdk()

    assert isinstance(sdk, dms.DataResetter)


def test_data_reset_obeys_host_access_policy() -> None:
    class AdminOnlyPolicy:
        def allows(self, *, operation, context, metadata):
            assert operation in {"data.clear_all", "data.initialize_for_data_load"}
            assert metadata is None
            return context is not None and "admin" in context.roles

    sdk = _sdk(access_policy=AdminOnlyPolicy())
    _upload(sdk, "protected")

    with pytest.raises(dms.AccessDeniedError):
        sdk.clear_all_data(access_context=dms.AccessContext(roles=frozenset({"reader"})))

    result = sdk.initialize_for_data_load(
        access_context=dms.AccessContext(roles=frozenset({"admin"})),
    )

    assert result.metadata_deleted == 1


@pytest.mark.asyncio
async def test_async_data_reset_operations_match_sync_contract() -> None:
    sdk = dms.AsyncDocumentManagementSDK(
        dms.DefaultDocumentManagementSDK(
            metadata_store=CursorMemoryStore(),
            object_store=StreamMemoryObjectStore(),
        )
    )
    await sdk.upload_document(
        dms.UploadDocumentRequest(
            document_id="async-document",
            content=b"payload",
            filename="async.txt",
            content_type="text/plain",
        )
    )

    result = await sdk.initialize_for_data_load()

    assert result.ready_for_data_load is True
    assert result.metadata_deleted == 1
    assert (await sdk.list_documents()).items == []



def test_data_reset_result_exposes_json_schema() -> None:
    schema = dms.DataResetResult.json_schema()

    assert schema["title"] == "DataResetResult"
    assert schema["properties"]["total_deleted"] == {"type": "integer", "minimum": 0}
    assert dms.DataResetResult.model_json_schema() == schema
