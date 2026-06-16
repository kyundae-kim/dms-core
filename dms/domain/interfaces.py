from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from dms.domain.models import DocumentMetadata


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
class StoredObject:
    document_id: str
    storage_key: str
    content: bytes
    content_type: str
    filename: str
    size: int
    checksum: str | None = None


class MetadataStore(Protocol):
    def save_metadata(self, metadata: DocumentMetadata) -> DocumentMetadata: ...

    def get_metadata(self, document_id: str) -> DocumentMetadata: ...

    def mark_deleted(self, document_id: str) -> DocumentMetadata: ...

    def hard_delete(self, document_id: str) -> None: ...

    def exists(self, document_id: str) -> bool: ...


class ObjectStore(Protocol):
    def put_object(self, request: PutObjectRequest) -> str: ...

    def get_object(self, document_id: str, storage_key: str) -> StoredObject: ...

    def delete_object(self, document_id: str, storage_key: str) -> None: ...

    def object_exists(self, document_id: str, storage_key: str) -> bool: ...


class AuthService(Protocol):
    def fetch_access_token(self, *, scope: str | None = None) -> object: ...

    def extract_user_info(self, token: str) -> object: ...


class MetadataIdGenerator(Protocol):
    def new_document_id(self) -> str: ...
