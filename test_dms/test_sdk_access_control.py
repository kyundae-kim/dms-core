from __future__ import annotations

from io import BytesIO

import pytest

import dms
from test_dms.sdk_test_support import (
    CursorMemoryStore,
    RecordingOperationStore,
    StreamMemoryObjectStore,
)
from test_dms.test_sdk_native_async_partitions import (
    AsyncMetadataMemoryStore,
    AsyncObjectMemoryStore,
)

PARTITION = dms.DocumentPartition.personal("access-person")


class RolePolicy:
    def __init__(self, required_role: str) -> None:
        self.required_role = required_role
        self.calls: list[tuple[str, dms.AccessContext | None, object | None]] = []

    def allows(
        self,
        *,
        operation: str,
        context: dms.AccessContext | None,
        metadata: object | None,
    ) -> bool:
        self.calls.append((operation, context, metadata))
        return context is not None and self.required_role in context.roles


class RaisingPolicy:
    def allows(self, *, operation, context, metadata) -> bool:
        del operation, context, metadata
        raise RuntimeError("host policy unavailable")


class AsyncRolePolicy(RolePolicy):
    async def allows(
        self,
        *,
        operation: str,
        context: dms.AccessContext | None,
        metadata: object | None,
    ) -> bool:
        return super().allows(
            operation=operation,
            context=context,
            metadata=metadata,
        )


def _request(document_id: str = "protected") -> dms.UploadDocumentRequest:
    return dms.UploadDocumentRequest(
        document_id=document_id,
        content=b"protected content",
        filename="protected.txt",
        content_type="text/plain",
    )


def _seed() -> tuple[CursorMemoryStore, StreamMemoryObjectStore, str]:
    metadata_store = CursorMemoryStore()
    object_store = StreamMemoryObjectStore()
    sdk = dms.DefaultDocumentManagementSDK(
        metadata_store=metadata_store,
        object_store=object_store,
    )
    uploaded = sdk.upload_document(_request(), partition=PARTITION)
    return metadata_store, object_store, uploaded.document_id


def test_access_contract_exports_host_context_policy_and_denied_error() -> None:
    assert hasattr(dms, "AccessContext")
    assert hasattr(dms, "AsyncDocumentAccessPolicy")
    assert hasattr(dms, "DocumentAccessPolicy")
    assert issubclass(dms.AccessDeniedError, dms.DmsError)

    context = dms.AccessContext(
        subject="user-1",
        groups=frozenset({"group-1"}),
        roles=frozenset({"reader"}),
    )
    assert context.subject == "user-1"
    assert context.groups == frozenset({"group-1"})
    assert context.roles == frozenset({"reader"})


@pytest.mark.parametrize("field_name", ["groups", "roles"])
def test_access_context_rejects_string_collection_values(field_name: str) -> None:
    with pytest.raises(TypeError, match=field_name):
        dms.AccessContext(**{field_name: "not-a-collection"})


def test_denied_upload_is_rejected_before_object_storage() -> None:
    object_store = StreamMemoryObjectStore()
    policy = RolePolicy("writer")
    sdk = dms.DefaultDocumentManagementSDK(
        metadata_store=CursorMemoryStore(),
        object_store=object_store,
        access_policy=policy,
    )

    with pytest.raises(dms.AccessDeniedError) as error:
        sdk.upload_document(
            _request(),
            partition=PARTITION,
            access_context=dms.AccessContext(roles=frozenset({"reader"})),
        )

    assert error.value.code == "access_denied"
    assert error.value.category == "authorization"
    assert error.value.retryable is False
    assert object_store._items == {}
    assert policy.calls[-1][0] == "upload"
    assert policy.calls[-1][2] is None


def test_policy_protects_public_internal_content_stream_copy_inspection_and_delete() -> None:
    metadata_store, object_store, document_id = _seed()
    policy = RolePolicy("reader")
    sdk = dms.DefaultDocumentManagementSDK(
        metadata_store=metadata_store,
        object_store=object_store,
        access_policy=policy,
    )
    denied = dms.AccessContext(roles=frozenset({"guest"}))
    allowed = dms.AccessContext(roles=frozenset({"reader"}))

    allowed_metadata = sdk.get_document_metadata(
        document_id,
        partition=PARTITION,
        access_context=allowed,
    )
    assert not hasattr(allowed_metadata, "storage_key")
    assert policy.calls[-1][2] is allowed_metadata

    denied_calls = (
        lambda: sdk.get_document_metadata(
            document_id,
            partition=PARTITION,
            access_context=denied,
        ),
        lambda: sdk.get_internal_document_metadata(
            document_id,
            partition=PARTITION,
            access_context=denied,
        ),
        lambda: sdk.get_document_content(
            document_id,
            partition=PARTITION,
            access_context=denied,
        ),
        lambda: sdk.get_document_content_stream(
            document_id,
            partition=PARTITION,
            access_context=denied,
        ),
        lambda: sdk.copy_document_to(
            document_id,
            BytesIO(),
            partition=PARTITION,
            access_context=denied,
        ),
        lambda: sdk.inspect_document(
            document_id,
            partition=PARTITION,
            access_context=denied,
        ),
        lambda: sdk.delete_document(
            document_id,
            partition=PARTITION,
            access_context=denied,
        ),
    )
    for call in denied_calls:
        with pytest.raises(dms.AccessDeniedError):
            call()

    assert sdk.get_document_content(
        document_id,
        partition=PARTITION,
        access_context=allowed,
    ).content == b"protected content"


