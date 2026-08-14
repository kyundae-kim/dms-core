from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Iterator
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, BinaryIO, Self

from dms.domain.models import DocumentMetadata, DocumentStatus, UploadOperationState


@dataclass(slots=True, kw_only=True)
class UploadDocumentRequest:
    content: bytes
    filename: str
    content_type: str
    document_id: str | None = None
    metadata: Any = None
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
    metadata: Any = None
    created_by: str | None = None


class _JsonSchemaMixin:
    __slots__ = ()

    @classmethod
    def model_json_schema(cls) -> dict[str, Any]:
        return cls.json_schema()


@dataclass(slots=True, kw_only=True)
class UploadDocumentResult(_JsonSchemaMixin):
    document_id: str
    metadata: PublicDocumentMetadata
    created: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "metadata": self.metadata.to_public_dict(),
            "created": self.created,
        }

    @classmethod
    def json_schema(cls) -> dict[str, Any]:
        return deepcopy(_UPLOAD_DOCUMENT_RESULT_SCHEMA)


@dataclass(frozen=True, slots=True, kw_only=True)
class PublicDocumentMetadata(_JsonSchemaMixin):
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
    extra_metadata: Any = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return the v0.6-compatible field names used by existing SDK consumers."""
        return {
            "document_id": self.document_id,
            "original_filename": self.original_filename,
            "content_type": self.content_type,
            "file_size": self.file_size,
            "status": self.status.value,
            "created_at": _serialize_datetime(self.created_at),
            "updated_at": _serialize_datetime(self.updated_at),
            "checksum": self.checksum,
            "deleted_at": _serialize_datetime(self.deleted_at) if self.deleted_at is not None else None,
            "created_by": self.created_by,
            "extra_metadata": self.extra_metadata,
        }

    def to_public_dict(self) -> dict[str, Any]:
        """Return the canonical external representation matching ``json_schema``."""
        value = self.to_dict()
        value["metadata"] = value.pop("extra_metadata")
        return value

    @classmethod
    def json_schema(cls) -> dict[str, Any]:
        return deepcopy(_PUBLIC_DOCUMENT_METADATA_SCHEMA)


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "idempotency_key": self.idempotency_key,
            "document_id": self.document_id,
            "state": self.state.value,
            "created_at": _serialize_datetime(self.created_at),
            "updated_at": _serialize_datetime(self.updated_at),
        }


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
        size = self.chunk_size if chunk_size is None else chunk_size
        if size <= 0:
            raise ValueError("chunk_size must be positive")
        while True:
            chunk = self.stream.read(size)
            if not chunk:
                break
            yield chunk

    def iter_chunks_closing(self, chunk_size: int | None = None) -> Iterator[bytes]:
        """Iterate content and close this stream on exhaustion, error, or iterator close."""
        failure: BaseException | None = None
        try:
            yield from self.iter_chunks(chunk_size)
        except BaseException as exc:
            failure = exc
            raise
        finally:
            try:
                self.close()
            except Exception:
                if failure is None:
                    raise

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
class AsyncDocumentContentStream:
    """Async wrapper around a storage stream; reads never block the event loop."""

    document_id: str
    _source: DocumentContentStream
    chunk_size: int = 65536
    _closed: bool = False

    @property
    def content_type(self) -> str:
        return self._source.content_type

    @property
    def filename(self) -> str:
        return self._source.filename

    @property
    def size(self) -> int:
        return self._source.size

    @property
    def checksum(self) -> str | None:
        return self._source.checksum

    @property
    def closed(self) -> bool:
        return self._closed

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        await self.aclose()

    def iter_chunks(self, chunk_size: int | None = None) -> AsyncIterator[bytes]:
        return self.aiter_chunks_closing(chunk_size)

    async def aiter_chunks_closing(self, chunk_size: int | None = None) -> AsyncIterator[bytes]:
        """Iterate content and close this stream on exhaustion, error, or cancellation."""
        failure: BaseException | None = None
        try:
            size = self.chunk_size if chunk_size is None else chunk_size
            if size <= 0:
                raise ValueError("chunk_size must be positive")
            while True:
                chunk = await asyncio.to_thread(self._source.stream.read, size)
                if not chunk:
                    break
                yield chunk
        except BaseException as exc:
            failure = exc
            raise
        finally:
            try:
                await self.aclose()
            except Exception:
                if failure is None:
                    raise

    async def aclose(self) -> None:
        if self._closed:
            return
        close_task = asyncio.create_task(asyncio.to_thread(self._source.close))
        try:
            await asyncio.shield(close_task)
        except asyncio.CancelledError:
            await close_task
            raise
        self._closed = True


@dataclass(slots=True, kw_only=True)
class DeleteDocumentResult(_JsonSchemaMixin):
    document_id: str
    deleted: bool
    hard_deleted: bool
    status: DocumentStatus

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "deleted": self.deleted,
            "hard_deleted": self.hard_deleted,
            "status": self.status.value,
        }

    @classmethod
    def json_schema(cls) -> dict[str, Any]:
        return deepcopy(_DELETE_DOCUMENT_RESULT_SCHEMA)


@dataclass(frozen=True, slots=True, kw_only=True)
class DataResetResult(_JsonSchemaMixin):
    """Counts from a destructive reset of all data owned by DMS."""

    metadata_deleted: int
    objects_deleted: int
    upload_operations_deleted: int
    ready_for_data_load: bool = True

    @property
    def total_deleted(self) -> int:
        return (
            self.metadata_deleted
            + self.objects_deleted
            + self.upload_operations_deleted
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "metadata_deleted": self.metadata_deleted,
            "objects_deleted": self.objects_deleted,
            "upload_operations_deleted": self.upload_operations_deleted,
            "ready_for_data_load": self.ready_for_data_load,
            "total_deleted": self.total_deleted,
        }

    @classmethod
    def json_schema(cls) -> dict[str, Any]:
        return deepcopy(_DATA_RESET_RESULT_SCHEMA)


def _serialize_datetime(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()



@dataclass(slots=True, kw_only=True)
class DocumentPage(_JsonSchemaMixin):
    """A cursor page in stable created_at/document_id descending order."""

    items: list[PublicDocumentMetadata]
    next_cursor: str | None
    has_more: bool

    def __iter__(self) -> Iterator[PublicDocumentMetadata]:
        """Iterate items for source compatibility with the former list result."""
        return iter(self.items)

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": [item.to_public_dict() for item in self.items],
            "next_cursor": self.next_cursor,
            "has_more": self.has_more,
        }

    @classmethod
    def json_schema(cls) -> dict[str, Any]:
        return deepcopy(_DOCUMENT_PAGE_SCHEMA)


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "metadata_exists": self.metadata_exists,
            "object_exists": self.object_exists,
            "status": self.status.value if self.status is not None else None,
            "consistent": self.consistent,
            "issue": self.issue.value,
            "storage_key": self.storage_key,
        }


@dataclass(slots=True, kw_only=True)
class ReconciliationResult:
    document_id: str
    action: RecoveryAction
    applied: bool
    inspection: DocumentInspection | None
    error_type: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "action": self.action.value,
            "applied": self.applied,
            "inspection": self.inspection.to_dict() if self.inspection is not None else None,
            "error_type": self.error_type,
            "error_message": self.error_message,
        }


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "action": self.action.value,
            "dry_run": self.dry_run,
            "offset": self.offset,
            "limit": self.limit,
            "scanned": self.scanned,
            "failed": self.failed,
            "eligible": self.eligible,
            "applied": self.applied,
            "skipped": self.skipped,
            "items": [item.to_dict() for item in self.items],
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ReconciliationPlanItem:
    document_id: str
    action: RecoveryAction
    storage_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "action": self.action.value,
            "storage_key": self.storage_key,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ReconciliationPlan:
    status: DocumentStatus
    action: RecoveryAction
    items: tuple[ReconciliationPlanItem, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(self.items))
        if any(item.action is not self.action for item in self.items):
            raise ValueError("reconciliation item action differs from plan action")

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "action": self.action.value,
            "items": [item.to_dict() for item in self.items],
        }


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "action": self.action.value,
            "dry_run": self.dry_run,
            "succeeded": self.succeeded,
            "applied": self.applied,
            "occurred_at": _serialize_datetime(self.occurred_at),
            "actor": self.actor,
            "error_type": self.error_type,
            "error_message": self.error_message,
        }


_NULLABLE_STRING_SCHEMA = {"anyOf": [{"type": "string"}, {"type": "null"}]}
_NULLABLE_DATETIME_SCHEMA = {
    "anyOf": [{"type": "string", "format": "date-time"}, {"type": "null"}]
}
_PUBLIC_DOCUMENT_METADATA_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "PublicDocumentMetadata",
    "type": "object",
    "properties": {
        "document_id": {"type": "string"},
        "original_filename": {"type": "string"},
        "content_type": {"type": "string"},
        "file_size": {"type": "integer", "minimum": 0},
        "status": {"type": "string", "enum": [status.value for status in DocumentStatus]},
        "created_at": {"type": "string", "format": "date-time"},
        "updated_at": {"type": "string", "format": "date-time"},
        "checksum": _NULLABLE_STRING_SCHEMA,
        "deleted_at": _NULLABLE_DATETIME_SCHEMA,
        "created_by": _NULLABLE_STRING_SCHEMA,
        "metadata": {},
    },
    "required": [
        "document_id",
        "original_filename",
        "content_type",
        "file_size",
        "status",
        "created_at",
        "updated_at",
    ],
    "additionalProperties": False,
}
_UPLOAD_DOCUMENT_RESULT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "UploadDocumentResult",
    "type": "object",
    "properties": {
        "document_id": {"type": "string"},
        "metadata": _PUBLIC_DOCUMENT_METADATA_SCHEMA,
        "created": {"type": "boolean"},
    },
    "required": ["document_id", "metadata"],
    "additionalProperties": False,
}
_DOCUMENT_PAGE_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "DocumentPage",
    "type": "object",
    "properties": {
        "items": {"type": "array", "items": _PUBLIC_DOCUMENT_METADATA_SCHEMA},
        "next_cursor": _NULLABLE_STRING_SCHEMA,
        "has_more": {"type": "boolean"},
    },
    "required": ["items", "next_cursor", "has_more"],
    "additionalProperties": False,
}
_DELETE_DOCUMENT_RESULT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "DeleteDocumentResult",
    "type": "object",
    "properties": {
        "document_id": {"type": "string"},
        "deleted": {"type": "boolean"},
        "hard_deleted": {"type": "boolean"},
        "status": {"type": "string", "enum": [status.value for status in DocumentStatus]},
    },
    "required": ["document_id", "deleted", "hard_deleted", "status"],
    "additionalProperties": False,
}
_DATA_RESET_RESULT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "DataResetResult",
    "type": "object",
    "properties": {
        "metadata_deleted": {"type": "integer", "minimum": 0},
        "objects_deleted": {"type": "integer", "minimum": 0},
        "upload_operations_deleted": {"type": "integer", "minimum": 0},
        "ready_for_data_load": {"type": "boolean"},
        "total_deleted": {"type": "integer", "minimum": 0},
    },
    "required": [
        "metadata_deleted",
        "objects_deleted",
        "upload_operations_deleted",
        "ready_for_data_load",
        "total_deleted",
    ],
    "additionalProperties": False,
}
