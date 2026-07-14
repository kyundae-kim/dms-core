from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class DocumentStatus(StrEnum):
    UPLOADED = "uploaded"
    AVAILABLE = "available"
    DELETING = "deleting"
    DELETED = "deleted"
    FAILED = "failed"


class UploadOperationState(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(slots=True, kw_only=True)
class UploadOperation:
    scope: str
    idempotency_key: str
    fingerprint: str
    document_id: str
    state: UploadOperationState
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True, kw_only=True)
class UploadOperationClaim:
    operation: UploadOperation
    claimed: bool


@dataclass(slots=True, kw_only=True)
class DocumentMetadata:
    document_id: str
    original_filename: str
    content_type: str
    file_size: int
    storage_key: str
    status: DocumentStatus
    created_at: datetime
    updated_at: datetime
    checksum: str | None = None
    deleted_at: datetime | None = None
    created_by: str | None = None
    extra_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, kw_only=True)
class StoredDocument:
    metadata: DocumentMetadata
    content: bytes
