from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, BinaryIO, Protocol

from dms.domain.models import (
    DocumentMetadata,
    DocumentStatus,
    UploadOperation,
    UploadOperationClaim,
)


@dataclass(slots=True, kw_only=True)
class PutObjectRequest:
    document_id: str
    storage_key: str
    content: bytes
    content_type: str
    filename: str
    checksum: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass(slots=True, kw_only=True)
class PutObjectStreamRequest:
    document_id: str
    storage_key: str
    stream: BinaryIO
    size: int
    chunk_size: int
    content_type: str
    filename: str
    checksum: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass(slots=True, kw_only=True)
class StoredObject:
    document_id: str
    storage_key: str
    content: bytes
    content_type: str
    filename: str
    size: int
    checksum: str | None = None


@dataclass(slots=True, kw_only=True)
class StoredObjectStream:
    document_id: str
    storage_key: str
    stream: BinaryIO
    content_type: str
    filename: str
    size: int
    checksum: str | None = None


@dataclass(slots=True, kw_only=True)
class AsyncStoredObjectStream:
    document_id: str
    storage_key: str
    stream: Any
    content_type: str
    filename: str
    size: int
    close_callback: Callable[[], Awaitable[object] | object] | None = None
    checksum: str | None = None


class MetadataConflictError(Exception):
    """Raised by a metadata store when a document identifier conflicts."""


class MetadataStore(Protocol):
    def allocate_document_id(self) -> str: ...

    def save_metadata(self, metadata: DocumentMetadata) -> DocumentMetadata: ...

    def update_metadata(self, metadata: DocumentMetadata) -> DocumentMetadata: ...

    def get_metadata(
        self, document_id: str, *, user_id: str | None = None,
    ) -> DocumentMetadata: ...

    def list_metadata(
        self,
        *,
        offset: int,
        limit: int,
        status: DocumentStatus | None = None,
        excluded_statuses: tuple[DocumentStatus, ...] = (),
        user_id: str | None = None,
        unscoped_only: bool = False,
    ) -> list[DocumentMetadata]: ...

    def list_metadata_page(
        self,
        *,
        after_created_at: datetime | None = None,
        after_document_id: str | None = None,
        limit: int,
        status: DocumentStatus | None = None,
        excluded_statuses: tuple[DocumentStatus, ...] = (),
        user_id: str | None = None,
        unscoped_only: bool = False,
    ) -> list[DocumentMetadata]: ...

    def mark_deleted(self, document_id: str) -> DocumentMetadata: ...

    def hard_delete(self, document_id: str) -> None: ...

    def clear_all(self, *, user_id: str | None = None) -> int: ...

    def exists(self, document_id: str, *, user_id: str | None = None) -> bool: ...


class ObjectStore(Protocol):
    def put_object(self, request: PutObjectRequest) -> str: ...

    def put_object_stream(self, request: PutObjectStreamRequest) -> str: ...

    def get_object(self, document_id: str, storage_key: str) -> StoredObject: ...

    def get_object_stream(self, document_id: str, storage_key: str) -> StoredObjectStream: ...

    def delete_object(self, document_id: str, storage_key: str) -> None: ...

    def clear_all(self, *, user_id: str | None = None) -> int: ...

    def object_exists(self, document_id: str, storage_key: str) -> bool: ...


class UploadOperationStore(Protocol):
    def get(self, *, scope: str, idempotency_key: str) -> UploadOperation: ...

    def claim(
        self, *, scope: str, idempotency_key: str, fingerprint: str, document_id: str
    ) -> UploadOperationClaim: ...

    def mark_succeeded(self, *, scope: str, idempotency_key: str) -> None: ...

    def mark_failed(self, *, scope: str, idempotency_key: str) -> None: ...

    def clear_all(self, *, scope_prefix: str | None = None) -> int: ...


class AsyncMetadataStore(Protocol):
    async def allocate_document_id(self) -> str: ...

    async def save_metadata(self, metadata: DocumentMetadata) -> DocumentMetadata: ...

    async def update_metadata(self, metadata: DocumentMetadata) -> DocumentMetadata: ...

    async def get_metadata(
        self, document_id: str, *, user_id: str | None = None,
    ) -> DocumentMetadata: ...

    async def list_metadata(
        self,
        *,
        offset: int,
        limit: int,
        status: DocumentStatus | None = None,
        excluded_statuses: tuple[DocumentStatus, ...] = (),
        user_id: str | None = None,
        unscoped_only: bool = False,
    ) -> list[DocumentMetadata]: ...

    async def list_metadata_page(
        self,
        *,
        after_created_at: datetime | None = None,
        after_document_id: str | None = None,
        limit: int,
        status: DocumentStatus | None = None,
        excluded_statuses: tuple[DocumentStatus, ...] = (),
        user_id: str | None = None,
        unscoped_only: bool = False,
    ) -> list[DocumentMetadata]: ...

    async def mark_deleted(self, document_id: str) -> DocumentMetadata: ...

    async def hard_delete(self, document_id: str) -> None: ...

    async def clear_all(self, *, user_id: str | None = None) -> int: ...

    async def exists(self, document_id: str, *, user_id: str | None = None) -> bool: ...


class AsyncObjectStore(Protocol):
    async def put_object(self, request: PutObjectRequest) -> str: ...

    async def put_object_stream(self, request: PutObjectStreamRequest) -> str: ...

    async def get_object(self, document_id: str, storage_key: str) -> StoredObject: ...

    async def get_object_stream(
        self, document_id: str, storage_key: str
    ) -> AsyncStoredObjectStream: ...

    async def delete_object(self, document_id: str, storage_key: str) -> None: ...

    async def clear_all(self, *, user_id: str | None = None) -> int: ...

    async def object_exists(self, document_id: str, storage_key: str) -> bool: ...


class AsyncUploadOperationStore(Protocol):
    async def get(self, *, scope: str, idempotency_key: str) -> UploadOperation: ...

    async def claim(
        self, *, scope: str, idempotency_key: str, fingerprint: str, document_id: str
    ) -> UploadOperationClaim: ...

    async def mark_succeeded(self, *, scope: str, idempotency_key: str) -> None: ...

    async def mark_failed(self, *, scope: str, idempotency_key: str) -> None: ...

    async def clear_all(self, *, scope_prefix: str | None = None) -> int: ...
