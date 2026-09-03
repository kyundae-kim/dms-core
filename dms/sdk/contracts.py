from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import AsyncIterator, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Any, BinaryIO, Protocol, TypeAlias, runtime_checkable

from dms.domain.models import DocumentMetadata, DocumentPartition, DocumentStatus
from dms.sdk.errors import AccessDeniedError, ValidationError
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
    public_metadata,
)


def build_log_extra(event: str, context: Mapping[str, object]) -> dict[str, object]:
    return {
        "dms_event": event,
        **{f"dms_{key}": value for key, value in context.items()},
    }


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


def partition_storage_segment(partition: DocumentPartition) -> str:
    """Return a path-safe, non-reversible segment for one partition."""
    return sha256(partition.partition_id.encode("utf-8")).hexdigest()


def partition_storage_prefix(partition: DocumentPartition) -> str:
    return (
        f"documents/partitions/{partition.kind.value}/"
        f"{partition_storage_segment(partition)}/"
    )


def partition_operation_scope_prefix(partition: DocumentPartition) -> str:
    return f"partition:{partition.kind.value}:{partition_storage_segment(partition)}:"


def partition_operation_scope(partition: DocumentPartition, scope: str) -> str:
    """Namespace idempotency records by exact personal or group partition."""
    return f"{partition_operation_scope_prefix(partition)}{scope}"


def _validate_partition(partition: DocumentPartition) -> None:
    if not isinstance(partition, DocumentPartition):
        raise ValidationError("partition must be a DocumentPartition")


@dataclass(frozen=True, slots=True, kw_only=True)
class AccessContext:
    """Host-authenticated caller data used by a document access policy.

    DMS treats all values as opaque. Authentication and group membership are
    resolved by the host before the context is passed to the SDK.
    """

    subject: str | None = None
    user_id: str | None = None
    tenant: str | None = None
    groups: frozenset[str] = field(default_factory=frozenset)
    roles: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        for field_name in ("subject", "user_id", "tenant"):
            value = getattr(self, field_name)
            if value is not None and (
                not isinstance(value, str) or not value.strip()
            ):
                raise ValueError(
                    f"{field_name} must be a non-empty string when provided"
                )
        for field_name in ("groups", "roles"):
            raw_values = getattr(self, field_name)
            if isinstance(raw_values, (str, bytes)):
                raise TypeError(f"{field_name} must be a collection of strings")
            try:
                values = frozenset(raw_values)
            except TypeError as exc:
                raise ValueError(f"{field_name} must be a collection of strings") from exc
            if any(not isinstance(value, str) or not value.strip() for value in values):
                raise ValueError(f"{field_name} must contain non-empty strings")
            object.__setattr__(self, field_name, values)

    @property
    def group_ids(self) -> frozenset[str]:
        """Alias for hosts that use an explicit group-id vocabulary."""
        return self.groups


@runtime_checkable
class DocumentAccessPolicy(Protocol):
    """Host-provided authorization policy for SDK operations.

    ``metadata`` is always the public projection and is ``None`` for
    partition-wide or metadata-independent operations. The policy must not
    perform authentication or group membership discovery inside DMS.
    """

    def allows(
        self,
        *,
        operation: str,
        context: AccessContext | None,
        metadata: PublicDocumentMetadata | None,
    ) -> bool: ...


@runtime_checkable
class AsyncDocumentAccessPolicy(Protocol):
    """Async host-provided authorization policy for native async SDK calls."""

    async def allows(
        self,
        *,
        operation: str,
        context: AccessContext | None,
        metadata: PublicDocumentMetadata | None,
    ) -> bool: ...


AccessPolicy: TypeAlias = DocumentAccessPolicy | AsyncDocumentAccessPolicy


def _project_access_metadata(
    metadata: DocumentMetadata | PublicDocumentMetadata | None,
) -> PublicDocumentMetadata | None:
    if metadata is None or isinstance(metadata, PublicDocumentMetadata):
        return metadata
    return public_metadata(metadata)


def _raise_access_denied(
    metadata: DocumentMetadata | PublicDocumentMetadata | None,
    *,
    cause: BaseException | None = None,
) -> None:
    projected = _project_access_metadata(metadata)
    if cause is None:
        raise AccessDeniedError(
            "Access to the document operation was denied",
            document_id=projected.document_id if projected is not None else None,
        )
    raise AccessDeniedError(
        "The access policy could not authorize the operation",
        document_id=projected.document_id if projected is not None else None,
    ) from cause


