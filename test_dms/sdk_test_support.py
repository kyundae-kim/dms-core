from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from io import BytesIO

from dms.domain.interfaces import PutObjectRequest, StoredObject, StoredObjectStream
from dms.domain.models import (
    DocumentMetadata,
    DocumentStatus,
    UploadOperation,
    UploadOperationClaim,
    UploadOperationState,
)
from dms.sdk.user_scope import user_storage_prefix


class InMemoryMetadataStore:
    def __init__(self) -> None:
        self._items: dict[str, DocumentMetadata] = {}
        self._next_document_id = 0

    def allocate_document_id(self) -> str:
        while True:
            self._next_document_id += 1
            document_id = str(self._next_document_id)
            if document_id not in self._items:
                return document_id

    def save_metadata(self, metadata: DocumentMetadata) -> DocumentMetadata:
        self._items[metadata.document_id] = metadata
        return metadata

    update_metadata = save_metadata

    def get_metadata(self, document_id: str) -> DocumentMetadata:
        try:
            return self._items[document_id]
        except KeyError as exc:
            raise LookupError(document_id) from exc

    def list_metadata(self, *, offset: int, limit: int, status: DocumentStatus | None = None,
                      excluded_statuses: tuple[DocumentStatus, ...] = (),
                      user_id: str | None = None,
                      unscoped_only: bool = False) -> list[DocumentMetadata]:
        items = sorted(self._items.values(), key=lambda item: (item.created_at, item.document_id), reverse=True)
        if status is not None:
            items = [item for item in items if item.status == status]
        if excluded_statuses:
            items = [item for item in items if item.status not in excluded_statuses]
        if unscoped_only:
            items = [item for item in items if item.user_id is None]
        elif user_id is not None:
            items = [item for item in items if item.user_id == user_id]
        return items[offset : offset + limit]

    def mark_deleted(self, document_id: str) -> DocumentMetadata:
        item = self.get_metadata(document_id)
        now = datetime.now(UTC)
        deleted = replace(item, status=DocumentStatus.DELETED, deleted_at=now, updated_at=now)
        self._items[document_id] = deleted
        return deleted

    def hard_delete(self, document_id: str) -> None:
        try:
            del self._items[document_id]
        except KeyError as exc:
            raise LookupError(document_id) from exc

    def clear_all(self, *, user_id: str | None = None) -> int:
        if user_id is None:
            count = len(self._items)
            self._items.clear()
            return count
        owned = [
            document_id
            for document_id, item in self._items.items()
            if item.user_id == user_id
        ]
        for document_id in owned:
            del self._items[document_id]
        return len(owned)

    def exists(self, document_id: str, *, user_id: str | None = None) -> bool:
        item = self._items.get(document_id)
        return item is not None and (user_id is None or item.user_id == user_id)


class InMemoryObjectStore:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str], StoredObject] = {}

    def put_object(self, request: PutObjectRequest) -> str:
        self._items[(request.document_id, request.storage_key)] = StoredObject(
            document_id=request.document_id, storage_key=request.storage_key,
            content=request.content, content_type=request.content_type,
            filename=request.filename, size=len(request.content), checksum=request.checksum)
        return request.storage_key

    def get_object(self, document_id: str, storage_key: str) -> StoredObject:
        try:
            return self._items[(document_id, storage_key)]
        except KeyError as exc:
            raise LookupError(document_id) from exc

    def get_object_stream(self, document_id: str, storage_key: str) -> StoredObjectStream:
        stored = self.get_object(document_id, storage_key)
        return StoredObjectStream(document_id=stored.document_id, storage_key=stored.storage_key,
            stream=BytesIO(stored.content), content_type=stored.content_type,
            filename=stored.filename, size=stored.size, checksum=stored.checksum)

    def delete_object(self, document_id: str, storage_key: str) -> None:
        try:
            del self._items[(document_id, storage_key)]
        except KeyError as exc:
            raise LookupError(document_id) from exc

    def clear_all(self, *, user_id: str | None = None) -> int:
        if user_id is None:
            count = len(self._items)
            self._items.clear()
            return count
        prefix = user_storage_prefix(user_id)
        owned = [key for key in self._items if key[1].startswith(prefix)]
        for key in owned:
            del self._items[key]
        return len(owned)

    def object_exists(self, document_id: str, storage_key: str) -> bool:
        return (document_id, storage_key) in self._items


def metadata(
    document_id: str = "d",
    status: DocumentStatus = DocumentStatus.AVAILABLE,
) -> DocumentMetadata:
    now = datetime.now(UTC)
    return DocumentMetadata(
        document_id=document_id,
        original_filename="x.txt",
        content_type="text/plain",
        file_size=1,
        storage_key="secret/key",
        status=status,
        created_at=now,
        updated_at=now,
        checksum="sum",
        created_by="u",
        extra_metadata={"schema_version": "1", "title": "x"},
    )


class CursorMemoryStore(InMemoryMetadataStore):
    def list_metadata_page(self, *, after_created_at=None, after_document_id=None, limit, status=None,
                           excluded_statuses=(), user_id=None, unscoped_only=False):
        items = sorted(self._items.values(), key=lambda item: (item.created_at, item.document_id), reverse=True)
        if status is not None:
            items = [item for item in items if item.status is status]
        if excluded_statuses:
            items = [item for item in items if item.status not in excluded_statuses]
        if unscoped_only:
            items = [item for item in items if item.user_id is None]
        elif user_id is not None:
            items = [item for item in items if item.user_id == user_id]
        if after_created_at is not None:
            items = [item for item in items if (item.created_at, item.document_id) < (after_created_at, after_document_id)]
        return items[:limit]


class RecordingOperationStore:
    def __init__(self) -> None:
        self.scopes: list[str] = []

    def claim(self, *, scope, idempotency_key, fingerprint, document_id):
        self.scopes.append(scope)
        now = datetime.now(UTC)
        return UploadOperationClaim(operation=UploadOperation(scope=scope, idempotency_key=idempotency_key, fingerprint=fingerprint, document_id=document_id, state=UploadOperationState.PENDING, created_at=now, updated_at=now), claimed=True)

    def mark_succeeded(self, *, scope, idempotency_key):
        pass

    def mark_failed(self, *, scope, idempotency_key):
        pass

    def clear_all(self, *, scope_prefix=None) -> int:
        if scope_prefix is None:
            count = len(self.scopes)
            self.scopes.clear()
            return count
        kept = [scope for scope in self.scopes if not scope.startswith(scope_prefix)]
        count = len(self.scopes) - len(kept)
        self.scopes[:] = kept
        return count


class StreamMemoryObjectStore(InMemoryObjectStore):
    def put_object_stream(self, request):
        content = request.stream.read()
        return self.put_object(PutObjectRequest(document_id=request.document_id, storage_key=request.storage_key, content=content, content_type=request.content_type, filename=request.filename, checksum=request.checksum, metadata=request.metadata))
