from __future__ import annotations

from io import BytesIO

import pytest

from dms.sdk import (
    PublicDocumentMetadata,
    UploadDocumentRequest,
    UploadDocumentStreamRequest,
    public_metadata,
)
from dms.sdk.errors import ValidationError
from dms.sdk.implementation import DefaultDocumentManagementSDK
from test_dms.sdk_test_support import (
    DEFAULT_PARTITION,
    CursorMemoryStore,
    RecordingOperationStore,
    StreamMemoryObjectStore,
)


def test_public_metadata_projection_accepts_metadata_and_upload_result_without_storage_key():
    store, objects = (CursorMemoryStore(), StreamMemoryObjectStore())
    sdk = DefaultDocumentManagementSDK(metadata_store=store, object_store=objects)
    result = sdk.upload_document(
        UploadDocumentRequest(
            content=b"x", filename="x.txt", content_type="text/plain"
        ),
        partition=DEFAULT_PARTITION,
    )
    projected = public_metadata(result)
    assert isinstance(projected, PublicDocumentMetadata)
    assert projected == public_metadata(result.metadata)
    assert not hasattr(projected, "storage_key")
    assert projected.extra_metadata is not result.metadata.extra_metadata


def test_metadata_requires_a_dictionary_or_none():
    sdk = DefaultDocumentManagementSDK(
        metadata_store=CursorMemoryStore(),
        object_store=StreamMemoryObjectStore(),
    )

    with pytest.raises(ValidationError, match="metadata"):
        sdk.upload_document(
            UploadDocumentRequest(
                content=b"x",
                filename="x",
                content_type="x",
                metadata="application-owned metadata",  # type: ignore[arg-type]
            ),
            partition=DEFAULT_PARTITION,
        )


def test_metadata_requires_json_serializable_values():
    sdk = DefaultDocumentManagementSDK(
        metadata_store=CursorMemoryStore(),
        object_store=StreamMemoryObjectStore(),
    )

    with pytest.raises(ValidationError, match="JSON"):
        sdk.upload_document(
            UploadDocumentRequest(
                content=b"x",
                filename="x",
                content_type="x",
                metadata={"unsupported": object()},
            ),
            partition=DEFAULT_PARTITION,
        )


def test_metadata_preserves_application_owned_dictionary_values():
    sdk = DefaultDocumentManagementSDK(
        metadata_store=CursorMemoryStore(),
        object_store=StreamMemoryObjectStore(),
    )

    value = {"password": "caller-owned", "custom_field": {"priority": 1}}
    result = sdk.upload_document(
        UploadDocumentRequest(
            content=b"x",
            filename="x",
            content_type="x",
            metadata=value,
        ),
        partition=DEFAULT_PARTITION,
    )

    assert result.metadata.extra_metadata["password"] == "caller-owned"
    assert result.metadata.extra_metadata["custom_field"] == {"priority": 1}


def test_dictionary_metadata_is_preserved_for_stream_and_file_uploads(tmp_path):
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
            metadata={"owner": "stream-owned"},
        ),
        partition=DEFAULT_PARTITION,
    )
    path = tmp_path / "file.txt"
    path.write_bytes(b"file")
    file_result = sdk.upload_file(
        path,
        content_type="text/plain",
        metadata={"owner": "file-owned"},
        partition=DEFAULT_PARTITION,
    )

    assert stream_result.metadata.extra_metadata == {"owner": "stream-owned"}
    assert file_result.metadata.extra_metadata == {"owner": "file-owned"}


def test_dictionary_metadata_is_preserved_with_idempotency():
    sdk = DefaultDocumentManagementSDK(
        metadata_store=CursorMemoryStore(),
        object_store=StreamMemoryObjectStore(),
        operation_store=RecordingOperationStore(),
    )
    value = {"title": "application-owned"}

    result = sdk.upload_document(
        UploadDocumentRequest(
            content=b"x",
            filename="x",
            content_type="x",
            metadata=value,
            idempotency_key="key",
            idempotency_scope="scope",
        ),
        partition=DEFAULT_PARTITION,
    )

    assert result.metadata.extra_metadata == value