def _enforce_access(
    access_policy: DocumentAccessPolicy | None,
    *,
    operation: str,
    context: AccessContext | None,
    metadata: DocumentMetadata | PublicDocumentMetadata | None,
) -> None:
    if access_policy is None:
        return
    projected = _project_access_metadata(metadata)
    try:
        allowed = access_policy.allows(
            operation=operation,
            context=context,
            metadata=projected,
        )
        if inspect.isawaitable(allowed):
            raise TypeError("synchronous access policy returned an awaitable")
    except Exception as exc:  # noqa: BLE001 - isolate host policy failures
        _raise_access_denied(metadata, cause=exc)
    if not allowed:
        _raise_access_denied(metadata)


async def _enforce_access_async(
    access_policy: AccessPolicy | None,
    *,
    operation: str,
    context: AccessContext | None,
    metadata: DocumentMetadata | PublicDocumentMetadata | None,
) -> None:
    if access_policy is None:
        return
    projected = _project_access_metadata(metadata)
    try:
        allows = access_policy.allows
        if inspect.iscoroutinefunction(allows):
            allowed = allows(
                operation=operation,
                context=context,
                metadata=projected,
            )
        else:
            allowed = await asyncio.to_thread(
                allows,
                operation=operation,
                context=context,
                metadata=projected,
            )
        if inspect.isawaitable(allowed):
            allowed = await allowed
    except Exception as exc:  # noqa: BLE001 - isolate host policy failures
        _raise_access_denied(metadata, cause=exc)
    if not allowed:
        _raise_access_denied(metadata)


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
        partition: DocumentPartition,
        access_context: AccessContext | None = None,
    ) -> UploadDocumentResult: ...

    def upload_file(
        self,
        path: str | Path,
        *,
        filename: str | None = None,
        content_type: str | None = None,
        document_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        created_by: str | None = None,
        partition: DocumentPartition,
        access_context: AccessContext | None = None,
    ) -> UploadDocumentResult: ...

    def upload_document_stream(
        self,
        request: UploadDocumentStreamRequest,
        *,
        partition: DocumentPartition,
        access_context: AccessContext | None = None,
    ) -> UploadDocumentResult: ...


@runtime_checkable
class DocumentReader(Protocol):
    def get_document_metadata(
        self,
        document_id: str,
        *,
        partition: DocumentPartition,
        access_context: AccessContext | None = None,
    ) -> PublicDocumentMetadata: ...

    def get_document_content(
        self,
        document_id: str,
        *,
        partition: DocumentPartition,
        access_context: AccessContext | None = None,
    ) -> DocumentContent: ...

    def get_document_content_stream(
        self,
        document_id: str,
        *,
        chunk_size: int = 65536,
        partition: DocumentPartition,
        access_context: AccessContext | None = None,
    ) -> DocumentContentStream: ...

    def copy_document_to(
        self,
        document_id: str,
        sink: BinaryIO,
        *,
        chunk_size: int = 65536,
        verify_checksum: bool = True,
        partition: DocumentPartition,
        access_context: AccessContext | None = None,
    ) -> DocumentCopyResult: ...


@runtime_checkable
class DocumentLister(Protocol):
    def list_documents(
        self,
        *,
        partition: DocumentPartition,
        cursor: str | None = None,
        limit: int = 100,
        status: DocumentStatus | None = None,
        access_context: AccessContext | None = None,
    ) -> DocumentPage: ...

    def iter_documents(
        self,
        *,
        partition: DocumentPartition,
        status: DocumentStatus | None = None,
        page_size: int = 100,
        access_context: AccessContext | None = None,
    ) -> Iterator[PublicDocumentMetadata]: ...


@runtime_checkable
class DocumentDeleter(Protocol):
    def delete_document(
        self,
        document_id: str,
        *,
        partition: DocumentPartition,
        hard_delete: bool = False,
        access_context: AccessContext | None = None,
    ) -> DeleteDocumentResult: ...


@runtime_checkable
class DataResetter(Protocol):
    def clear_all_data(
        self,
        *,
        access_context: AccessContext | None = None,
    ) -> DataResetResult: ...

    def clear_partition_data(
        self,
        *,
        partition: DocumentPartition,
        access_context: AccessContext | None = None,
    ) -> DataResetResult: ...

    def initialize_for_data_load(
        self,
        *,
        access_context: AccessContext | None = None,
    ) -> DataResetResult: ...

    def initialize_partition_for_data_load(
        self,
        *,
        partition: DocumentPartition,
        access_context: AccessContext | None = None,
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
        self,
        *,
        partition: DocumentPartition,
        status: DocumentStatus | None = None,
        page_size: int = 100,
        access_context: AccessContext | None = None,
    ) -> AsyncIterator[PublicDocumentMetadata]: ...


def _serialize_datetime(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()
