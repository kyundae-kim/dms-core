from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from io import BytesIO
from types import SimpleNamespace

import pytest
from minio import Minio
from sqlalchemy.ext.asyncio import create_async_engine

import dms
from dms.domain.interfaces import (
    AsyncStoredObjectStream,
    PutObjectRequest,
    PutObjectStreamRequest,
    StoredObject,
)
from dms.domain.models import (
    DocumentMetadata,
    DocumentPartition,
    DocumentStatus,
    UploadOperation,
    UploadOperationClaim,
    UploadOperationState,
)
from dms.infrastructure.storage.minio import AsyncMinioObjectStore, MinioObjectStore
from dms.sdk.contracts import partition_storage_prefix
from dms.sdk.factory import AsyncDocumentManagementSDKFactory
from test_dms.sdk_test_support import CursorMemoryStore

PARTITION = DocumentPartition.personal("native-person")
OTHER_PARTITION = DocumentPartition.group("native-group")


class AsyncMetadataMemoryStore:
    def __init__(self) -> None:
        self.inner = CursorMemoryStore()

    async def allocate_document_id(self) -> str:
        return self.inner.allocate_document_id()

    async def save_metadata(self, metadata: DocumentMetadata) -> DocumentMetadata:
        return self.inner.save_metadata(metadata)

    async def update_metadata(self, metadata: DocumentMetadata) -> DocumentMetadata:
        return self.inner.update_metadata(metadata)

    async def get_metadata(
        self,
        document_id: str,
        *,
        partition: DocumentPartition,
    ) -> DocumentMetadata:
        return self.inner.get_metadata(document_id, partition=partition)

    async def list_metadata(
        self,
        *,
        offset: int,
        limit: int,
        partition: DocumentPartition,
        status: DocumentStatus | None = None,
        excluded_statuses: tuple[DocumentStatus, ...] = (),
    ) -> list[DocumentMetadata]:
        return self.inner.list_metadata(
            offset=offset,
            limit=limit,
            partition=partition,
            status=status,
            excluded_statuses=excluded_statuses,
        )

    async def list_metadata_page(
        self,
        *,
        partition: DocumentPartition,
        after_created_at=None,
        after_document_id=None,
        limit: int,
        status: DocumentStatus | None = None,
        excluded_statuses: tuple[DocumentStatus, ...] = (),
    ) -> list[DocumentMetadata]:
        return self.inner.list_metadata_page(
            partition=partition,
            after_created_at=after_created_at,
            after_document_id=after_document_id,
            limit=limit,
            status=status,
            excluded_statuses=excluded_statuses,
        )

    async def mark_deleted(
        self,
        document_id: str,
        *,
        partition: DocumentPartition,
    ) -> DocumentMetadata:
        return self.inner.mark_deleted(document_id, partition=partition)

    async def hard_delete(
        self,
        document_id: str,
        *,
        partition: DocumentPartition,
    ) -> None:
        self.inner.hard_delete(document_id, partition=partition)

    async def clear_all(self) -> int:
        return self.inner.clear_all()

    async def clear_partition(self, *, partition: DocumentPartition) -> int:
        return self.inner.clear_partition(partition=partition)

    async def exists(self, document_id: str) -> bool:
        return self.inner.exists(document_id)


class AsyncBytesStream:
    def __init__(self, content: bytes) -> None:
        self._stream = BytesIO(content)

    async def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)


class FakeAsyncResponse:
    def __init__(self, content: bytes, content_type: str) -> None:
        self.content = AsyncBytesStream(content)
        self.content_length = len(content)
        self.headers = {"Content-Type": content_type}
        self.released = 0
        self.closed = 0

    async def read(self) -> bytes:
        return await self.content.read()

    def release(self) -> None:
        self.released += 1

    def close(self) -> None:
        self.closed += 1


