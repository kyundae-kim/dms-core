from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from tempfile import SpooledTemporaryFile
from collections.abc import Callable, Mapping
from typing import Any, BinaryIO, Protocol, cast

from dms.sdk.errors import ValidationError
from dms.sdk.types import (
    UploadDocumentRequest,
    UploadDocumentResult,
    UploadDocumentStreamRequest,
    UploadDocumentUnknownSizeStreamRequest,
)

_UNKNOWN_SIZE_SPOOL_MEMORY_LIMIT = 1024 * 1024
_MAX_STREAM_CHUNK_SIZE = 1024 * 1024


class _UploadHost(Protocol):
    _max_file_size: int | None

    def _normalize_metadata(self, metadata: Mapping[str, object]) -> dict[str, object]: ...
    def _idempotent_upload(
        self,
        request: object,
        checksum: str,
        upload: Callable[[Any], UploadDocumentResult],
    ) -> UploadDocumentResult: ...
    def _upload_document(self, request: UploadDocumentRequest) -> UploadDocumentResult: ...
    def _upload_document_stream(self, request: UploadDocumentStreamRequest) -> UploadDocumentResult: ...
    def upload_document_stream(self, request: UploadDocumentStreamRequest) -> UploadDocumentResult: ...


class UploadService:
    """Coordinates SDK upload entry points; adapters remain owned by the SDK host."""

    def __init__(
        self,
        host: _UploadHost,
        *,
        spool_factory: Callable[..., Any] = SpooledTemporaryFile,
    ) -> None:
        self._host = host
        self._spool_factory = spool_factory

    def upload_document(self, request: UploadDocumentRequest) -> UploadDocumentResult:
        request = replace(request, metadata=self._host._normalize_metadata(request.metadata))
        checksum = sha256(request.content).hexdigest()
        return self._host._idempotent_upload(request, checksum, self._host._upload_document)

    def upload_document_stream(self, request: UploadDocumentStreamRequest) -> UploadDocumentResult:
        request = replace(request, metadata=self._host._normalize_metadata(request.metadata))
        if request.idempotency_key is not None and request.checksum is None:
            raise ValidationError("checksum is required for an idempotent streaming upload")
        return self._host._idempotent_upload(
            request, request.checksum or "", self._host._upload_document_stream
        )

    def upload_document_unknown_size_stream(
        self, request: UploadDocumentUnknownSizeStreamRequest
    ) -> UploadDocumentResult:
        if request.max_size <= 0:
            raise ValidationError("max_size must be positive")
        if self._host._max_file_size is not None and request.max_size > self._host._max_file_size:
            raise ValidationError("max_size exceeds configured max_file_size")
        if request.chunk_size <= 0 or request.chunk_size > _MAX_STREAM_CHUNK_SIZE:
            raise ValidationError("chunk_size must be between 1 and 1048576")
        size = 0
        digest = sha256()
        with self._spool_factory(max_size=_UNKNOWN_SIZE_SPOOL_MEMORY_LIMIT, mode="w+b") as spool:
            while True:
                chunk = request.stream.read(request.chunk_size)
                if not isinstance(chunk, bytes):
                    raise ValidationError("stream.read() must return bytes")
                if not chunk:
                    break
                size += len(chunk)
                if size > request.max_size:
                    raise ValidationError("stream exceeds max_size")
                digest.update(chunk)
                spool.write(chunk)
            spool.seek(0)
            return self._host.upload_document_stream(UploadDocumentStreamRequest(
                stream=cast(BinaryIO, spool), size=size, filename=request.filename,
                content_type=request.content_type, document_id=request.document_id,
                metadata=dict(request.metadata), created_by=request.created_by,
                checksum=digest.hexdigest(), chunk_size=request.chunk_size,
                idempotency_key=request.idempotency_key,
                idempotency_scope=request.idempotency_scope,
            ))
