from __future__ import annotations

import asyncio
import logging

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from tempfile import SpooledTemporaryFile
from time import perf_counter
from typing import Any, BinaryIO, cast

from sqlalchemy.exc import IntegrityError

from dms.domain.interfaces import MetadataStore, ObjectStore, PutObjectRequest, PutObjectStreamRequest, UploadOperationStore
from dms.domain.models import DocumentMetadata, DocumentStatus, UploadOperationState
from dms.sdk.errors import (
    ConsistencyError, DuplicateDocumentError, IdempotencyInProgressError,
    MetadataStoreError, PayloadTooLargeError, StorageError, UploadOperationNotFoundError,
    ValidationError,
)
from dms.sdk.idempotency import build_upload_fingerprint
from dms.sdk.metadata import MetadataValidator
from dms.sdk.types import (
    AsyncUploadDocumentStreamRequest, AsyncUploadDocumentUnknownSizeStreamRequest,
    PublicDocumentMetadata, UploadDocumentRequest, UploadDocumentResult,
    UploadDocumentStreamRequest, UploadDocumentUnknownSizeStreamRequest,
    UploadOperationResult, public_metadata,
)

_UNKNOWN_SIZE_SPOOL_MEMORY_LIMIT = 1024 * 1024
_MAX_STREAM_CHUNK_SIZE = 1024 * 1024


class _HashingReader:
    def __init__(self, stream: BinaryIO) -> None:
        self._stream = stream
        self.bytes_read = 0
        self._hash = sha256()

    def read(self, size: int = -1) -> bytes:
        chunk = self._stream.read(size)
        if not isinstance(chunk, bytes):
            raise ValidationError("stream.read() must return bytes")
        self.bytes_read += len(chunk)
        self._hash.update(chunk)
        return chunk

    def hexdigest(self) -> str:
        return self._hash.hexdigest()