class FakeAsyncMinioClient:
    def __init__(self) -> None:
        self.bucket_created = 0
        self.items: dict[str, tuple[bytes, str, dict[str, str]]] = {}
        self.responses: list[FakeAsyncResponse] = []

    async def bucket_exists(self, bucket_name: str) -> bool:
        return self.bucket_created > 0

    async def make_bucket(self, bucket_name: str) -> None:
        self.bucket_created += 1

    async def put_object(
        self,
        bucket_name: str,
        object_name: str,
        data,
        length: int,
        *,
        content_type: str,
        metadata: dict[str, str],
    ) -> None:
        content = data.read()
        assert len(content) == length
        self.items[object_name] = (content, content_type, metadata)

    async def stat_object(self, bucket_name: str, object_name: str):
        try:
            content, content_type, metadata = self.items[object_name]
        except KeyError as exc:
            error = LookupError(object_name)
            error.code = "NoSuchKey"  # type: ignore[attr-defined]
            raise error from exc
        return SimpleNamespace(
            size=len(content),
            content_type=content_type,
            metadata=metadata,
        )

    async def get_object(self, bucket_name: str, object_name: str):
        content, content_type, _ = self.items[object_name]
        response = FakeAsyncResponse(content, content_type)
        self.responses.append(response)
        return response

    async def remove_object(self, bucket_name: str, object_name: str) -> None:
        del self.items[object_name]

    def list_objects(
        self,
        bucket_name: str,
        *,
        prefix: str,
        recursive: bool,
    ):
        async def iterate():
            for object_name in sorted(self.items):
                if object_name.startswith(prefix):
                    yield SimpleNamespace(object_name=object_name)

        return iterate()


class AsyncObjectMemoryStore:
    def __init__(self) -> None:
        self.items: dict[str, tuple[bytes, str, str, str | None]] = {}
        self.calls: list[str] = []
        self.close_calls = 0

    async def put_object(self, request: PutObjectRequest) -> str:
        self.calls.append("put_object")
        self.items[request.storage_key] = (
            request.content,
            request.content_type,
            request.filename,
            request.checksum,
        )
        return request.storage_key

    async def put_object_stream(self, request: PutObjectStreamRequest) -> str:
        self.calls.append("put_object_stream")
        content = request.stream.read()
        if hasattr(content, "__await__"):
            content = await content
        self.items[request.storage_key] = (
            content,
            request.content_type,
            request.filename,
            request.checksum,
        )
        return request.storage_key

    async def get_object(self, document_id: str, storage_key: str) -> StoredObject:
        self.calls.append("get_object")
        content, content_type, filename, checksum = self.items[storage_key]
        return StoredObject(
            document_id=document_id,
            storage_key=storage_key,
            content=content,
            content_type=content_type,
            filename=filename,
            size=len(content),
            checksum=checksum,
        )

    async def get_object_stream(
        self,
        document_id: str,
        storage_key: str,
    ) -> AsyncStoredObjectStream:
        self.calls.append("get_object_stream")
        content, content_type, filename, checksum = self.items[storage_key]

        async def close() -> None:
            self.close_calls += 1

        return AsyncStoredObjectStream(
            document_id=document_id,
            storage_key=storage_key,
            stream=AsyncBytesStream(content),
            content_type=content_type,
            filename=filename,
            size=len(content),
            checksum=checksum,
            close_callback=close,
        )

    async def delete_object(self, document_id: str, storage_key: str) -> None:
        self.calls.append("delete_object")
        del self.items[storage_key]

    async def clear_all(self) -> int:
        count = len(self.items)
        self.items.clear()
        return count

    async def clear_partition(self, *, partition: DocumentPartition) -> int:
        prefix = partition_storage_prefix(partition)
        keys = [key for key in self.items if key.startswith(prefix)]
        for key in keys:
            del self.items[key]
        return len(keys)

    async def object_exists(self, document_id: str, storage_key: str) -> bool:
        return storage_key in self.items


class BlockingAfterWriteObjectStore(AsyncObjectMemoryStore):
    def __init__(self) -> None:
        super().__init__()
        self.written = asyncio.Event()
        self.release = asyncio.Event()

    async def put_object(self, request: PutObjectRequest) -> str:
        storage_key = await super().put_object(request)
        self.written.set()
        await self.release.wait()
        return storage_key


