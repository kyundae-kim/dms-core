from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import BinaryIO, Literal, Protocol, runtime_checkable

from dms.domain.models import DocumentStatus
from dms.sdk.metadata import MetadataValidator
from dms.sdk.types import (
    DataResetResult,
    DeleteDocumentResult,
    DocumentContent,
    DocumentContentStream,
    DocumentPage,
    HealthStatus,
    PublicDocumentMetadata,
    RecoveryAuditEvent,
    UploadDocumentRequest,
    UploadDocumentResult,
    UploadDocumentStreamRequest,
)


class ResourceOwnership(StrEnum):
    CALLER = "caller"
    SDK = "sdk"


@dataclass(frozen=True, slots=True, kw_only=True)
class ManagedResource:
    resource: object
    ownership: ResourceOwnership = ResourceOwnership.CALLER
    close: Callable[[], object] | None = None
    aclose: Callable[[], object] | None = None
    name: str | None = None

    def __post_init__(self) -> None:
        if self.ownership is ResourceOwnership.SDK and self.close is None and self.aclose is None:
            raise ValueError("SDK-owned resources require close or aclose")


@dataclass(frozen=True, slots=True, kw_only=True)
class AccessContext:
    subject: str | None = None
    tenant: str | None = None
    roles: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
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
class DmsOperationContext:
    access: AccessContext | None = None
    created_by: str | None = None
    idempotency_scope: str | None = None
    audit_actor: str | None = None
    default_metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "default_metadata", MappingProxyType(dict(self.default_metadata)))


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
class DmsAssemblyPlan:
    metadata_backend: Literal["auto", "postgresql", "sqlite"] = "auto"
    strict_configuration: bool = False
    metadata_validator: MetadataValidator | None = None
    metadata_max_serialized_bytes: int = 16_384
    metadata_max_depth: int = 8
    max_file_size: int | None = None
    check_on_startup: bool = False
    startup_timeout_seconds: float | None = None
    logger: logging.Logger | None = None
    recovery_audit_hook: Callable[[RecoveryAuditEvent], object] | None = None
    operation_observer: OperationObserver | None = None
    access_policy: DocumentAccessPolicy | None = None

    def __post_init__(self) -> None:
        if self.metadata_backend not in {"auto", "postgresql", "sqlite"}:
            raise ValueError("metadata_backend must be auto, postgresql, or sqlite")
        if self.metadata_max_serialized_bytes <= 0:
            raise ValueError("metadata_max_serialized_bytes must be positive")
        if self.metadata_max_depth <= 0:
            raise ValueError("metadata_max_depth must be positive")
        if self.max_file_size is not None and self.max_file_size <= 0:
            raise ValueError("max_file_size must be positive")
        if self.startup_timeout_seconds is not None and self.startup_timeout_seconds <= 0:
            raise ValueError("startup_timeout_seconds must be positive")


@dataclass(frozen=True, slots=True, kw_only=True)
class DmsServiceConfigs:
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_bucket: str
    minio_secure: bool = False
    sqlite_path: str | None = None
    postgres_host: str | None = None
    postgres_port: int = 5432
    postgres_database: str | None = None
    postgres_user: str | None = None
    postgres_password: str | None = None

    def __post_init__(self) -> None:
        required_minio = (
            self.minio_endpoint,
            self.minio_access_key,
            self.minio_secret_key,
            self.minio_bucket,
        )
        if any(not value.strip() for value in required_minio):
            raise ValueError("MinIO endpoint, credentials, and bucket are required")
        sqlite_configured = self.sqlite_path is not None
        postgres_values = (
            self.postgres_host,
            self.postgres_database,
            self.postgres_user,
            self.postgres_password,
        )
        postgres_configured = any(value is not None for value in postgres_values)
        if sqlite_configured == postgres_configured:
            raise ValueError("exactly one metadata backend must be configured")
        if postgres_configured and any(value is None or not value.strip() for value in postgres_values):
            raise ValueError("PostgreSQL configuration is incomplete")
        if self.postgres_port <= 0:
            raise ValueError("postgres_port must be positive")


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
    def upload_document(self, request: UploadDocumentRequest) -> UploadDocumentResult: ...

    def upload_file(
        self, path: str | Path, *, filename: str | None = None,
        content_type: str | None = None,
        document_id: str | None = None, metadata: Mapping[str, object] | None = None,
        created_by: str | None = None,
    ) -> UploadDocumentResult: ...

    def upload_document_stream(
        self, request: UploadDocumentStreamRequest,
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
class DocumentHealth(Protocol):
    def check_health(self) -> HealthStatus: ...


@runtime_checkable
class DocumentManagementClient(
    DocumentWriter,
    DocumentReader,
    DocumentLister,
    DocumentDeleter,
    DataResetter,
    DocumentHealth,
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
