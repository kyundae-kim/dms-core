from __future__ import annotations

from hashlib import sha256
from io import BytesIO

import pytest

from dms import UploadDocumentRequest, UploadDocumentStreamRequest
from dms.domain.interfaces import (
    MetadataConflictError,
    PutObjectRequest,
    PutObjectStreamRequest,
)
from dms.sdk import UploadDocumentStreamRequest as SdkExport
from dms.sdk.errors import DuplicateDocumentError, ValidationError
from dms.sdk.implementation import DefaultDocumentManagementSDK
from test_dms.sdk_test_support import (
    DEFAULT_PARTITION,
    InMemoryMetadataStore,
    InMemoryObjectStore,
)
from test_dms.test_sdk_behavior import FailingMetadataStore


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
        return self.put_object(
            PutObjectRequest(
                document_id=request.document_id,
                storage_key=request.storage_key,
                content=b"".join(parts),
                content_type=request.content_type,
                filename=request.filename,
                checksum=request.checksum,
                metadata=request.metadata,
            )
        )

    def delete_object(self, document_id: str, storage_key: str) -> None:
        self.deleted.append((document_id, storage_key))
        super().delete_object(document_id, storage_key)


class CollisionMetadataStore(InMemoryMetadataStore):
    def save_metadata(self, metadata):
        raise MetadataConflictError("collision")


def request(content: bytes, **changes) -> UploadDocumentStreamRequest:
    values = {
        "stream": BytesIO(content),
        "size": len(content),
        "filename": "data.bin",
        "content_type": "application/octet-stream",
        "document_id": "stream-1",
    }
    values.update(changes)
    return UploadDocumentStreamRequest(**values)


def test_stream_request_is_public_and_uploads_without_buffering_as_bytes() -> None:
    assert SdkExport is UploadDocumentStreamRequest
    metadata, objects = InMemoryMetadataStore(), StreamingObjectStore()
    sdk = DefaultDocumentManagementSDK(metadata_store=metadata, object_store=objects)
    result = sdk.upload_document_stream(
        request(b"abcdefgh"), partition=DEFAULT_PARTITION
    )
    assert objects.chunks == [8]
    assert result.metadata.file_size == 8
    assert (
        sdk.get_document_content(
            result.document_id, partition=DEFAULT_PARTITION
        ).content
        == b"abcdefgh"
    )
    assert result.metadata.checksum == sha256(b"abcdefgh").hexdigest()


@pytest.mark.parametrize("changes", [{"size": 0}, {"size": -1}])
def test_stream_upload_rejects_non_positive_size_before_storage(changes) -> None:
    objects = StreamingObjectStore()
    sdk = DefaultDocumentManagementSDK(
        metadata_store=InMemoryMetadataStore(), object_store=objects
    )
    with pytest.raises(ValidationError):
        sdk.upload_document_stream(
            request(b"abc", **changes), partition=DEFAULT_PARTITION
        )
    assert not objects._items


def test_stream_upload_enforces_declared_size_and_rolls_back() -> None:
    objects = StreamingObjectStore()
    sdk = DefaultDocumentManagementSDK(
        metadata_store=InMemoryMetadataStore(), object_store=objects
    )
    with pytest.raises(ValidationError):
        sdk.upload_document_stream(request(b"abc", size=4), partition=DEFAULT_PARTITION)
    assert not objects._items
    assert objects.deleted


def test_stream_upload_rolls_back_metadata_failure_and_insert_collision() -> None:
    for metadata, error in (
        (FailingMetadataStore(), Exception),
        (CollisionMetadataStore(), DuplicateDocumentError),
    ):
        objects = StreamingObjectStore()
        sdk = DefaultDocumentManagementSDK(
            metadata_store=metadata, object_store=objects
        )
        with pytest.raises(error):
            sdk.upload_document_stream(request(b"abc"), partition=DEFAULT_PARTITION)
        assert not objects._items


def test_max_file_size_applies_to_bytes_and_stream_before_storage() -> None:
    objects = StreamingObjectStore()
    sdk = DefaultDocumentManagementSDK(
        metadata_store=InMemoryMetadataStore(), object_store=objects, max_file_size=2
    )
    with pytest.raises(ValidationError):
        sdk.upload_document_stream(request(b"abc"), partition=DEFAULT_PARTITION)
    with pytest.raises(ValidationError):
        sdk.upload_document(
            UploadDocumentRequest(content=b"abc", filename="x", content_type="x"),
            partition=DEFAULT_PARTITION,
        )
    assert not objects._items