class BlockingAfterWriteStreamObjectStore(AsyncObjectMemoryStore):
    def __init__(self) -> None:
        super().__init__()
        self.written = asyncio.Event()
        self.release = asyncio.Event()

    async def put_object_stream(self, request: PutObjectStreamRequest) -> str:
        storage_key = await super().put_object_stream(request)
        self.written.set()
        await self.release.wait()
        return storage_key


class AsyncOperationMemoryStore:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str], UploadOperation] = {}

    async def claim(self, *, scope, idempotency_key, fingerprint, document_id):
        key = (scope, idempotency_key)
        existing = self.records.get(key)
        if existing is not None:
            return UploadOperationClaim(operation=existing, claimed=False)
        now = datetime.now(UTC)
        operation = UploadOperation(
            scope=scope,
            idempotency_key=idempotency_key,
            fingerprint=fingerprint,
            document_id=document_id,
            state=UploadOperationState.PENDING,
            created_at=now,
            updated_at=now,
        )
        self.records[key] = operation
        return UploadOperationClaim(operation=operation, claimed=True)

    async def get(self, *, scope, idempotency_key):
        try:
            return self.records[(scope, idempotency_key)]
        except KeyError as exc:
            raise LookupError((scope, idempotency_key)) from exc

    async def mark_succeeded(self, *, scope, idempotency_key):
        key = (scope, idempotency_key)
        self.records[key] = replace(
            self.records[key],
            state=UploadOperationState.SUCCEEDED,
        )

    async def mark_failed(self, *, scope, idempotency_key):
        key = (scope, idempotency_key)
        self.records[key] = replace(
            self.records[key],
            state=UploadOperationState.FAILED,
        )

    async def clear_all(self, *, scope_prefix=None) -> int:
        keys = [
            key
            for key in self.records
            if scope_prefix is None or key[0].startswith(scope_prefix)
        ]
        for key in keys:
            del self.records[key]
        return len(keys)


def _sdk() -> tuple[dms.AsyncDocumentManagementSDK, AsyncObjectMemoryStore]:
    objects = AsyncObjectMemoryStore()
    sdk = dms.AsyncDocumentManagementSDK.from_async_components(
        metadata_store=AsyncMetadataMemoryStore(),
        object_store=objects,
        operation_store=AsyncOperationMemoryStore(),
    )
    return sdk, objects


@pytest.mark.asyncio
async def test_native_async_core_awaits_object_storage_and_preserves_partition() -> (
    None
):
    sdk, objects = _sdk()

    uploaded = await sdk.upload_document(
        dms.UploadDocumentRequest(
            document_id="native-document",
            content=b"native-content",
            filename="native.txt",
            content_type="text/plain",
        ),
        partition=PARTITION,
    )
    internal = await sdk.get_internal_document_metadata(
        uploaded.document_id,
        partition=PARTITION,
    )
    content = await sdk.get_document_content(
        uploaded.document_id,
        partition=PARTITION,
    )

    assert isinstance(internal.storage_key, str)
    assert internal.partition == PARTITION
    assert content.content == b"native-content"
    assert objects.calls[:2] == ["put_object", "get_object"]
    with pytest.raises(dms.DocumentNotFoundError):
        await sdk.get_document_metadata(uploaded.document_id, partition=OTHER_PARTITION)

    await sdk.hard_delete_document(uploaded.document_id, partition=PARTITION)
    assert objects.items == {}


@pytest.mark.asyncio
async def test_native_async_stream_forwards_adapter_close_callback() -> None:
    sdk, objects = _sdk()
    uploaded = await sdk.upload_document(
        dms.UploadDocumentRequest(
            document_id="native-stream",
            content=b"stream-content",
            filename="stream.txt",
            content_type="text/plain",
        ),
        partition=PARTITION,
    )

    stream = await sdk.get_document_content_stream(
        uploaded.document_id,
        chunk_size=3,
        partition=PARTITION,
    )
    chunks = [chunk async for chunk in stream.aiter_chunks_closing()]
    await stream.aclose()

    assert b"".join(chunks) == b"stream-content"
    assert objects.close_calls == 1