def test_policy_controls_listing_recovery_and_partition_reset() -> None:
    metadata_store, object_store, document_id = _seed()
    policy = RolePolicy("admin")
    sdk = dms.DefaultDocumentManagementSDK(
        metadata_store=metadata_store,
        object_store=object_store,
        access_policy=policy,
    )
    reader = dms.AccessContext(roles=frozenset({"reader"}))
    admin = dms.AccessContext(roles=frozenset({"admin"}))

    for call in (
        lambda: sdk.list_documents(partition=PARTITION, access_context=reader),
        lambda: sdk.list_recovery_candidates(
            partition=PARTITION,
            status=dms.DocumentStatus.FAILED,
            access_context=reader,
        ),
        lambda: sdk.clear_partition_data(
            partition=PARTITION,
            access_context=reader,
        ),
    ):
        with pytest.raises(dms.AccessDeniedError):
            call()

    assert sdk.list_documents(partition=PARTITION, access_context=admin).items[0].document_id == document_id
    result = sdk.clear_partition_data(
        partition=PARTITION,
        access_context=admin,
    )
    assert result.metadata_deleted == 1


def test_policy_covers_all_public_document_operation_categories(tmp_path) -> None:
    metadata_store = CursorMemoryStore()
    object_store = StreamMemoryObjectStore()
    operation_store = RecordingOperationStore()
    policy = RolePolicy("allowed")
    sdk = dms.DefaultDocumentManagementSDK(
        metadata_store=metadata_store,
        object_store=object_store,
        operation_store=operation_store,
        access_policy=policy,
    )
    context = dms.AccessContext(roles=frozenset({"allowed"}))

    uploaded = sdk.upload_document(
        _request("categories"),
        partition=PARTITION,
        access_context=context,
    )
    sdk.upload_document(
        dms.UploadDocumentRequest(
            document_id="idempotent",
            content=b"idempotent",
            filename="idempotent.txt",
            content_type="text/plain",
            idempotency_key="key",
            idempotency_scope="scope",
        ),
        partition=PARTITION,
        access_context=context,
    )
    file_path = tmp_path / "file.txt"
    file_path.write_bytes(b"file")
    sdk.upload_file(file_path, partition=PARTITION, access_context=context)
    sdk.upload_document_stream(
        dms.UploadDocumentStreamRequest(
            stream=BytesIO(b"stream"),
            size=6,
            filename="stream.txt",
            content_type="text/plain",
            document_id="stream",
        ),
        partition=PARTITION,
        access_context=context,
    )

    sdk.get_upload_operation(
        scope="scope",
        idempotency_key="key",
        partition=PARTITION,
        access_context=context,
    )
    sdk.get_document_metadata(
        uploaded.document_id,
        partition=PARTITION,
        access_context=context,
    )
    sdk.get_internal_document_metadata(
        uploaded.document_id,
        partition=PARTITION,
        access_context=context,
    )
    sdk.list_documents(partition=PARTITION, access_context=context)
    list(sdk.iter_documents(partition=PARTITION, access_context=context))
    sdk.get_document_content(
        uploaded.document_id,
        partition=PARTITION,
        access_context=context,
    )
    stream = sdk.get_document_content_stream(
        uploaded.document_id,
        partition=PARTITION,
        access_context=context,
    )
    stream.close()
    sdk.copy_document_to(
        uploaded.document_id,
        BytesIO(),
        partition=PARTITION,
        access_context=context,
    )
    sdk.inspect_document(
        uploaded.document_id,
        partition=PARTITION,
        access_context=context,
    )
    sdk.list_recovery_candidates(
        partition=PARTITION,
        status=dms.DocumentStatus.FAILED,
        access_context=context,
    )
    sdk.reconcile_documents(
        partition=PARTITION,
        status=dms.DocumentStatus.FAILED,
        action=dms.RecoveryAction.MARK_FAILED,
        access_context=context,
    )
    sdk.delete_document(
        uploaded.document_id,
        partition=PARTITION,
        access_context=context,
    )
    sdk.clear_partition_data(partition=PARTITION, access_context=context)
    sdk.initialize_partition_for_data_load(
        partition=PARTITION,
        access_context=context,
    )
    sdk.clear_all_data(access_context=context)
    sdk.initialize_for_data_load(access_context=context)

    assert {
        "upload",
        "upload.operation.get",
        "metadata.get",
        "metadata.internal",
        "documents.list",
        "content.get",
        "content.stream",
        "content.copy",
        "document.inspect",
        "recovery.list",
        "recovery.execute",
        "document.delete",
        "data.clear_partition",
        "data.initialize_partition_for_data_load",
        "data.clear_all",
        "data.initialize_for_data_load",
    }.issubset({operation for operation, _, _ in policy.calls})


