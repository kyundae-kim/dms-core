from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, BinaryIO, Callable, Iterator, Self

from dms.domain.models import DocumentMetadata, DocumentStatus


@dataclass(slots=True, kw_only=True)
class UploadDocumentRequest:
    content: bytes
    filename: str
    content_type: str
    document_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_by: str | None = None
    checksum: str | None = None
    idempotency_key: str | None = None


@dataclass(slots=True, kw_only=True)
class UploadDocumentStreamRequest:
    stream: BinaryIO
    size: int
    filename: str
    content_type: str
    document_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_by: str | None = None
    checksum: str | None = None
    chunk_size: int = 65536
    idempotency_key: str | None = None


@dataclass(slots=True, kw_only=True)
class UploadDocumentResult:
    document_id: str
    storage_key: str
    metadata: DocumentMetadata
    created: bool = True


@dataclass(slots=True, kw_only=True)
class DocumentContent:
    document_id: str
    content: bytes
    content_type: str
    filename: str
    size: int
    checksum: str | None = None


@dataclass(slots=True, kw_only=True)
class DocumentContentStream:
    document_id: str
    stream: BinaryIO
    content_type: str
    filename: str
    size: int
    checksum: str | None = None
    chunk_size: int = 65536
    _close_callback: Callable[[], None] | None = None
    _closed: bool = False

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()

    def iter_chunks(self, chunk_size: int | None = None) -> Iterator[bytes]:
        size = chunk_size or self.chunk_size
        while True:
            chunk = self.stream.read(size)
            if not chunk:
                break
            yield chunk

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._close_callback is not None:
            callback = self._close_callback
            self._close_callback = None
            callback()
        else:
            self.stream.close()


@dataclass(slots=True, kw_only=True)
class DeleteDocumentResult:
    document_id: str
    deleted: bool
    hard_deleted: bool
    status: DocumentStatus


class RecoveryIssue(StrEnum):
    NONE = "none"
    METADATA_MISSING = "metadata_missing"
    OBJECT_MISSING = "object_missing"
    DELETION_INCOMPLETE = "deletion_incomplete"
    FAILED_STATUS = "failed_status"


class RecoveryAction(StrEnum):
    COMPLETE_DELETION_SOFT = "complete_deletion_soft"
    COMPLETE_DELETION_HARD = "complete_deletion_hard"
    MARK_FAILED = "mark_failed"
    PURGE_ORPHAN_OBJECT = "purge_orphan_object"


@dataclass(slots=True, kw_only=True)
class DocumentInspection:
    document_id: str
    metadata_exists: bool
    object_exists: bool | None
    status: DocumentStatus | None
    consistent: bool
    issue: RecoveryIssue
    storage_key: str | None = None


@dataclass(slots=True, kw_only=True)
class ReconciliationResult:
    document_id: str
    action: RecoveryAction
    applied: bool
    inspection: DocumentInspection
    error_type: str | None = None
    error_message: str | None = None


@dataclass(slots=True, kw_only=True)
class BatchReconciliationResult:
    status: DocumentStatus
    action: RecoveryAction
    dry_run: bool
    offset: int
    limit: int
    items: list[ReconciliationResult]


@dataclass(slots=True, kw_only=True)
class ServiceHealth:
    service: str
    ok: bool
    latency_ms: float | None = None
    error: str | None = None


@dataclass(slots=True, kw_only=True)
class HealthStatus:
    ok: bool
    services: list[ServiceHealth]
    checked_at: datetime
