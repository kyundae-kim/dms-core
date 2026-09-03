from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from io import BytesIO

from dms.domain.interfaces import PutObjectRequest, StoredObject, StoredObjectStream
from dms.domain.models import (
    DocumentMetadata,
    DocumentPartition,
    DocumentStatus,
    UploadOperation,
    UploadOperationClaim,
    UploadOperationState,
)
from dms.sdk.contracts import partition_storage_prefix
from dms.sdk.errors import IdempotencyConflictError

DEFAULT_PARTITION = DocumentPartition.personal("test-person")


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

    def update_metadata(self, metadata: DocumentMetadata) -> DocumentMetadata:
        current = self._items.get(metadata.document_id)
        if current is None or current.partition != metadata.partition:
            raise LookupError(metadata.document_id)
        self._items[metadata.document_id] = metadata
        return metadata

    def get_metadata(
        self,
        document_id: str,
        *,
        partition: DocumentPartition,
    ) -> DocumentMetadata:
        try:
            item = self._items[document_id]
        except KeyError as exc:
            raise LookupError(document_id) from exc
        if item.partition != partition:
            raise LookupError(document_id)
        return item

    def list_metadata(
        self,
        *,
        offset: int,
        limit: int,
        status: DocumentStatus | None = None,
        excluded_statuses: tuple[DocumentStatus, ...] = (),
        partition: DocumentPartition,
    ) -> list[DocumentMetadata]:
        items = sorted(
            self._items.values(),
            key=lambda item: (item.created_at, item.document_id),
            reverse=True,
        )
        items = [item for item in items if item.partition == partition]
        if status is not None:
            items = [item for item in items if item.status == status]
        if excluded_statuses:
            items = [item for item in items if item.status not in excluded_statuses]
        return items[offset : offset + limit]

    def mark_deleted(
        self,
        document_id: str,
        *,
        partition: DocumentPartition,
    ) -> DocumentMetadata:
        item = self.get_metadata(document_id, partition=partition)
        now = datetime.now(UTC)
        deleted = replace(
            item, status=DocumentStatus.DELETED, deleted_at=now, updated_at=now
        )
        self._items[document_id] = deleted
        return deleted

    def hard_delete(self, document_id: str, *, partition: DocumentPartition) -> None:
        self.get_metadata(document_id, partition=partition)
        del self._items[document_id]

    def clear_all(self) -> int:
        count = len(self._items)
        self._items.clear()
        return count

    def clear_partition(self, *, partition: DocumentPartition) -> int:
        owned = [
            document_id
            for document_id, item in self._items.items()
            if item.partition == partition
        ]
        for document_id in owned:
            del self._items[document_id]
        return len(owned)

    def exists(self, document_id: str) -> bool:
        return document_id in self._items


class InMemoryObjectStore:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str], StoredObject] = {}

    def put_object(self, request: PutObjectRequest) -> str:
        self._items[(request.document_id, request.storage_key)] = StoredObject(
            document_id=request.document_id,
            storage_key=request.storage_key,
            content=request.content,
            content_type=request.content_type,
            filename=request.filename,
            size=len(request.content),
            checksum=request.checksum,
        )
        return request.storage_key

    def get_object(self, document_id: str, storage_key: str) -> StoredObject:
        try:
            return self._items[(document_id, storage_key)]
        except KeyError as exc:
            raise LookupError(document_id) from exc

    def get_object_stream(
        self, document_id: str, storage_key: str
    ) -> StoredObjectStream:
        stored = self.get_object(document_id, storage_key)
        return StoredObjectStream(
            document_id=stored.document_id,
            storage_key=stored.storage_key,
            stream=BytesIO(stored.content),
            content_type=stored.content_type,
            filename=stored.filename,
            size=stored.size,
            checksum=stored.checksum,
        )

    def delete_object(self, document_id: str, storage_key: str) -> None:
        try:
            del self._items[(document_id, storage_key)]
        except KeyError as exc:
            raise LookupError(document_id) from exc

    def clear_all(self) -> int:
        count = len(self._items)
        self._items.clear()
        return count

    def clear_partition(self, *, partition: DocumentPartition) -> int:
        prefix = partition_storage_prefix(partition)
        owned = [key for key in self._items if key[1].startswith(prefix)]
        for key in owned:
            del self._items[key]
        return len(owned)

    def object_exists(self, document_id: str, storage_key: str) -> bool:
        return (document_id, storage_key) in self._items


