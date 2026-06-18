from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, BinaryIO, Callable, Iterator

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

    def iter_chunks(self, chunk_size: int | None = None) -> Iterator[bytes]:
        size = chunk_size or self.chunk_size
        while True:
            chunk = self.stream.read(size)
            if not chunk:
                break
            yield chunk

    def close(self) -> None:
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
