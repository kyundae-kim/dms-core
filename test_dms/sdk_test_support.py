from __future__ import annotations

from datetime import UTC, datetime

from dms.domain.interfaces import PutObjectRequest
from dms.domain.models import (
    DocumentMetadata,
    DocumentStatus,
    UploadOperation,
    UploadOperationClaim,
    UploadOperationState,
)
from test_dms.test_sdk_behavior import InMemoryMetadataStore, InMemoryObjectStore


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
        return UploadOperationClaim(operation=UploadOperation(scope=scope, idempotency_key=idempotency_key, fingerprint=fingerprint, document_id=document_id, state=UploadOperationState.PENDING, created_at=now, updated_at=now), claimed=True)

    def mark_succeeded(self, *, scope, idempotency_key):
        pass

    def mark_failed(self, *, scope, idempotency_key):
        pass


class StreamMemoryObjectStore(InMemoryObjectStore):
    def put_object_stream(self, request):
        content = request.stream.read()
        return self.put_object(PutObjectRequest(document_id=request.document_id, storage_key=request.storage_key, content=content, content_type=request.content_type, filename=request.filename, checksum=request.checksum, metadata=request.metadata))