@pytest.mark.asyncio
async def test_async_stream_marks_cleanup_complete_before_propagating_cancellation() -> (
    None
):
    started = asyncio.Event()
    release = asyncio.Event()
    close_calls = 0

    async def close() -> None:
        nonlocal close_calls
        started.set()
        await release.wait()
        close_calls += 1

    stream = dms.AsyncDocumentContentStream(
        document_id="cancel-stream",
        _async_stream=AsyncBytesStream(b"content"),
        _async_close_callback=close,
    )
    close_task = asyncio.create_task(stream.aclose())
    await started.wait()

    close_task.cancel()
    await asyncio.sleep(0)
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await close_task

    assert stream.closed is True
    await stream.aclose()
    assert close_calls == 1


@pytest.mark.asyncio
async def test_native_async_partition_reset_rejects_none_without_global_wipe() -> None:
    sdk, _ = _sdk()
    uploaded = await sdk.upload_document(
        dms.UploadDocumentRequest(
            document_id="async-kept",
            content=b"kept",
            filename="kept.txt",
            content_type="text/plain",
        ),
        partition=PARTITION,
    )

    with pytest.raises(dms.ValidationError, match="partition"):
        await sdk.clear_partition_data(partition=None)  # type: ignore[arg-type]
    with pytest.raises(dms.ValidationError, match="partition"):
        await sdk.initialize_partition_for_data_load(
            partition=None  # type: ignore[arg-type]
        )

    assert (
        await sdk.get_document_metadata(uploaded.document_id, partition=PARTITION)
    ).document_id == uploaded.document_id


@pytest.mark.asyncio
async def test_native_async_reset_does_not_wrap_async_store_calls_in_threads(
    monkeypatch,
) -> None:
    sdk, _ = _sdk()

    async def fail_to_thread(*args, **kwargs):
        del args, kwargs
        raise AssertionError("native async reset must not use a thread wrapper")

    monkeypatch.setattr(asyncio, "to_thread", fail_to_thread)

    result = await sdk.clear_all_data()

    assert result.ready_for_data_load is True


@pytest.mark.asyncio
async def test_native_async_partition_reset_clears_operation_records_in_scope() -> None:
    sdk, _ = _sdk()
    for document_id, partition in (
        ("reset-personal", PARTITION),
        ("reset-group", OTHER_PARTITION),
    ):
        await sdk.upload_document(
            dms.UploadDocumentRequest(
                document_id=document_id,
                content=document_id.encode(),
                filename=f"{document_id}.txt",
                content_type="text/plain",
                idempotency_key="same-key",
                idempotency_scope="same-scope",
            ),
            partition=partition,
        )

    result = await sdk.clear_partition_data(partition=PARTITION)

    assert result.metadata_deleted == 1
    assert result.objects_deleted == 1
    assert result.upload_operations_deleted == 1
    with pytest.raises(dms.UploadOperationNotFoundError):
        await sdk.get_upload_operation(
            scope="same-scope",
            idempotency_key="same-key",
            partition=PARTITION,
        )
    assert (
        await sdk.get_upload_operation(
            scope="same-scope",
            idempotency_key="same-key",
            partition=OTHER_PARTITION,
        )
    ).document_id == "reset-group"


@pytest.mark.asyncio
async def test_native_async_partition_only_operations_reject_invalid_values() -> None:
    sdk, _ = _sdk()
    uploaded = await sdk.upload_document(
        dms.UploadDocumentRequest(
            document_id="invalid-async-partition-target",
            content=b"content",
            filename="content.txt",
            content_type="text/plain",
        ),
        partition=PARTITION,
    )

    calls = (
        lambda: sdk.get_document_metadata(
            uploaded.document_id,
            partition=None,  # type: ignore[arg-type]
        ),
        lambda: sdk.list_documents(partition=None),  # type: ignore[arg-type]
        lambda: sdk.inspect_document(
            uploaded.document_id,
            partition=None,  # type: ignore[arg-type]
        ),
        lambda: sdk.list_recovery_candidates(
            status=DocumentStatus.FAILED,
            partition=None,  # type: ignore[arg-type]
        ),
    )
    for call in calls:
        with pytest.raises(dms.ValidationError, match="partition"):
            await call()