class UploadService:
    """Owns upload, streaming, rollback, and idempotency behavior."""

    def __init__(self, *, metadata_store: MetadataStore, object_store: ObjectStore,
                 logger: logging.Logger, id_generator: Callable[[], str],
                 metadata_validator: MetadataValidator, max_file_size: int | None,
                 operation_store: UploadOperationStore | None,
                 get_internal_metadata: Callable[[str], DocumentMetadata],
                 stream_upload: Callable[[UploadDocumentStreamRequest], UploadDocumentResult],
                 spool_factory: Callable[..., Any] = SpooledTemporaryFile) -> None:
        self._metadata_store = metadata_store
        self._object_store = object_store
        self._logger = logger
        self._id_generator = id_generator
        self._metadata_validator = metadata_validator
        self._max_file_size = max_file_size
        self._operation_store = operation_store
        self._get_internal_metadata = get_internal_metadata
        self._stream_upload = stream_upload
        self._spool_factory = spool_factory

    def upload_document(self, request: UploadDocumentRequest) -> UploadDocumentResult:
        self._validate_common_upload_fields(request)
        request = replace(request, metadata=self._normalize_metadata(request.metadata))
        self._validate_upload_request(request)
        self._validate_file_size(len(request.content))
        checksum = sha256(request.content).hexdigest()
        return self._idempotent_upload(request, checksum, self._upload_document)

    def _upload_document(self, request: UploadDocumentRequest) -> UploadDocumentResult:
        started = perf_counter()
        self._validate_upload_request(request)
        self._validate_file_size(len(request.content))
        document_id = request.document_id or self._id_generator()
        if self._metadata_store.exists(document_id):
            self._log_warning("document.upload.duplicate", document_id=document_id, filename=request.filename)
            raise DuplicateDocumentError(f"Document already exists: {document_id}")
        checksum = request.checksum or sha256(request.content).hexdigest()
        storage_key = self._build_storage_key(document_id=document_id, filename=request.filename)
        try:
            stored_key = self._object_store.put_object(PutObjectRequest(
                document_id=document_id, storage_key=storage_key, content=request.content,
                content_type=request.content_type, filename=request.filename, checksum=checksum,
                metadata=dict(request.metadata)))
        except Exception as exc:
            self._log_exception("document.upload.storage_error", exc, document_id=document_id,
                filename=request.filename, duration_ms=(perf_counter() - started) * 1000)
            raise StorageError(f"Failed to store document content for {document_id}") from exc
        try:
            saved = self._save_uploaded_metadata(request, document_id, stored_key, len(request.content), checksum)
        except Exception as exc:
            try:
                self._object_store.delete_object(document_id, stored_key)
            except Exception as cleanup_exc:
                self._log_exception("document.upload.rollback_failed", cleanup_exc,
                    document_id=document_id, storage_key=stored_key,
                    duration_ms=(perf_counter() - started) * 1000)
                raise ConsistencyError(f"Failed to persist metadata and failed to clean up content for {document_id}") from cleanup_exc
            self._log_exception("document.upload.metadata_error", exc, document_id=document_id,
                storage_key=stored_key, duration_ms=(perf_counter() - started) * 1000)
            if isinstance(exc, IntegrityError):
                raise DuplicateDocumentError(f"Document already exists: {document_id}") from exc
            raise ConsistencyError(f"Failed to persist metadata for {document_id}; object storage was rolled back") from exc
        self._log_info("document.upload.succeeded", document_id=document_id, storage_key=stored_key,
            content_type=request.content_type, file_size=len(request.content),
            duration_ms=(perf_counter() - started) * 1000)
        return UploadDocumentResult(document_id=document_id, metadata=public_metadata(saved), created=True)

    def upload_document_stream(self, request: UploadDocumentStreamRequest) -> UploadDocumentResult:
        self._validate_common_upload_fields(request)
        request = replace(request, metadata=self._normalize_metadata(request.metadata))
        self._validate_stream_upload_request(request)
        self._validate_file_size(request.size)
        if request.idempotency_key is not None and request.checksum is None:
            raise ValidationError("checksum is required for an idempotent streaming upload")
        return self._idempotent_upload(request, request.checksum or "", self._upload_document_stream)

    def _upload_document_stream(self, request: UploadDocumentStreamRequest) -> UploadDocumentResult:
        self._validate_stream_upload_request(request)
        self._validate_file_size(request.size)
        document_id = request.document_id or self._id_generator()
        if self._metadata_store.exists(document_id):
            raise DuplicateDocumentError(f"Document already exists: {document_id}")
        storage_key = self._build_storage_key(document_id=document_id, filename=request.filename)
        tracked = _HashingReader(request.stream)
        stored_key: str | None = None
        try:
            stored_key = self._object_store.put_object_stream(PutObjectStreamRequest(
                document_id=document_id, storage_key=storage_key, stream=cast(BinaryIO, tracked),
                size=request.size, chunk_size=request.chunk_size, content_type=request.content_type,
                filename=request.filename, checksum=request.checksum, metadata=dict(request.metadata)))
            if tracked.bytes_read != request.size:
                raise ValidationError(f"Stream size mismatch: declared {request.size} bytes, read {tracked.bytes_read}")
            checksum = tracked.hexdigest()
            if request.checksum is not None and checksum.lower() != request.checksum.lower():
                raise ValidationError("SHA-256 checksum mismatch")
        except ValidationError:
            if stored_key is not None:
                self._delete_uploaded_best_effort(document_id, stored_key)
            raise
        except Exception as exc:
            raise StorageError(f"Failed to store document content for {document_id}") from exc
        try:
            saved = self._save_uploaded_metadata(request, document_id, stored_key, request.size, checksum)
        except Exception as exc:
            self._delete_uploaded_best_effort(document_id, stored_key)
            if isinstance(exc, IntegrityError):
                raise DuplicateDocumentError(f"Document already exists: {document_id}") from exc
            raise ConsistencyError(f"Failed to persist metadata for {document_id}; object storage was rolled back") from exc
        return UploadDocumentResult(document_id=document_id, metadata=public_metadata(saved), created=True)

    def upload_document_unknown_size_stream(self, request: UploadDocumentUnknownSizeStreamRequest) -> UploadDocumentResult:
        self._validate_common_upload_fields(request)
        request = replace(request, metadata=self._normalize_metadata(request.metadata))
        if request.max_size <= 0:
            raise ValidationError("max_size must be positive")
        if self._max_file_size is not None and request.max_size > self._max_file_size:
            raise ValidationError("max_size exceeds configured max_file_size")
        if request.chunk_size <= 0 or request.chunk_size > _MAX_STREAM_CHUNK_SIZE:
            raise ValidationError("chunk_size must be between 1 and 1048576")
        if not hasattr(request.stream, "read"):
            raise ValidationError("stream must be a readable binary file")
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
                    raise PayloadTooLargeError("stream exceeds max_size")
                digest.update(chunk)
                spool.write(chunk)
            spool.seek(0)
            return self._stream_upload(UploadDocumentStreamRequest(
                stream=cast(BinaryIO, spool), size=size, filename=request.filename,
                content_type=request.content_type, document_id=request.document_id,
                metadata=dict(request.metadata), created_by=request.created_by,
                checksum=digest.hexdigest(), chunk_size=request.chunk_size,
                idempotency_key=request.idempotency_key, idempotency_scope=request.idempotency_scope))

    async def upload_document_async_stream(
        self, request: AsyncUploadDocumentStreamRequest,
    ) -> UploadDocumentResult:
        self._validate_common_upload_fields(request)
        request = replace(request, metadata=self._normalize_metadata(request.metadata))
        if request.size <= 0:
            raise ValidationError("size must be positive")
        if request.chunk_size <= 0 or request.chunk_size > _MAX_STREAM_CHUNK_SIZE:
            raise ValidationError("chunk_size must be between 1 and 1048576")
        self._validate_file_size(request.size)
        return await self._spool_async_stream(request, exact_size=request.size, max_size=request.size)

    async def upload_document_async_unknown_size_stream(
        self, request: AsyncUploadDocumentUnknownSizeStreamRequest,
    ) -> UploadDocumentResult:
        self._validate_common_upload_fields(request)
        request = replace(request, metadata=self._normalize_metadata(request.metadata))
        if request.max_size <= 0:
            raise ValidationError("max_size must be positive")
        if request.chunk_size <= 0 or request.chunk_size > _MAX_STREAM_CHUNK_SIZE:
            raise ValidationError("chunk_size must be between 1 and 1048576")
        if self._max_file_size is not None and request.max_size > self._max_file_size:
            raise ValidationError("max_size exceeds configured max_file_size")
        return await self._spool_async_stream(request, exact_size=None, max_size=request.max_size)

    async def _spool_async_stream(
        self,
        request: AsyncUploadDocumentStreamRequest | AsyncUploadDocumentUnknownSizeStreamRequest,
        *,
        exact_size: int | None,
        max_size: int,
    ) -> UploadDocumentResult:
        size = 0
        digest = sha256()
        with self._spool_factory(max_size=_UNKNOWN_SIZE_SPOOL_MEMORY_LIMIT, mode="w+b") as spool:
            while True:
                chunk = await request.stream.read(request.chunk_size)
                if not isinstance(chunk, bytes):
                    raise ValidationError("stream.read() must return bytes")
                if not chunk:
                    break
                size += len(chunk)
                if size > max_size:
                    raise PayloadTooLargeError("stream exceeds max_size")
                digest.update(chunk)
                await asyncio.to_thread(spool.write, chunk)
            if exact_size is not None and size != exact_size:
                raise ValidationError(
                    f"Stream size mismatch: declared {exact_size} bytes, read {size}"
                )
            checksum = digest.hexdigest()
            supplied_checksum = getattr(request, "checksum", None)
            if supplied_checksum is not None and checksum.lower() != supplied_checksum.lower():
                raise ValidationError("SHA-256 checksum mismatch")
            await asyncio.to_thread(spool.seek, 0)
            sync_request = UploadDocumentStreamRequest(
                stream=cast(BinaryIO, spool), size=size, filename=request.filename,
                content_type=request.content_type, document_id=request.document_id,
                metadata=dict(request.metadata), created_by=request.created_by, checksum=checksum,
                chunk_size=request.chunk_size, idempotency_key=request.idempotency_key,
                idempotency_scope=request.idempotency_scope,
            )
            upload_task = asyncio.create_task(
                asyncio.to_thread(self.upload_document_stream, sync_request)
            )
            try:
                return await asyncio.shield(upload_task)
            except asyncio.CancelledError:
                await upload_task
                raise

    def get_upload_operation(self, *, scope: str, idempotency_key: str) -> UploadOperationResult:
        if not scope.strip() or not idempotency_key.strip():
            raise ValidationError("scope and idempotency_key must not be empty")
        if self._operation_store is None:
            raise ValidationError("upload operation reads require a persistent operation store")
        try:
            operation = self._operation_store.get(scope=scope, idempotency_key=idempotency_key)
        except LookupError as exc:
            raise UploadOperationNotFoundError(f"Upload operation not found for scope {scope!r} and key {idempotency_key!r}") from exc
        except Exception as exc:
            raise MetadataStoreError("Failed to load upload operation") from exc
        return UploadOperationResult(scope=operation.scope, idempotency_key=operation.idempotency_key,
            document_id=operation.document_id, state=operation.state, created_at=operation.created_at,
            updated_at=operation.updated_at)

    def _normalize_metadata(self, metadata: Mapping[str, object]) -> dict[str, object]:
        try:
            return self._metadata_validator(metadata)
        except ValidationError:
            raise
        except Exception as exc:
            raise ValidationError(f"Invalid document metadata: {exc}") from exc

    def _idempotent_upload(self, request: object, checksum: str,
                           upload: Callable[[Any], UploadDocumentResult]) -> UploadDocumentResult:
        key = getattr(request, "idempotency_key")
        if key is None:
            return upload(request)
        if not key.strip():
            raise ValidationError("idempotency_key must not be empty")
        if self._operation_store is None:
            raise ValidationError("idempotency requires a persistent operation store")
        scope = getattr(request, "idempotency_scope", None)
        if scope is not None and not scope.strip():
            raise ValidationError("idempotency_scope must not be empty")
        if scope is None:
            raise ValidationError(
                "idempotency_scope is required when idempotency_key is used"
            )
        fingerprint = build_upload_fingerprint(checksum=checksum, filename=getattr(request, "filename"),
            content_type=getattr(request, "content_type"), size=getattr(request, "size", len(getattr(request, "content", b""))),
            document_id=getattr(request, "document_id"), metadata=getattr(request, "metadata"))
        generated_id = getattr(request, "document_id") or self._id_generator()
        claim = self._operation_store.claim(scope=scope, idempotency_key=key,
            fingerprint=fingerprint, document_id=generated_id)
        if not claim.claimed:
            if claim.operation.state is UploadOperationState.PENDING:
                raise IdempotencyInProgressError("Upload with this idempotency key is in progress")
            metadata = self._get_internal_metadata(claim.operation.document_id)
            return UploadDocumentResult(document_id=metadata.document_id, metadata=public_metadata(metadata), created=False)
        try:
            result = upload(replace(request, document_id=claim.operation.document_id))
            self._operation_store.mark_succeeded(scope=scope, idempotency_key=key)
            return result
        except Exception:
            try:
                self._operation_store.mark_failed(scope=scope, idempotency_key=key)
            except Exception:
                self._logger.exception("upload idempotency failure state could not be persisted")
            raise

    def _save_uploaded_metadata(self, request: UploadDocumentRequest | UploadDocumentStreamRequest,
                                document_id: str, storage_key: str, file_size: int,
                                checksum: str) -> DocumentMetadata:
        now = datetime.now(UTC)
        return self._metadata_store.save_metadata(DocumentMetadata(document_id=document_id,
            original_filename=request.filename, content_type=request.content_type, file_size=file_size,
            storage_key=storage_key, checksum=checksum, status=DocumentStatus.AVAILABLE,
            created_at=now, updated_at=now, created_by=request.created_by,
            extra_metadata=dict(request.metadata)))

    def _validate_file_size(self, size: int) -> None:
        if self._max_file_size is not None and size > self._max_file_size:
            raise PayloadTooLargeError(f"Document size exceeds maximum of {self._max_file_size} bytes")

    def _delete_uploaded_best_effort(self, document_id: str, storage_key: str) -> None:
        try:
            self._object_store.delete_object(document_id, storage_key)
        except Exception as exc:
            raise ConsistencyError(f"Failed to roll back object content for {document_id}") from exc

    @classmethod
    def _validate_stream_upload_request(cls, request: UploadDocumentStreamRequest) -> None:
        if request.size <= 0:
            raise ValidationError("size must be positive")
        if request.chunk_size <= 0:
            raise ValidationError("chunk_size must be positive")
        if not hasattr(request.stream, "read"):
            raise ValidationError("stream must be a readable binary file")
        cls._validate_upload_fields(request.filename, request.content_type)

    @classmethod
    def _validate_common_upload_fields(cls, request: object) -> None:
        filename = getattr(request, "filename", None)
        content_type = getattr(request, "content_type", None)
        if not isinstance(filename, str):
            raise ValidationError("filename must be a string")
        if not isinstance(content_type, str):
            raise ValidationError("content_type must be a string")
        cls._validate_upload_fields(filename, content_type)
        for field_name in ("document_id", "created_by", "idempotency_key", "idempotency_scope"):
            value = getattr(request, field_name, None)
            if value is not None and not isinstance(value, str):
                raise ValidationError(f"{field_name} must be a string")
            if value is not None and not value.strip():
                raise ValidationError(f"{field_name} must not be empty")
        metadata = getattr(request, "metadata", None)
        if not isinstance(metadata, Mapping):
            raise ValidationError("metadata must be a mapping")

    @classmethod
    def _validate_upload_request(cls, request: UploadDocumentRequest) -> None:
        if not request.content:
            raise ValidationError("Document content must not be empty")
        cls._validate_upload_fields(request.filename, request.content_type)

    @classmethod
    def _validate_upload_fields(cls, filename: str, content_type: str) -> None:
        if not filename.strip():
            raise ValidationError("filename must not be empty")
        if not content_type.strip():
            raise ValidationError("content_type must not be empty")
        if cls._sanitize_filename(filename) in {".", ""}:
            raise ValidationError("filename must not normalize to '.' or empty")

    @classmethod
    def _build_storage_key(cls, *, document_id: str, filename: str) -> str:
        return f"documents/{document_id}/{cls._sanitize_filename(filename)}"

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        return filename.strip().replace("..", ".").replace("/", "-").replace("\\", "-")

    def _log_info(self, event: str, **context: object) -> None:
        self._logger.info(event, extra=self._build_log_extra(event, context))

    def _log_warning(self, event: str, **context: object) -> None:
        self._logger.warning(event, extra=self._build_log_extra(event, context))

    def _log_exception(self, event: str, exc: Exception, **context: object) -> None:
        self._logger.exception(event, extra=self._build_log_extra(event, {**context, "error_type": type(exc).__name__}))

    @staticmethod
    def _build_log_extra(event: str, context: Mapping[str, object]) -> dict[str, object]:
        return {"dms_event": event, **{f"dms_{key}": value for key, value in context.items()}}
