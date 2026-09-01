from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Any, BinaryIO, Protocol, runtime_checkable

from dms.domain.models import DocumentStatus
from dms.sdk.types import (
    DataResetResult,
    DeleteDocumentResult,
    DocumentContent,
    DocumentContentStream,
    DocumentPage,
    PublicDocumentMetadata,
    UploadDocumentRequest,
    UploadDocumentResult,
    UploadDocumentStreamRequest,
)


def build_log_extra(event: str, context: Mapping[str, object]) -> dict[str, object]:
    return {"dms_event": event, **{f"dms_{key}": value for key, value in context.items()}}


class _LoggingMixin:
    """Share the SDK service logging contract without duplicating wrappers."""

    _logger: logging.Logger

    def _log_info(self, event: str, **context: object) -> None:
        self._logger.info(event, extra=build_log_extra(event, context))

    def _log_warning(self, event: str, **context: object) -> None:
        self._logger.warning(event, extra=build_log_extra(event, context))

    def _log_exception(self, event: str, exc: Exception, **context: object) -> None:
        self._logger.exception(
            event,
            extra=build_log_extra(event, {**context, "error_type": type(exc).__name__}),
        )


def user_storage_segment(user_id: str) -> str:
    """Return a path-safe, non-reversible storage segment for a user."""
    return sha256(user_id.encode("utf-8")).hexdigest()


def user_storage_prefix(user_id: str) -> str:
    return f"documents/users/{user_storage_segment(user_id)}/"


def user_operation_scope_prefix(user_id: str) -> str:
    return f"user:{user_storage_segment(user_id)}:"


def user_operation_scope(user_id: str, scope: str) -> str:
    """Namespace idempotency records without exposing the user id in a key."""
    return f"{user_operation_scope_prefix(user_id)}{scope}"


@dataclass(frozen=True, slots=True, kw_only=True)
class AccessContext:
    subject: str | None = None
    user_id: str | None = None
    tenant: str | None = None
    roles: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if self.user_id is not None and (
            not isinstance(self.user_id, str) or not self.user_id.strip()
        ):
            raise ValueError("user_id must be a non-empty string when provided")
        object.__setattr__(self, "roles", frozenset(self.roles))


class DocumentAccessPolicy(Protocol):
    def allows(
        self,
        *,
        operation: str,
        context: AccessContext | None,
        metadata: PublicDocumentMetadata | None,
    ) -> bool: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class OperationEvent:
    operation: str
    succeeded: bool
    started_at: datetime
    completed_at: datetime
    document_id: str | None = None
    conditions: Mapping[str, object] = field(default_factory=dict)
    error_code: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "conditions", MappingProxyType(dict(self.conditions)))

    def to_dict(self) -> dict[str, object]:
        return {
            "operation": self.operation,
            "succeeded": self.succeeded,
            "document_id": self.document_id,
            "conditions": dict(self.conditions),
            "error_code": self.error_code,
            "started_at": _serialize_datetime(self.started_at),
            "completed_at": _serialize_datetime(self.completed_at),
        }


class OperationObserver(Protocol):
    def __call__(self, event: OperationEvent) -> object: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class DocumentCopyResult:
    document_id: str
    bytes_copied: int
    checksum: str
    checksum_verified: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "document_id": self.document_id,
            "bytes_copied": self.bytes_copied,
            "checksum": self.checksum,
            "checksum_verified": self.checksum_verified,
        }


@runtime_checkable
class DocumentWriter(Protocol):
    def upload_document(
        self,
        request: UploadDocumentRequest,
        *,
        access_context: AccessContext | None = None,
    ) -> UploadDocumentResult: ...

    def upload_file(
        self, path: str | Path, *, filename: str | None = None,
        content_type: str | None = None,
        document_id: str | None = None, metadata: dict[str, Any] | None = None,
        created_by: str | None = None,
        access_context: AccessContext | None = None,
    ) -> UploadDocumentResult: ...

    def upload_document_stream(
        self, request: UploadDocumentStreamRequest,
        *, access_context: AccessContext | None = None,
    ) -> UploadDocumentResult: ...


@runtime_checkable
class DocumentReader(Protocol):
    def get_document_metadata(
        self, document_id: str, *, access_context: AccessContext | None = None,
    ) -> PublicDocumentMetadata: ...

    def get_document_content(
        self, document_id: str, *, access_context: AccessContext | None = None,
    ) -> DocumentContent: ...

    def get_document_content_stream(
        self, document_id: str, *, chunk_size: int = 65536,
        access_context: AccessContext | None = None,
    ) -> DocumentContentStream: ...

    def copy_document_to(
        self, document_id: str, sink: BinaryIO, *, chunk_size: int = 65536,
        verify_checksum: bool = True, access_context: AccessContext | None = None,
    ) -> DocumentCopyResult: ...


@runtime_checkable
class DocumentLister(Protocol):
    def list_documents(
        self, *, cursor: str | None = None, limit: int = 100,
        status: DocumentStatus | None = None,
        access_context: AccessContext | None = None,
    ) -> DocumentPage: ...

    def iter_documents(
        self, *, status: DocumentStatus | None = None, page_size: int = 100,
        access_context: AccessContext | None = None,
    ) -> Iterator[PublicDocumentMetadata]: ...


@runtime_checkable
class DocumentDeleter(Protocol):
    def delete_document(
        self, document_id: str, *, hard_delete: bool = False,
        access_context: AccessContext | None = None,
    ) -> DeleteDocumentResult: ...


@runtime_checkable
class DataResetter(Protocol):
    def clear_all_data(
        self, *, access_context: AccessContext | None = None,
    ) -> DataResetResult: ...

    def initialize_for_data_load(
        self, *, access_context: AccessContext | None = None,
    ) -> DataResetResult: ...


@runtime_checkable
class DocumentManagementClient(
    DocumentWriter,
    DocumentReader,
    DocumentLister,
    DocumentDeleter,
    DataResetter,
    Protocol,
):
    pass


class AsyncDocumentIterator(Protocol):
    def __call__(
        self, *, status: DocumentStatus | None = None, page_size: int = 100,
        access_context: AccessContext | None = None,
    ) -> AsyncIterator[PublicDocumentMetadata]: ...


def _serialize_datetime(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()