@pytest.mark.asyncio
async def test_native_async_wrong_partition_recovery_returns_not_found() -> None:
    sdk, _ = _sdk()
    uploaded = await sdk.upload_document(
        dms.UploadDocumentRequest(
            document_id="wrong-recovery-partition",
            content=b"content",
            filename="content.txt",
            content_type="text/plain",
        ),
        partition=PARTITION,
    )

    inspection = await sdk.inspect_document(
        uploaded.document_id,
        partition=OTHER_PARTITION,
    )
    assert inspection.metadata_exists is False
    assert inspection.issue.value == "metadata_missing"

    with pytest.raises(dms.DocumentNotFoundError):
        await sdk.reconcile_document(
            uploaded.document_id,
            dms.RecoveryAction.MARK_FAILED,
            partition=OTHER_PARTITION,
        )


@pytest.mark.asyncio
async def test_native_async_orphan_recovery_rejects_another_document_key() -> None:
    sdk, _ = _sdk()
    uploaded = await sdk.upload_document(
        dms.UploadDocumentRequest(
            document_id="live-async-orphan-boundary",
            content=b"content",
            filename="content.txt",
            content_type="text/plain",
        ),
        partition=PARTITION,
    )
    internal = await sdk.get_internal_document_metadata(
        uploaded.document_id,
        partition=PARTITION,
    )

    with pytest.raises(dms.ValidationError, match="document"):
        await sdk.reconcile_document(
            "missing-async-orphan",
            dms.RecoveryAction.PURGE_ORPHAN_OBJECT,
            storage_key=internal.storage_key,
            partition=PARTITION,
        )

    assert (
        await sdk.get_document_content(
            uploaded.document_id,
            partition=PARTITION,
        )
    ).content == b"content"


def test_async_factory_rejects_synchronous_minio_client() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        with pytest.raises(dms.ConfigurationError, match="async MinIO"):
            AsyncDocumentManagementSDKFactory(
                engine=engine,
                minio_client=Minio("localhost:9000", secure=False),
                bucket_name="documents",
            )
    finally:
        # No connection was opened; sync disposal is sufficient for constructor testing.
        engine.sync_engine.dispose()


@pytest.mark.asyncio
async def test_native_async_idempotent_upload_finishes_before_propagating_cancellation() -> (
    None
):
    metadata_store = AsyncMetadataMemoryStore()
    object_store = BlockingAfterWriteObjectStore()
    operation_store = AsyncOperationMemoryStore()
    sdk = dms.AsyncDocumentManagementSDK.from_async_components(
        metadata_store=metadata_store,
        object_store=object_store,
        operation_store=operation_store,
    )
    task = asyncio.create_task(
        sdk.upload_document(
            dms.UploadDocumentRequest(
                document_id="cancel-native",
                content=b"cancel-content",
                filename="cancel.txt",
                content_type="text/plain",
                idempotency_key="cancel-key",
                idempotency_scope="cancel-scope",
            ),
            partition=PARTITION,
        )
    )
    await object_store.written.wait()

    task.cancel()
    await asyncio.sleep(0)
    object_store.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(operation_store.records) == 1
    operation = next(iter(operation_store.records.values()))
    assert operation.state is UploadOperationState.SUCCEEDED
    assert (
        metadata_store.inner.get_metadata(
            "cancel-native",
            partition=PARTITION,
        ).status
        is DocumentStatus.AVAILABLE
    )