def metadata(
    document_id: str = "d",
    status: DocumentStatus = DocumentStatus.AVAILABLE,
    partition: DocumentPartition = DEFAULT_PARTITION,
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
        partition=partition,
        checksum="sum",
        created_by="u",
        extra_metadata={"schema_version": "1", "title": "x"},
    )


class CursorMemoryStore(InMemoryMetadataStore):
    def list_metadata_page(
        self,
        *,
        after_created_at=None,
        after_document_id=None,
        limit,
        status=None,
        excluded_statuses=(),
        partition,
    ):
        items = sorted(
            self._items.values(),
            key=lambda item: (item.created_at, item.document_id),
            reverse=True,
        )
        items = [item for item in items if item.partition == partition]
        if status is not None:
            items = [item for item in items if item.status is status]
        if excluded_statuses:
            items = [item for item in items if item.status not in excluded_statuses]

        if after_created_at is not None:
            items = [
                item
                for item in items
                if (item.created_at, item.document_id)
                < (after_created_at, after_document_id)
            ]
        return items[:limit]


class RecordingOperationStore:
    def __init__(self) -> None:
        self.scopes: list[str] = []
        self._records: dict[tuple[str, str], UploadOperation] = {}

    def claim(self, *, scope, idempotency_key, fingerprint, document_id):
        self.scopes.append(scope)
        key = (scope, idempotency_key)
        existing = self._records.get(key)
        if existing is not None:
            if existing.fingerprint != fingerprint:
                raise IdempotencyConflictError("fingerprint mismatch")
            if existing.state is UploadOperationState.FAILED:
                existing = replace(
                    existing,
                    state=UploadOperationState.PENDING,
                    updated_at=datetime.now(UTC),
                )
                self._records[key] = existing
                return UploadOperationClaim(operation=existing, claimed=True)
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
        self._records[key] = operation
        return UploadOperationClaim(operation=operation, claimed=True)

    def get(self, *, scope, idempotency_key):
        try:
            return self._records[(scope, idempotency_key)]
        except KeyError as exc:
            raise LookupError((scope, idempotency_key)) from exc

    def mark_succeeded(self, *, scope, idempotency_key):
        self._mark(scope, idempotency_key, UploadOperationState.SUCCEEDED)

    def mark_failed(self, *, scope, idempotency_key):
        self._mark(scope, idempotency_key, UploadOperationState.FAILED)

    def clear_all(self, *, scope_prefix=None) -> int:
        if scope_prefix is None:
            count = len(self._records)
            self._records.clear()
            self.scopes.clear()
            return count
        removed = [key for key in self._records if key[0].startswith(scope_prefix)]
        for key in removed:
            del self._records[key]
        kept = [scope for scope in self.scopes if not scope.startswith(scope_prefix)]
        self.scopes[:] = kept
        return len(removed)

    def _mark(self, scope, idempotency_key, state):
        key = (scope, idempotency_key)
        operation = self._records[key]
        self._records[key] = replace(
            operation,
            state=state,
            updated_at=datetime.now(UTC),
        )


class StreamMemoryObjectStore(InMemoryObjectStore):
    def put_object_stream(self, request):
        content = request.stream.read()
        return self.put_object(
            PutObjectRequest(
                document_id=request.document_id,
                storage_key=request.storage_key,
                content=content,
                content_type=request.content_type,
                filename=request.filename,
                checksum=request.checksum,
                metadata=request.metadata,
            )
        )
