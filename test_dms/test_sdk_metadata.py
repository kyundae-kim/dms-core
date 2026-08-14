from __future__ import annotations

from io import BytesIO

from dms.sdk import (
    PublicDocumentMetadata,
    UploadDocumentRequest,
    UploadDocumentStreamRequest,
    public_metadata,
)
from dms.sdk.implementation import DefaultDocumentManagementSDK
from test_dms.sdk_test_support import (
    CursorMemoryStore,
    RecordingOperationStore,
    StreamMemoryObjectStore,
)


def test_public_metadata_projection_accepts_metadata_and_upload_result_without_storage_key():
    store, objects = (CursorMemoryStore(), StreamMemoryObjectStore())
    sdk = DefaultDocumentManagementSDK(metadata_store=store, object_store=objects)
    result = sdk.upload_document(UploadDocumentRequest(content=b'x', filename='x.txt', content_type='text/plain'))
    projected = public_metadata(result)
    assert isinstance(projected, PublicDocumentMetadata)
    assert projected == public_metadata(result.metadata)
    assert not hasattr(projected, 'storage_key')
    assert projected.extra_metadata is not result.metadata.extra_metadata

def test_metadata_is_application_owned_and_does_not_require_a_mapping():
    sdk = DefaultDocumentManagementSDK(
        metadata_store=CursorMemoryStore(),
        object_store=StreamMemoryObjectStore(),
    )

    value = "application-owned metadata"
    result = sdk.upload_document(
        UploadDocumentRequest(
            content=b"x",
            filename="x",
            content_type="x",
            metadata=value,  # type: ignore[arg-type]
        )
    )

    assert result.metadata.extra_metadata == value


def test_metadata_does_not_apply_dms_security_or_schema_rules():
    sdk = DefaultDocumentManagementSDK(
        metadata_store=CursorMemoryStore(),
        object_store=StreamMemoryObjectStore(),
    )

    value = {"password": "caller-owned", "custom_field": object()}
    result = sdk.upload_document(
        UploadDocumentRequest(
            content=b"x",
            filename="x",
            content_type="x",
            metadata=value,
        )
    )

    assert result.metadata.extra_metadata["password"] == "caller-owned"
    assert isinstance(result.metadata.extra_metadata["custom_field"], object)


def test_opaque_metadata_is_preserved_for_stream_and_file_uploads(tmp_path):
    sdk = DefaultDocumentManagementSDK(
        metadata_store=CursorMemoryStore(),
        object_store=StreamMemoryObjectStore(),
    )

    stream_result = sdk.upload_document_stream(
        UploadDocumentStreamRequest(
            stream=BytesIO(b"stream"),
            size=6,
            filename="stream.txt",
            content_type="text/plain",
            metadata=["stream-owned"],
        )
    )
    path = tmp_path / "file.txt"
    path.write_bytes(b"file")
    file_result = sdk.upload_file(
        path,
        content_type="text/plain",
        metadata="file-owned",
    )

    assert stream_result.metadata.extra_metadata == ["stream-owned"]
    assert file_result.metadata.extra_metadata == "file-owned"


def test_metadata_is_not_serialized_for_idempotency():
    class UnserializableMetadata:
        def __str__(self):
            raise AssertionError("DMS must not serialize opaque metadata")

    sdk = DefaultDocumentManagementSDK(
        metadata_store=CursorMemoryStore(),
        object_store=StreamMemoryObjectStore(),
        operation_store=RecordingOperationStore(),
    )
    value = UnserializableMetadata()

    result = sdk.upload_document(
        UploadDocumentRequest(
            content=b"x",
            filename="x",
            content_type="x",
            metadata=value,
            idempotency_key="key",
            idempotency_scope="scope",
        )
    )

    assert isinstance(result.metadata.extra_metadata, UnserializableMetadata)
