from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from time import perf_counter
from typing import BinaryIO, cast

from dms.domain.interfaces import (
    MetadataConflictError,
    MetadataStore,
    ObjectStore,
    PutObjectRequest,
    PutObjectStreamRequest,
    UploadOperationStore,
)
from dms.domain.models import DocumentMetadata, DocumentStatus, UploadOperationState
from dms.sdk.errors import (
    ConsistencyError,
    DuplicateDocumentError,
    IdempotencyInProgressError,
    MetadataStoreError,
    PayloadTooLargeError,
    StorageError,
    UploadOperationNotFoundError,
    ValidationError,
)
from dms.sdk.idempotency import build_upload_fingerprint
from dms.sdk.observability import _LoggingMixin
from dms.sdk.types import (
    UploadDocumentRequest,
    UploadDocumentResult,
    UploadDocumentStreamRequest,
    UploadOperationResult,
    public_metadata,
)

_STREAM_CHUNK_SIZE = 65536


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


class UploadService(_LoggingMixin):
    """Owns upload, streaming, rollback, and idempotency behavior."""

    def __init__(self, *, metadata_store: MetadataStore, object_store: ObjectStore,
                 logger: logging.Logger,
                 max_file_size: int | None,
                 operation_store: UploadOperationStore | None,
                 get_internal_metadata: Callable[[str], DocumentMetadata]) -> None:
        self._metadata_store = metadata_store
        self._object_store = object_store
        self._logger = logger
        self._max_file_size = max_file_size
        self._operation_store = operation_store
        self._get_internal_metadata = get_internal_metadata

    def upload_document(self, request: UploadDocumentRequest) -> UploadDocumentResult:
        self._validate_common_upload_fields(request)
        self._validate_upload_request(request)
        self._validate_file_size(len(request.content))
        checksum = sha256(request.content).hexdigest()
        return self._idempotent_upload(request, checksum)

    def _upload_document(self, request: UploadDocumentRequest) -> UploadDocumentResult:
        started = perf_counter()
        document_id = request.document_id or self._allocate_document_id()
        if self._metadata_store.exists(document_id):
            self._log_warning("document.upload.duplicate", document_id=document_id, filename=request.filename)
            raise DuplicateDocumentError(f"Document already exists: {document_id}")
        checksum = request.checksum or sha256(request.content).hexdigest()
        storage_key = self._build_storage_key(document_id=document_id, filename=request.filename)
        try:
            stored_key = self._object_store.put_object(PutObjectRequest(
                document_id=document_id, storage_key=storage_key, content=request.content,
                content_type=request.content_type, filename=request.filename, checksum=checksum,
                metadata=request.metadata))
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
            if isinstance(exc, MetadataConflictError):
                raise DuplicateDocumentError(f"Document already exists: {document_id}") from exc
            raise ConsistencyError(f"Failed to persist metadata for {document_id}; object storage was rolled back") from exc
        self._log_info("document.upload.succeeded", document_id=document_id, storage_key=stored_key,
            content_type=request.content_type, file_size=len(request.content),
            duration_ms=(perf_counter() - started) * 1000)
        return UploadDocumentResult(document_id=document_id, metadata=public_metadata(saved), created=True)

    def upload_document_stream(self, request: UploadDocumentStreamRequest) -> UploadDocumentResult:
        self._validate_common_upload_fields(request)
        self._validate_stream_upload_request(request)
        self._validate_file_size(request.size)
        return self._upload_document_stream(request)

    def _upload_document_stream(self, request: UploadDocumentStreamRequest) -> UploadDocumentResult:
        document_id = request.document_id or self._allocate_document_id()
        if self._metadata_store.exists(document_id):
            raise DuplicateDocumentError(f"Document already exists: {document_id}")
        storage_key = self._build_storage_key(document_id=document_id, filename=request.filename)
        tracked = _HashingReader(request.stream)
        stored_key: str | None = None
        try:
            stored_key = self._object_store.put_object_stream(PutObjectStreamRequest(
                document_id=document_id, storage_key=storage_key, stream=cast(BinaryIO, tracked),
                size=request.size, chunk_size=_STREAM_CHUNK_SIZE, content_type=request.content_type,
                filename=request.filename, metadata=request.metadata))
            if tracked.bytes_read != request.size:
                raise ValidationError(f"Stream size mismatch: declared {request.size} bytes, read {tracked.bytes_read}")
            checksum = tracked.hexdigest()
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
            if isinstance(exc, MetadataConflictError):
                raise DuplicateDocumentError(f"Document already exists: {document_id}") from exc
            raise ConsistencyError(f"Failed to persist metadata for {document_id}; object storage was rolled back") from exc
        return UploadDocumentResult(document_id=document_id, metadata=public_metadata(saved), created=True)


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

    def _idempotent_upload(
        self,
        request: UploadDocumentRequest,
        checksum: str,
    ) -> UploadDocumentResult:
        key = request.idempotency_key
        if key is None:
            return self._upload_document(request)
        if not key.strip():
            raise ValidationError("idempotency_key must not be empty")
        if self._operation_store is None:
            raise ValidationError("idempotency requires a persistent operation store")
        scope = request.idempotency_scope
        if scope is not None and not scope.strip():
            raise ValidationError("idempotency_scope must not be empty")
        if scope is None:
            raise ValidationError(
                "idempotency_scope is required when idempotency_key is used"
            )
        fingerprint = build_upload_fingerprint(
            checksum=checksum,
            filename=request.filename,
            content_type=request.content_type,
            size=len(request.content),
            document_id=request.document_id,
        )
        generated_id = request.document_id or self._allocate_document_id()
        claim = self._operation_store.claim(
            scope=scope,
            idempotency_key=key,
            fingerprint=fingerprint,
            document_id=generated_id,
        )
        if not claim.claimed:
            if claim.operation.state is UploadOperationState.PENDING:
                raise IdempotencyInProgressError("Upload with this idempotency key is in progress")
            metadata = self._get_internal_metadata(claim.operation.document_id)
            return UploadDocumentResult(document_id=metadata.document_id, metadata=public_metadata(metadata), created=False)
        try:
            result = self._upload_document(
                replace(request, document_id=claim.operation.document_id)
            )
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
            extra_metadata=request.metadata if request.metadata is not None else {}))

    def _validate_file_size(self, size: int) -> None:
        if self._max_file_size is not None and size > self._max_file_size:
            raise PayloadTooLargeError(f"Document size exceeds maximum of {self._max_file_size} bytes")

    def _allocate_document_id(self) -> str:
        try:
            document_id = self._metadata_store.allocate_document_id()
        except Exception as exc:
            raise MetadataStoreError("Failed to allocate a document identifier") from exc
        if not isinstance(document_id, str) or not document_id.strip():
            raise MetadataStoreError("Metadata store returned an invalid document identifier")
        return document_id


    def _delete_uploaded_best_effort(self, document_id: str, storage_key: str) -> None:
        try:
            self._object_store.delete_object(document_id, storage_key)
        except Exception as exc:
            raise ConsistencyError(f"Failed to roll back object content for {document_id}") from exc

    @classmethod
    def _validate_stream_upload_request(cls, request: UploadDocumentStreamRequest) -> None:
        if request.size <= 0:
            raise ValidationError("size must be positive")
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
