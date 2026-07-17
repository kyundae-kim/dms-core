from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from dms import UploadDocumentRequest, UploadDocumentStreamRequest
from dms.domain.interfaces import PutObjectRequest, PutObjectStreamRequest
from dms.infrastructure.storage.minio import MinioObjectStore
from dms.sdk import UploadDocumentStreamRequest as SdkExport
from dms.sdk.errors import DuplicateDocumentError, ValidationError
from dms.sdk.factory import create_sdk_from_components
from test_dms.test_sdk_behavior import FailingMetadataStore, InMemoryMetadataStore, InMemoryObjectStore


class StreamingObjectStore(InMemoryObjectStore):
    def __init__(self) -> None:
        super().__init__()
        self.deleted: list[tuple[str, str]] = []
        self.chunks: list[int] = []

    def put_object_stream(self, request: PutObjectStreamRequest) -> str:
        parts = []
        while chunk := request.stream.read(request.chunk_size):
            self.chunks.append(len(chunk))
            parts.append(chunk)
        return self.put_object(PutObjectRequest(
            document_id=request.document_id, storage_key=request.storage_key,
            content=b"".join(parts), content_type=request.content_type,
            filename=request.filename, checksum=request.checksum, metadata=request.metadata,
        ))

    def delete_object(self, document_id: str, storage_key: str) -> None:
        self.deleted.append((document_id, storage_key))
        super().delete_object(document_id, storage_key)


class CollisionMetadataStore(InMemoryMetadataStore):
    def save_metadata(self, metadata):
        raise IntegrityError("insert", {}, RuntimeError("collision"))


def request(content: bytes, **changes) -> UploadDocumentStreamRequest:
    values = dict(stream=BytesIO(content), size=len(content), filename="data.bin", content_type="application/octet-stream", document_id="stream-1", chunk_size=3)
    values.update(changes)
    return UploadDocumentStreamRequest(**values)


def test_stream_request_is_public_and_uploads_in_chunks_without_bytes_api() -> None:
    assert SdkExport is UploadDocumentStreamRequest
    metadata, objects = InMemoryMetadataStore(), StreamingObjectStore()
    sdk = create_sdk_from_components(metadata_store=metadata, object_store=objects)
    result = sdk.upload_document_stream(request(b"abcdefgh"))
    assert objects.chunks == [3, 3, 2]
    assert result.metadata.file_size == 8
    assert sdk.get_document_content(result.document_id).content == b"abcdefgh"
    assert result.metadata.checksum == sha256(b"abcdefgh").hexdigest()


@pytest.mark.parametrize("changes", [{"size": 0}, {"size": -1}, {"chunk_size": 0}, {"chunk_size": -1}])
def test_stream_upload_rejects_non_positive_size_and_chunk_size_before_storage(changes) -> None:
    objects = StreamingObjectStore()
    sdk = create_sdk_from_components(metadata_store=InMemoryMetadataStore(), object_store=objects)
    with pytest.raises(ValidationError):
        sdk.upload_document_stream(request(b"abc", **changes))
    assert not objects._items


def test_stream_upload_enforces_declared_size_and_checksum_and_rolls_back() -> None:
    for changes in ({"size": 4}, {"checksum": "0" * 64}):
        objects = StreamingObjectStore()
        sdk = create_sdk_from_components(metadata_store=InMemoryMetadataStore(), object_store=objects)
        with pytest.raises(ValidationError):
            sdk.upload_document_stream(request(b"abc", **changes))
        assert not objects._items
        assert objects.deleted


def test_stream_upload_rolls_back_metadata_failure_and_insert_collision() -> None:
    for metadata, error in ((FailingMetadataStore(), Exception), (CollisionMetadataStore(), DuplicateDocumentError)):
        objects = StreamingObjectStore()
        sdk = create_sdk_from_components(metadata_store=metadata, object_store=objects)
        with pytest.raises(error):
            sdk.upload_document_stream(request(b"abc"))
        assert not objects._items


def test_max_file_size_applies_to_bytes_and_stream_before_storage() -> None:
    objects = StreamingObjectStore()
    sdk = create_sdk_from_components(metadata_store=InMemoryMetadataStore(), object_store=objects, max_file_size=2)
    with pytest.raises(ValidationError):
        sdk.upload_document_stream(request(b"abc"))
    with pytest.raises(ValidationError):
        sdk.upload_document(UploadDocumentRequest(content=b"abc", filename="x", content_type="x"))
    assert not objects._items


class FakeClient:
    def __init__(self):
        self.data = None
        self.length = None

    def put_object(self, bucket, key, data, length, **kwargs):
        self.data = data
        self.length = length
        self.payload = data.read()
        return SimpleNamespace()


def test_minio_stream_adapter_passes_original_readable_stream_and_known_size() -> None:
    client = FakeClient()
    store = MinioObjectStore(client=client, bucket_name="bucket")
    stream = BytesIO(b"payload")
    store.put_object_stream(PutObjectStreamRequest(document_id="d", storage_key="k", stream=stream, size=7, chunk_size=2, content_type="x", filename="x"))
    assert client.data is stream
    assert client.length == 7
    assert client.payload == b"payload"
