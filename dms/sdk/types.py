from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, BinaryIO, Callable, Iterator, Self

from dms.domain.models import DocumentMetadata, DocumentStatus, UploadOperationState


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
    idempotency_scope: str | None = None


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
    idempotency_scope: str | None = None


@dataclass(slots=True, kw_only=True)
class UploadDocumentUnknownSizeStreamRequest:
    """An unknown-length stream copied into a bounded temporary spool before upload."""

    stream: BinaryIO
    max_size: int
    filename: str
    content_type: str
    document_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_by: str | None = None
    chunk_size: int = 65536
    idempotency_key: str | None = None
    idempotency_scope: str | None = None


@dataclass(slots=True, kw_only=True)
class UploadDocumentResult:
    document_id: str
    metadata: PublicDocumentMetadata
    created: bool = True


@dataclass(frozen=True, slots=True, kw_only=True)
class PublicDocumentMetadata:
    """Public-safe projection which deliberately omits ``storage_key``."""
    document_id: str
    original_filename: str
    content_type: str
    file_size: int
    status: DocumentStatus
    created_at: datetime
    updated_at: datetime
    checksum: str | None = None
    deleted_at: datetime | None = None
    created_by: str | None = None
    extra_metadata: dict[str, Any] = field(default_factory=dict)


def public_metadata(
    value: DocumentMetadata | PublicDocumentMetadata | UploadDocumentResult,
) -> PublicDocumentMetadata:
    """Project ``DocumentMetadata`` or ``UploadDocumentResult`` for public use."""
    source = value.metadata if isinstance(value, UploadDocumentResult) else value
    return PublicDocumentMetadata(document_id=source.document_id,
        original_filename=source.original_filename, content_type=source.content_type,
        file_size=source.file_size, status=source.status, created_at=source.created_at,
        updated_at=source.updated_at, checksum=source.checksum, deleted_at=source.deleted_at,
        created_by=source.created_by, extra_metadata=deepcopy(source.extra_metadata))


@dataclass(slots=True, kw_only=True)
class UploadOperationResult:
    scope: str
    idempotency_key: str
    document_id: str
    state: UploadOperationState
    created_at: datetime
    updated_at: datetime


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


@dataclass(slots=True, kw_only=True)
class DocumentPage:
    """A cursor page in stable created_at/document_id descending order."""

    items: list[PublicDocumentMetadata]
    next_cursor: str | None
    has_more: bool


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
    inspection: DocumentInspection | None
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

    @property
    def scanned(self) -> int:
        return len(self.items)

    @property
    def failed(self) -> int:
        return sum(item.error_type is not None for item in self.items)

    @property
    def eligible(self) -> int:
        return self.scanned - self.failed

    @property
    def applied(self) -> int:
        return sum(item.applied and item.error_type is None for item in self.items)

    @property
    def skipped(self) -> int:
        return self.eligible - self.applied

    def to_plan(self) -> ReconciliationPlan:
        """Export non-error candidates; execution always re-inspects each item."""
        if not self.dry_run:
            raise ValueError("reconciliation plans can only be exported from a dry-run result")
        return ReconciliationPlan(status=self.status, action=self.action, items=tuple(ReconciliationPlanItem(
            document_id=item.document_id, action=item.action,
            storage_key=item.inspection.storage_key if
                item.action is RecoveryAction.PURGE_ORPHAN_OBJECT and item.inspection is not None else None)
            for item in self.items if item.error_type is None))


@dataclass(frozen=True, slots=True, kw_only=True)
class ReconciliationPlanItem:
    document_id: str
    action: RecoveryAction
    storage_key: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ReconciliationPlan:
    status: DocumentStatus
    action: RecoveryAction
    items: tuple[ReconciliationPlanItem, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(self.items))
        if any(item.action is not self.action for item in self.items):
            raise ValueError("reconciliation item action differs from plan action")


@dataclass(frozen=True, slots=True, kw_only=True)
class RecoveryAuditEvent:
    """Best-effort notification for one attempted reconciliation."""
    document_id: str
    action: RecoveryAction
    dry_run: bool
    succeeded: bool
    applied: bool
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    actor: str | None = None
    error_type: str | None = None
    error_message: str | None = None


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
