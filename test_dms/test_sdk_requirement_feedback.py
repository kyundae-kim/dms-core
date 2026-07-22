from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from io import BytesIO

import pytest
from sqlalchemy import create_engine

from dms import (
    ConsistencyError,
    DeleteDocumentResult,
    DocumentNotFoundError,
    DocumentStatus,
    DuplicateDocumentError,
    IdempotencyInProgressError,
    MetadataStoreError,
    PublicDocumentMetadata,
    StorageError,
    UploadDocumentRequest,
    UploadDocumentStreamRequest,
    UploadDocumentUnknownSizeStreamRequest,
    ValidationError,
    create_sdk_from_components,
)
from dms.infrastructure.metadata.sqlite import SqliteMetadataStore
from test_dms.sdk_test_support import CursorMemoryStore, RecordingOperationStore, StreamMemoryObjectStore


def _sdk(*, metadata_store=None, object_store=None, operation_store=None, close_callbacks=None):
    return create_sdk_from_components(
        metadata_store=metadata_store or CursorMemoryStore(),
        object_store=object_store or StreamMemoryObjectStore(),
        operation_store=operation_store,
        close_callbacks=close_callbacks,
    )


def _upload(sdk, document_id: str):
    return sdk.upload_document(UploadDocumentRequest(
        document_id=document_id,
        content=b"content",
        filename=f"{document_id}.txt",
        content_type="text/plain",
    ))


def test_public_models_have_stable_json_serialization() -> None:
    now = datetime(2026, 7, 22, 12, 30, tzinfo=UTC)
    metadata = PublicDocumentMetadata(
        document_id="doc",
        original_filename="doc.txt",
        content_type="text/plain",
        file_size=7,
        status=DocumentStatus.AVAILABLE,
        created_at=now,
        updated_at=now,
        checksum=None,
        deleted_at=None,
        created_by=None,
        extra_metadata={"nested": [1, True, None, {"name": "value"}]},
    )
    deleted = DeleteDocumentResult(
        document_id="doc",
        deleted=True,
        hard_deleted=False,
        status=DocumentStatus.DELETED,
    )

    metadata_value = metadata.to_dict()
    delete_value = deleted.to_dict()

    assert metadata_value == {
        "document_id": "doc",
        "original_filename": "doc.txt",
        "content_type": "text/plain",
        "file_size": 7,
        "status": "available",
        "created_at": "2026-07-22T12:30:00+00:00",
        "updated_at": "2026-07-22T12:30:00+00:00",
        "checksum": None,
        "deleted_at": None,
        "created_by": None,
        "extra_metadata": {"nested": [1, True, None, {"name": "value"}]},
    }
    assert delete_value == {
        "document_id": "doc",
        "deleted": True,
        "hard_deleted": False,
        "status": "deleted",
    }
    json.dumps(metadata_value)
    json.dumps(delete_value)


def test_public_metadata_serialization_rejects_non_json_runtime_values() -> None:
    now = datetime.now(UTC)
    metadata = PublicDocumentMetadata(
        document_id="doc",
        original_filename="doc.txt",
        content_type="text/plain",
        file_size=1,
        status=DocumentStatus.AVAILABLE,
        created_at=now,
        updated_at=now,
        extra_metadata={"payload": b"not-json"},
    )

    with pytest.raises(TypeError, match="JSON-compatible"):
        metadata.to_dict()


def test_public_metadata_get_and_lists_hide_deleted_documents() -> None:
    sdk = _sdk()
    _upload(sdk, "available")
    _upload(sdk, "deleted")
    sdk.soft_delete_document("deleted")

    with pytest.raises(DocumentNotFoundError):
        sdk.get_document_metadata("deleted")
    assert sdk.get_internal_document_metadata("deleted").status is DocumentStatus.DELETED
    assert [item.document_id for item in sdk.list_documents()] == ["available"]
    assert [item.document_id for item in sdk.list_documents_page().items] == ["available"]
    with pytest.raises(ValidationError):
        sdk.list_documents(status=DocumentStatus.DELETED)
    with pytest.raises(ValidationError):
        sdk.list_documents_page(status=DocumentStatus.DELETING)


def test_sql_public_filter_is_applied_before_offset_and_limit() -> None:
    store = SqliteMetadataStore(create_engine("sqlite+pysqlite:///:memory:"))
    sdk = _sdk(metadata_store=store)
    for document_id in ("a", "b", "c"):
        _upload(sdk, document_id)
    deleted = store.get_metadata("b")
    store.update_metadata(replace(deleted, status=DocumentStatus.DELETED))

    assert [item.document_id for item in sdk.list_documents(offset=1, limit=1)] == ["a"]


def test_all_public_sdk_errors_expose_structured_contract() -> None:
    expectations = [
        (ValidationError, "validation_invalid", "validation", False),
        (DuplicateDocumentError, "document_duplicate", "conflict", False),
        (DocumentNotFoundError, "document_not_found", "not_found", False),
        (StorageError, "object_storage_failed", "storage", True),
        (MetadataStoreError, "metadata_store_failed", "storage", True),
        (ConsistencyError, "document_inconsistent", "consistency", False),
        (IdempotencyInProgressError, "idempotency_in_progress", "conflict", True),
    ]
    for error_type, code, category, retryable in expectations:
        error = error_type("failure")
        assert error.code == code
        assert error.category == category
        assert error.retryable is retryable


def test_common_upload_validation_happens_before_stream_read_or_idempotency_claim() -> None:
    class ExplodingStream:
        reads = 0

        def read(self, size=-1):
            self.reads += 1
            raise AssertionError("invalid common input must be rejected before reading")

    operations = RecordingOperationStore()
    sdk = _sdk(operation_store=operations)
    requests = [
        UploadDocumentRequest(
            content=b"content", filename=" ", content_type="text/plain",
            idempotency_key="key", idempotency_scope="scope",
        ),
        UploadDocumentStreamRequest(
            stream=ExplodingStream(), size=7, filename=" ", content_type="text/plain",
            idempotency_key="key", idempotency_scope="scope",
        ),
        UploadDocumentUnknownSizeStreamRequest(
            stream=ExplodingStream(), max_size=10, filename=" ", content_type="text/plain",
            idempotency_key="key", idempotency_scope="scope",
        ),
    ]
    uploaders = [
        sdk.upload_document,
        sdk.upload_document_stream,
        sdk.upload_document_unknown_size_stream,
    ]

    for uploader, request in zip(uploaders, requests, strict=True):
        with pytest.raises(ValidationError, match="filename must not be empty"):
            uploader(request)
    assert operations.scopes == []
    assert requests[1].stream.reads == 0
    assert requests[2].stream.reads == 0


def test_sdk_and_content_stream_are_context_managed_on_exception() -> None:
    closed: list[str] = []
    sdk = _sdk(close_callbacks=[lambda: closed.append("sdk")])
    _upload(sdk, "stream")

    with pytest.raises(RuntimeError, match="boom"):
        with sdk as entered:
            assert entered is sdk
            with sdk.get_document_content_stream("stream") as content:
                assert content.stream.closed is False
                raise RuntimeError("boom")

    assert content.stream.closed is True
    assert closed == ["sdk"]
    sdk.close()
    content.close()
    assert closed == ["sdk"]