@pytest.mark.asyncio
async def test_native_async_upload_without_idempotency_finishes_before_cancellation() -> (
    None
):
    metadata_store = AsyncMetadataMemoryStore()
    object_store = BlockingAfterWriteObjectStore()
    sdk = dms.AsyncDocumentManagementSDK.from_async_components(
        metadata_store=metadata_store,
        object_store=object_store,
    )
    task = asyncio.create_task(
        sdk.upload_document(
            dms.UploadDocumentRequest(
                document_id="cancel-untracked",
                content=b"cancel-content",
                filename="cancel.txt",
                content_type="text/plain",
            ),
            partition=PARTITION,
        )
    )
    await object_store.written.wait()

    task.cancel()
    await asyncio.sleep(0)
    object_store.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert (
        await sdk.get_document_content(
            "cancel-untracked",
            partition=PARTITION,
        )
    ).content == b"cancel-content"


@pytest.mark.asyncio
async def test_native_async_stream_upload_finishes_before_cancellation() -> None:
    metadata_store = AsyncMetadataMemoryStore()
    object_store = BlockingAfterWriteStreamObjectStore()
    sdk = dms.AsyncDocumentManagementSDK.from_async_components(
        metadata_store=metadata_store,
        object_store=object_store,
    )
    task = asyncio.create_task(
        sdk.upload_document_stream(
            dms.UploadDocumentStreamRequest(
                stream=BytesIO(b"cancel-stream-content"),
                size=len(b"cancel-stream-content"),
                filename="cancel-stream.txt",
                content_type="text/plain",
                document_id="cancel-stream-upload",
            ),
            partition=PARTITION,
        )
    )
    await object_store.written.wait()

    task.cancel()
    await asyncio.sleep(0)
    object_store.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert (
        await sdk.get_document_content(
            "cancel-stream-upload",
            partition=PARTITION,
        )
    ).content == b"cancel-stream-content"


@pytest.mark.asyncio
async def test_async_minio_adapter_uses_native_client_and_releases_responses() -> None:
    client = FakeAsyncMinioClient()
    store = AsyncMinioObjectStore(client=client, bucket_name="documents")
    await store.initialize()
    await store.initialize()
    storage_key = "documents/partitions/personal/hash/doc/content.txt"

    await store.put_object(
        PutObjectRequest(
            document_id="doc",
            storage_key=storage_key,
            content=b"content",
            content_type="text/plain",
            filename="content.txt",
            checksum="checksum",
        )
    )
    eager = await store.get_object("doc", storage_key)
    stream = await store.get_object_stream("doc", storage_key)
    streamed = await stream.stream.read()
    assert stream.close_callback is not None
    await stream.close_callback()

    assert client.bucket_created == 1
    assert eager.content == b"content"
    assert streamed == b"content"
    assert client.responses[0].released == 1
    assert client.responses[0].closed == 1
    assert client.responses[1].released == 1
    assert client.responses[1].closed == 1
    assert await store.object_exists("doc", storage_key) is True
    assert await store.object_exists("missing", storage_key + ".missing") is False


@pytest.mark.asyncio
async def test_async_factory_wires_native_async_minio_adapter() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    client = FakeAsyncMinioClient()
    try:
        sdk = await AsyncDocumentManagementSDKFactory(
            engine=engine,
            minio_client=client,
            bucket_name="documents",
        ).create_async()

        assert isinstance(sdk._object_store, AsyncMinioObjectStore)
        assert client.bucket_created == 1
    finally:
        await engine.dispose()


def test_sync_minio_exists_only_maps_actual_not_found_errors_to_false() -> None:
    class Client:
        error: Exception

        def bucket_exists(self, bucket_name: str) -> bool:
            return True

        def stat_object(self, bucket_name: str, storage_key: str) -> object:
            raise self.error

    client = Client()
    store = MinioObjectStore(client=client, bucket_name="documents")
    missing = LookupError("missing")
    missing.code = "NoSuchKey"  # type: ignore[attr-defined]
    client.error = missing
    assert store.object_exists("doc", "missing") is False

    client.error = RuntimeError("backend unavailable")
    with pytest.raises(RuntimeError, match="backend unavailable"):
        store.object_exists("doc", "object")
