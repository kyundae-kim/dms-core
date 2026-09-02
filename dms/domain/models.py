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


class PartitionKind(StrEnum):
    PERSONAL = "personal"
    GROUP = "group"


@dataclass(frozen=True, slots=True, kw_only=True)
class DocumentPartition:
    kind: PartitionKind
    partition_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, PartitionKind):
            raise TypeError("kind must be a PartitionKind")
        if not isinstance(self.partition_id, str):
            raise TypeError("partition_id must be a string")
        if not self.partition_id.strip():
            raise ValueError("partition_id must be a non-empty string")

    @classmethod
    def personal(cls, partition_id: str) -> DocumentPartition:
        return cls(kind=PartitionKind.PERSONAL, partition_id=partition_id)

    @classmethod
    def group(cls, partition_id: str) -> DocumentPartition:
        return cls(kind=PartitionKind.GROUP, partition_id=partition_id)

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind.value,
            "partition_id": self.partition_id,
        }


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
    partition: DocumentPartition
    checksum: str | None = None
    deleted_at: datetime | None = None
    created_by: str | None = None
    extra_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, kw_only=True)
class StoredDocument:
    metadata: DocumentMetadata
    content: bytes
