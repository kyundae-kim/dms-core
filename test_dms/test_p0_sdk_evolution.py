from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from io import BytesIO
import warnings

import pytest
from sqlalchemy import create_engine

from dms.domain.interfaces import PutObjectRequest
from dms.domain.models import DocumentStatus, UploadOperation, UploadOperationClaim, UploadOperationState
from dms.infrastructure.metadata.postgres import PostgresMetadataStore
from dms.infrastructure.metadata.sqlite import SqliteMetadataStore
from dms.sdk import DocumentPage, UploadDocumentRequest, UploadDocumentStreamRequest
from dms.sdk.errors import ValidationError
from dms.sdk.factory import create_sdk_from_components
from test_dms.test_sdk_behavior import InMemoryMetadataStore, InMemoryObjectStore


class CursorMemoryStore(InMemoryMetadataStore):
    def list_metadata_page(self, *, after_created_at=None, after_document_id=None, limit, status=None):
        items = sorted(self._items.values(), key=lambda item: (item.created_at, item.document_id), reverse=True)
        if status is not None:
            items = [item for item in items if item.status is status]
        if after_created_at is not None:
            items = [item for item in items if (item.created_at, item.document_id) < (after_created_at, after_document_id)]
        return items[:limit]


class RecordingOperationStore:
    def __init__(self) -> None:
        self.scopes: list[str] = []

    def claim(self, *, scope, idempotency_key, fingerprint, document_id):
        self.scopes.append(scope)
        now = datetime.now(UTC)
        return UploadOperationClaim(operation=UploadOperation(scope=scope, idempotency_key=idempotency_key,
            fingerprint=fingerprint, document_id=document_id, state=UploadOperationState.PENDING,
            created_at=now, updated_at=now), claimed=True)

    def mark_succeeded(self, *, scope, idempotency_key): pass
    def mark_failed(self, *, scope, idempotency_key): pass


class StreamMemoryObjectStore(InMemoryObjectStore):
    def put_object_stream(self, request):
        content = request.stream.read()
        return self.put_object(PutObjectRequest(
            document_id=request.document_id, storage_key=request.storage_key,
            content=content, content_type=request.content_type, filename=request.filename,
            checksum=request.checksum, metadata=request.metadata,
        ))


def _sdk(metadata_store=None, operation_store=None):
    return create_sdk_from_components(metadata_store=metadata_store or CursorMemoryStore(),
        object_store=StreamMemoryObjectStore(), operation_store=operation_store)


def _request(document_id: str, **kwargs):
    return UploadDocumentRequest(document_id=document_id, content=b"x", filename=f"{document_id}.txt",
        content_type="text/plain", **kwargs)


def test_explicit_delete_methods_preserve_legacy_dispatch():
    sdk = _sdk()
    sdk.upload_document(_request("soft"))
    sdk.upload_document(_request("hard"))
    sdk.upload_document(_request("legacy"))
    assert sdk.soft_delete_document("soft").hard_deleted is False
    assert sdk.hard_delete_document("hard").hard_deleted is True
    assert sdk.delete_document("legacy", hard_delete=True).hard_deleted is True


def test_explicit_idempotency_scope_on_both_request_types_and_fallback_warning():
    operations = RecordingOperationStore()
    sdk = _sdk(operation_store=operations)
    sdk.upload_document(_request("bytes", idempotency_key="k1", idempotency_scope="tenant-a"))
    checksum = "2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881"
    sdk.upload_document_stream(UploadDocumentStreamRequest(document_id="stream", stream=BytesIO(b"x"), size=1,
        filename="stream.txt", content_type="text/plain", checksum=checksum,
        idempotency_key="k2", idempotency_scope="tenant-b"))
    assert operations.scopes == ["tenant-a", "tenant-b"]

    with pytest.warns(DeprecationWarning, match="idempotency_scope"):
        sdk.upload_document(_request("fallback", idempotency_key="k3", created_by="legacy-user"))
    assert operations.scopes[-1] == "legacy-user"
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _sdk().upload_document(_request("ordinary"))
    assert caught == []


def test_cursor_page_is_stable_opaque_and_status_bound():
    store = CursorMemoryStore()
    sdk = _sdk(store)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for index, document_id in enumerate(("a", "b", "c", "d")):
        sdk.upload_document(_request(document_id))
        item = store.get_metadata(document_id)
        store.update_metadata(replace(item, created_at=base + timedelta(seconds=index // 2)))
    first = sdk.list_documents_page(limit=2, status=DocumentStatus.AVAILABLE)
    assert isinstance(first, DocumentPage)
    assert [item.document_id for item in first.items] == ["d", "c"]
    assert first.has_more is True and isinstance(first.next_cursor, str)
    assert "2026" not in first.next_cursor
    second = sdk.list_documents_page(limit=2, cursor=first.next_cursor, status=DocumentStatus.AVAILABLE)
    assert [item.document_id for item in second.items] == ["b", "a"]
    assert second.has_more is False and second.next_cursor is None
    with pytest.raises(ValidationError):
        sdk.list_documents_page(cursor=first.next_cursor, status=DocumentStatus.DELETED)
    with pytest.raises(ValidationError):
        sdk.list_documents_page(cursor="not-a-cursor")


@pytest.mark.parametrize("store_type", [PostgresMetadataStore, SqliteMetadataStore])
def test_sql_adapters_cursor_on_created_at_and_document_id(store_type):
    store = store_type(create_engine("sqlite+pysqlite:///:memory:"))
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for document_id in ("a", "b", "c"):
        metadata = store.build_metadata(document_id=document_id, filename="x", content_type="text/plain",
            file_size=1, storage_key=document_id, checksum=None, created_by=None)
        store.save_metadata(replace(metadata, created_at=base))
    first = store.list_metadata_page(limit=2, status=DocumentStatus.AVAILABLE)
    second = store.list_metadata_page(after_created_at=first[-1].created_at,
        after_document_id=first[-1].document_id, limit=2, status=DocumentStatus.AVAILABLE)
    assert [item.document_id for item in first] == ["c", "b"]
    assert [item.document_id for item in second] == ["a"]