def test_policy_failures_are_mapped_to_access_denied() -> None:
    metadata_store, object_store, document_id = _seed()
    sdk = dms.DefaultDocumentManagementSDK(
        metadata_store=metadata_store,
        object_store=object_store,
        access_policy=RaisingPolicy(),
    )

    with pytest.raises(dms.AccessDeniedError) as error:
        sdk.get_document_metadata(
            document_id,
            partition=PARTITION,
            access_context=dms.AccessContext(subject="user-1"),
        )

    assert error.value.__cause__ is not None
    assert error.value.code == "access_denied"
    assert "host policy unavailable" not in str(error.value)


def test_policy_can_distinguish_hard_delete_from_soft_delete() -> None:
    metadata_store, object_store, document_id = _seed()

    class SoftDeleteOnlyPolicy:
        def allows(self, *, operation, context, metadata) -> bool:
            del context, metadata
            return operation != "document.hard_delete"

    sdk = dms.DefaultDocumentManagementSDK(
        metadata_store=metadata_store,
        object_store=object_store,
        access_policy=SoftDeleteOnlyPolicy(),
    )
    context = dms.AccessContext(subject="user-1")

    sdk.soft_delete_document(
        document_id,
        partition=PARTITION,
        access_context=context,
    )

    metadata_store, object_store, hard_document_id = _seed()
    sdk = dms.DefaultDocumentManagementSDK(
        metadata_store=metadata_store,
        object_store=object_store,
        access_policy=SoftDeleteOnlyPolicy(),
    )
    with pytest.raises(dms.AccessDeniedError):
        sdk.hard_delete_document(
            hard_document_id,
            partition=PARTITION,
            access_context=context,
        )
    assert sdk.get_internal_document_metadata(
        hard_document_id,
        partition=PARTITION,
        access_context=context,
    ).document_id == hard_document_id


def test_async_sync_backed_facade_forwards_access_context() -> None:
    policy = RolePolicy("writer")
    sdk = dms.AsyncDocumentManagementSDK(
        dms.DefaultDocumentManagementSDK(
            metadata_store=CursorMemoryStore(),
            object_store=StreamMemoryObjectStore(),
            access_policy=policy,
        )
    )

    async def scenario() -> None:
        with pytest.raises(dms.AccessDeniedError):
            await sdk.upload_document(
                _request("async-denied"),
                partition=PARTITION,
                access_context=dms.AccessContext(roles=frozenset({"reader"})),
            )
        uploaded = await sdk.upload_document(
            _request("async-allowed"),
            partition=PARTITION,
            access_context=dms.AccessContext(roles=frozenset({"writer"})),
        )
        assert uploaded.document_id == "async-allowed"

    import asyncio

    asyncio.run(scenario())


@pytest.mark.asyncio
async def test_native_async_policy_supports_async_host_callback() -> None:
    policy = AsyncRolePolicy("writer")
    sdk = dms.AsyncDocumentManagementSDK.from_async_components(
        metadata_store=AsyncMetadataMemoryStore(),
        object_store=AsyncObjectMemoryStore(),
        access_policy=policy,
    )

    with pytest.raises(dms.AccessDeniedError):
        await sdk.upload_document(
            _request("native-denied"),
            partition=PARTITION,
            access_context=dms.AccessContext(roles=frozenset({"reader"})),
        )
    uploaded = await sdk.upload_document(
        _request("native-allowed"),
        partition=PARTITION,
        access_context=dms.AccessContext(roles=frozenset({"writer"})),
    )

    assert uploaded.document_id == "native-allowed"
    assert policy.calls[0][0] == "upload"
    with pytest.raises(dms.AccessDeniedError):
        await sdk.get_document_content(
            uploaded.document_id,
            partition=PARTITION,
            access_context=dms.AccessContext(roles=frozenset({"reader"})),
        )
    assert (
        await sdk.get_document_content(
            uploaded.document_id,
            partition=PARTITION,
            access_context=dms.AccessContext(roles=frozenset({"writer"})),
        )
    ).content == b"protected content"
