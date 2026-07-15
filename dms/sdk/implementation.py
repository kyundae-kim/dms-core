from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from time import perf_counter
from typing import BinaryIO, TypeAlias, cast
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from dms.domain.interfaces import MetadataStore, ObjectStore, PutObjectRequest, PutObjectStreamRequest, UploadOperationStore
from dms.domain.models import DocumentMetadata, DocumentStatus, UploadOperationState
from dms.sdk.errors import (
    ConsistencyError,
    DmsError,
    DocumentNotFoundError,
    DuplicateDocumentError,
    MetadataStoreError,
    IdempotencyInProgressError,
    StorageError,
    ValidationError,
)
from dms.sdk.types import (
    BatchReconciliationResult,
    DeleteDocumentResult,
    DocumentContent,
    DocumentContentStream,
    DocumentInspection,
    HealthStatus,
    ReconciliationResult,
    RecoveryAction,
    RecoveryIssue,
    ServiceHealth,
    UploadDocumentRequest,
    UploadDocumentStreamRequest,
    UploadDocumentResult,
)
from dms.sdk.metadata import DefaultMetadataPolicy, MetadataValidator


DocumentIdGenerator: TypeAlias = Callable[[], str]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _new_document_id() -> str:
    return str(uuid4())


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


class DefaultDocumentManagementSDK:
    def __init__(
        self,
        *,
        metadata_store: MetadataStore,
        object_store: ObjectStore,
        logger: logging.Logger | None = None,
        id_generator: DocumentIdGenerator | None = None,
        service_checks: Mapping[str, Callable[[], object]] | None = None,
        close_callbacks: Iterable[Callable[[], object]] | None = None,
        max_file_size: int | None = None,
        operation_store: UploadOperationStore | None = None,
        metadata_validator: MetadataValidator | None = None,
    ) -> None:
        self._metadata_store = metadata_store
        self._object_store = object_store
        self._logger = logger or logging.getLogger("dms.sdk")
        self._id_generator = id_generator or _new_document_id
        self._service_checks = dict(service_checks or {})
        self._close_callbacks = list(close_callbacks or [])
        self._closed = False
        if max_file_size is not None and max_file_size <= 0:
            raise ValidationError("max_file_size must be positive")
        self._max_file_size = max_file_size
        self._operation_store = operation_store
        self._metadata_validator = metadata_validator or DefaultMetadataPolicy()

    def __enter__(self) -> DefaultDocumentManagementSDK:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()

    def upload_document(self, request: UploadDocumentRequest) -> UploadDocumentResult:
        request = replace(request, metadata=self._normalize_metadata(request.metadata))
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
        put_request = PutObjectRequest(
            document_id=document_id,
            storage_key=storage_key,
            content=request.content,
            content_type=request.content_type,
            filename=request.filename,
            checksum=checksum,
            metadata=dict(request.metadata),
        )

        try:
            stored_key = self._object_store.put_object(put_request)
        except Exception as exc:  # pragma: no cover - protocol adapter boundary
            self._log_exception(
                "document.upload.storage_error",
                exc,
                document_id=document_id,
                filename=request.filename,
                duration_ms=(perf_counter() - started) * 1000,
            )
            raise StorageError(f"Failed to store document content for {document_id}") from exc

        try:
            saved_metadata = self._save_uploaded_metadata(
                request, document_id, stored_key, len(request.content), checksum
            )
        except Exception as exc:
            try:
                self._object_store.delete_object(document_id, stored_key)
            except Exception as cleanup_exc:  # pragma: no cover - rare double-failure boundary
                self._log_exception(
                    "document.upload.rollback_failed",
                    cleanup_exc,
                    document_id=document_id,
                    storage_key=stored_key,
                    duration_ms=(perf_counter() - started) * 1000,
                )
                raise ConsistencyError(
                    f"Failed to persist metadata and failed to clean up content for {document_id}"
                ) from cleanup_exc
            self._log_exception(
                "document.upload.metadata_error",
                exc,
                document_id=document_id,
                storage_key=stored_key,
                duration_ms=(perf_counter() - started) * 1000,
            )
            if isinstance(exc, IntegrityError):
                raise DuplicateDocumentError(f"Document already exists: {document_id}") from exc
            raise ConsistencyError(f"Failed to persist metadata for {document_id}; object storage was rolled back") from exc

        self._log_info(
            "document.upload.succeeded",
            document_id=document_id,
            storage_key=stored_key,
            content_type=request.content_type,
            file_size=len(request.content),
            duration_ms=(perf_counter() - started) * 1000,
        )
        return UploadDocumentResult(
            document_id=document_id,
            storage_key=stored_key,
            metadata=saved_metadata,
            created=True,
        )

    def upload_document_stream(self, request: UploadDocumentStreamRequest) -> UploadDocumentResult:
        request = replace(request, metadata=self._normalize_metadata(request.metadata))
        if request.idempotency_key is not None and request.checksum is None:
            raise ValidationError("checksum is required for an idempotent streaming upload")
        return self._idempotent_upload(
            request, request.checksum or "", self._upload_document_stream
        )

    def _normalize_metadata(self, metadata: Mapping[str, object]) -> dict[str, object]:
        try:
            return self._metadata_validator(metadata)
        except ValidationError:
            raise
        except Exception as exc:
            raise ValidationError(f"Invalid document metadata: {exc}") from exc

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
                size=request.size, chunk_size=request.chunk_size,
                content_type=request.content_type, filename=request.filename,
                checksum=request.checksum, metadata=dict(request.metadata),
            ))
            if tracked.bytes_read != request.size:
                raise ValidationError(
                    f"Stream size mismatch: declared {request.size} bytes, read {tracked.bytes_read}"
                )
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
            saved = self._save_uploaded_metadata(
                request, document_id, stored_key, request.size, checksum
            )
        except Exception as exc:
            self._delete_uploaded_best_effort(document_id, stored_key)
            if isinstance(exc, IntegrityError):
                raise DuplicateDocumentError(f"Document already exists: {document_id}") from exc
            raise ConsistencyError(
                f"Failed to persist metadata for {document_id}; object storage was rolled back"
            ) from exc
        return UploadDocumentResult(document_id=document_id, storage_key=stored_key,
                                    metadata=saved, created=True)

    def _save_uploaded_metadata(
        self,
        request: UploadDocumentRequest | UploadDocumentStreamRequest,
        document_id: str,
        storage_key: str,
        file_size: int,
        checksum: str,
    ) -> DocumentMetadata:
        now = _utcnow()
        return self._metadata_store.save_metadata(DocumentMetadata(
            document_id=document_id,
            original_filename=request.filename,
            content_type=request.content_type,
            file_size=file_size,
            storage_key=storage_key,
            checksum=checksum,
            status=DocumentStatus.AVAILABLE,
            created_at=now,
            updated_at=now,
            created_by=request.created_by,
            extra_metadata=dict(request.metadata),
        ))

    def _idempotent_upload(self, request: object, checksum: str, upload: Callable[[object], UploadDocumentResult]) -> UploadDocumentResult:
        key = getattr(request, "idempotency_key")
        if key is None:
            return upload(request)
        if not key.strip():
            raise ValidationError("idempotency_key must not be empty")
        if self._operation_store is None:
            raise ValidationError("idempotency requires a persistent operation store")
        scope = getattr(request, "created_by") or "anonymous"
        payload = {
            "checksum": checksum.lower(), "filename": getattr(request, "filename"),
            "content_type": getattr(request, "content_type"),
            "size": getattr(request, "size", len(getattr(request, "content", b""))),
            "document_id": getattr(request, "document_id"),
            "metadata": getattr(request, "metadata"),
        }
        fingerprint = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                           default=str).encode()).hexdigest()
        generated_id = getattr(request, "document_id") or self._id_generator()
        claim = self._operation_store.claim(scope=scope, idempotency_key=key,
                                            fingerprint=fingerprint, document_id=generated_id)
        if not claim.claimed:
            if claim.operation.state is UploadOperationState.PENDING:
                raise IdempotencyInProgressError("Upload with this idempotency key is in progress")
            metadata = self.get_document_metadata(claim.operation.document_id)
            return UploadDocumentResult(document_id=metadata.document_id,
                storage_key=metadata.storage_key, metadata=metadata, created=False)
        claimed_request = replace(request, document_id=claim.operation.document_id)
        try:
            result = upload(claimed_request)
            self._operation_store.mark_succeeded(scope=scope, idempotency_key=key)
            return result
        except Exception:
            try:
                self._operation_store.mark_failed(scope=scope, idempotency_key=key)
            except Exception:
                self._logger.exception("upload idempotency failure state could not be persisted")
            raise

    def get_document_metadata(self, document_id: str) -> DocumentMetadata:
        try:
            metadata = self._metadata_store.get_metadata(document_id)
        except LookupError as exc:
            self._log_warning("document.metadata.not_found", document_id=document_id)
            raise DocumentNotFoundError(f"Document not found: {document_id}") from exc
        except Exception as exc:
            self._log_exception("document.metadata.backend_error", exc, document_id=document_id)
            raise MetadataStoreError(f"Failed to load metadata for {document_id}") from exc
        self._log_info(
            "document.metadata.succeeded",
            document_id=document_id,
            status=metadata.status.value,
        )
        return metadata

    def list_documents(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
        status: DocumentStatus | None = None,
    ) -> list[DocumentMetadata]:
        if offset < 0:
            raise ValidationError("offset must not be negative")
        if limit <= 0:
            raise ValidationError("limit must be positive")

        try:
            metadata = self._metadata_store.list_metadata(offset=offset, limit=limit, status=status)
        except Exception as exc:
            self._log_exception(
                "document.list.backend_error",
                exc,
                offset=offset,
                limit=limit,
                status=status.value if status is not None else None,
            )
            raise MetadataStoreError("Failed to list document metadata") from exc
        self._log_info(
            "document.list.succeeded",
            offset=offset,
            limit=limit,
            status=status.value if status is not None else None,
            result_count=len(metadata),
        )
        return metadata

    def inspect_document(self, document_id: str) -> DocumentInspection:
        """Inspect consistency; missing metadata is a result, not a not-found error."""
        try:
            metadata = self._metadata_store.get_metadata(document_id)
        except LookupError:
            return DocumentInspection(document_id=document_id, metadata_exists=False,
                object_exists=None, status=None, consistent=False,
                issue=RecoveryIssue.METADATA_MISSING, storage_key=None)
        except Exception as exc:
            raise MetadataStoreError(f"Failed to load metadata for {document_id}") from exc
        try:
            object_exists = self._object_store.object_exists(document_id, metadata.storage_key)
        except Exception as exc:
            raise StorageError(f"Failed to inspect document content for {document_id}") from exc
        if metadata.status is DocumentStatus.DELETED and not object_exists:
            consistent, issue = True, RecoveryIssue.NONE
        elif not object_exists:
            consistent, issue = False, RecoveryIssue.OBJECT_MISSING
        elif metadata.status is DocumentStatus.DELETING:
            consistent, issue = False, RecoveryIssue.DELETION_INCOMPLETE
        elif metadata.status is DocumentStatus.FAILED:
            consistent, issue = False, RecoveryIssue.FAILED_STATUS
        else:
            consistent, issue = True, RecoveryIssue.NONE
        return DocumentInspection(document_id=document_id, metadata_exists=True,
            object_exists=object_exists, status=metadata.status, consistent=consistent,
            issue=issue, storage_key=metadata.storage_key)

    def list_recovery_candidates(self, *, status: DocumentStatus,
                                 offset: int = 0, limit: int = 100) -> list[DocumentMetadata]:
        self._validate_recovery_page(status=status, offset=offset, limit=limit)
        return self.list_documents(offset=offset, limit=limit, status=status)

    def reconcile_document(self, document_id: str, action: RecoveryAction, *,
                           storage_key: str | None = None,
                           dry_run: bool = False) -> ReconciliationResult:
        if not isinstance(action, RecoveryAction):
            raise ValidationError("action must be a RecoveryAction")
        inspection = self.inspect_document(document_id)
        if action is RecoveryAction.PURGE_ORPHAN_OBJECT:
            if inspection.metadata_exists:
                raise ValidationError("orphan purge requires absent metadata")
            if storage_key is None or not storage_key.strip():
                raise ValidationError("storage_key is required for orphan purge")
            try:
                exists = self._object_store.object_exists(document_id, storage_key)
            except Exception as exc:
                raise StorageError(f"Failed to inspect orphan object for {document_id}") from exc
            if not exists:
                raise ValidationError("orphan purge requires an existing object at the supplied storage_key")
            if not dry_run:
                try:
                    self._object_store.delete_object(document_id, storage_key)
                except Exception as exc:
                    raise StorageError(f"Failed to purge orphan object for {document_id}") from exc
            return ReconciliationResult(document_id=document_id, action=action,
                applied=not dry_run, inspection=self.inspect_document(document_id))

        if not inspection.metadata_exists:
            raise ValidationError("reconciliation action requires existing metadata")
        if action in (RecoveryAction.COMPLETE_DELETION_SOFT,
                      RecoveryAction.COMPLETE_DELETION_HARD):
            if inspection.status is not DocumentStatus.DELETING or inspection.object_exists is not False:
                raise ValidationError("completion requires DELETING metadata and an absent object")
            if not dry_run:
                try:
                    if action is RecoveryAction.COMPLETE_DELETION_HARD:
                        self._metadata_store.hard_delete(document_id)
                    else:
                        self._metadata_store.mark_deleted(document_id)
                except Exception as exc:
                    raise MetadataStoreError(f"Failed to complete deletion for {document_id}") from exc
        elif action is RecoveryAction.MARK_FAILED:
            if inspection.object_exists is not False:
                raise ValidationError("mark failed requires existing metadata and an absent object")
            if not dry_run:
                self._set_document_status(self.get_document_metadata(document_id), DocumentStatus.FAILED)
        return ReconciliationResult(document_id=document_id, action=action,
            applied=not dry_run, inspection=self.inspect_document(document_id))

    def reconcile_documents(self, *, status: DocumentStatus, action: RecoveryAction,
                            offset: int = 0, limit: int = 100,
                            dry_run: bool = False) -> BatchReconciliationResult:
        candidates = self.list_recovery_candidates(status=status, offset=offset, limit=limit)
        items: list[ReconciliationResult] = []
        for metadata in candidates:
            try:
                items.append(self.reconcile_document(metadata.document_id, action, dry_run=dry_run))
            except DmsError as exc:
                items.append(ReconciliationResult(document_id=metadata.document_id,
                    action=action, applied=False,
                    inspection=self.inspect_document(metadata.document_id),
                    error_type=type(exc).__name__, error_message=str(exc)))
        return BatchReconciliationResult(status=status, action=action, dry_run=dry_run,
            offset=offset, limit=limit, items=items)

    @staticmethod
    def _validate_recovery_page(*, status: DocumentStatus, offset: int, limit: int) -> None:
        if status not in (DocumentStatus.FAILED, DocumentStatus.DELETING):
            raise ValidationError("recovery status must be FAILED or DELETING")
        if offset < 0:
            raise ValidationError("offset must not be negative")
        if limit <= 0 or limit > 1000:
            raise ValidationError("recovery limit must be between 1 and 1000")

    def get_document_content(self, document_id: str) -> DocumentContent:
        started = perf_counter()
        metadata = self.get_document_metadata(document_id)
        try:
            stored = self._object_store.get_object(document_id, metadata.storage_key)
        except Exception as exc:
            self._log_exception(
                "document.content.missing_object",
                exc,
                document_id=document_id,
                storage_key=metadata.storage_key,
                duration_ms=(perf_counter() - started) * 1000,
            )
            raise ConsistencyError(
                f"Document metadata exists but object content is missing for {document_id}"
            ) from exc

        self._log_info(
            "document.content.succeeded",
            document_id=document_id,
            storage_key=metadata.storage_key,
            file_size=stored.size,
            duration_ms=(perf_counter() - started) * 1000,
        )
        return DocumentContent(
            document_id=document_id,
            content=stored.content,
            content_type=stored.content_type,
            filename=stored.filename,
            size=stored.size,
            checksum=stored.checksum,
        )

    def get_document_content_stream(
        self,
        document_id: str,
        *,
        chunk_size: int = 65536,
    ) -> DocumentContentStream:
        if chunk_size <= 0:
            raise ValidationError("chunk_size must be positive")

        started = perf_counter()
        metadata = self.get_document_metadata(document_id)
        try:
            stored_stream = self._object_store.get_object_stream(document_id, metadata.storage_key)
        except Exception as exc:
            self._log_exception(
                "document.content_stream.missing_object",
                exc,
                document_id=document_id,
                storage_key=metadata.storage_key,
                duration_ms=(perf_counter() - started) * 1000,
            )
            raise ConsistencyError(
                f"Document metadata exists but object content is missing for {document_id}"
            ) from exc

        def close_stream() -> None:
            if hasattr(stored_stream.stream, "close"):
                stored_stream.stream.close()
            if hasattr(stored_stream.stream, "release_conn"):
                stored_stream.stream.release_conn()

        self._log_info(
            "document.content_stream.succeeded",
            document_id=document_id,
            storage_key=metadata.storage_key,
            file_size=stored_stream.size,
            chunk_size=chunk_size,
            duration_ms=(perf_counter() - started) * 1000,
        )
        return DocumentContentStream(
            document_id=document_id,
            stream=stored_stream.stream,
            content_type=stored_stream.content_type,
            filename=stored_stream.filename,
            size=stored_stream.size,
            checksum=stored_stream.checksum,
            chunk_size=chunk_size,
            _close_callback=close_stream,
        )

    def delete_document(
        self,
        document_id: str,
        *,
        hard_delete: bool = False,
    ) -> DeleteDocumentResult:
        started = perf_counter()
        metadata = self.get_document_metadata(document_id)
        deleting_metadata = self._set_document_status(metadata, DocumentStatus.DELETING)

        try:
            self._object_store.delete_object(document_id, metadata.storage_key)
        except Exception as exc:
            self._set_document_status_best_effort(deleting_metadata, DocumentStatus.FAILED)
            self._log_exception(
                "document.delete.storage_error",
                exc,
                document_id=document_id,
                storage_key=metadata.storage_key,
                hard_delete=hard_delete,
                duration_ms=(perf_counter() - started) * 1000,
            )
            raise StorageError(f"Failed to delete document content for {document_id}") from exc

        try:
            if hard_delete:
                self._metadata_store.hard_delete(document_id)
                status = DocumentStatus.DELETED
            else:
                status = self._metadata_store.mark_deleted(document_id).status
        except Exception as exc:
            self._log_exception(
                "document.delete.metadata_error",
                exc,
                document_id=document_id,
                storage_key=metadata.storage_key,
                hard_delete=hard_delete,
                persisted_status=deleting_metadata.status.value,
                duration_ms=(perf_counter() - started) * 1000,
            )
            operation = "hard deleted" if hard_delete else "marked deleted"
            raise ConsistencyError(
                f"Document content was deleted but metadata could not be {operation} for {document_id}"
            ) from exc
        self._log_info(
            "document.delete.succeeded",
            document_id=document_id,
            hard_delete=hard_delete,
            status=status.value,
            duration_ms=(perf_counter() - started) * 1000,
        )
        return DeleteDocumentResult(
            document_id=document_id,
            deleted=True,
            hard_deleted=hard_delete,
            status=status,
        )

    def check_health(self) -> HealthStatus:
        services: list[ServiceHealth] = []
        overall_ok = True
        for name, check in self._service_checks.items():
            started = perf_counter()
            try:
                check()
            except Exception as exc:
                overall_ok = False
                services.append(
                    ServiceHealth(
                        service=name,
                        ok=False,
                        latency_ms=(perf_counter() - started) * 1000,
                        error=str(exc),
                    )
                )
            else:
                services.append(
                    ServiceHealth(
                        service=name,
                        ok=True,
                        latency_ms=(perf_counter() - started) * 1000,
                        error=None,
                    )
                )

        health = HealthStatus(ok=overall_ok, services=services, checked_at=_utcnow())
        self._log_info(
            "sdk.health.checked",
            ok=overall_ok,
            service_count=len(services),
            failed_services=[service.service for service in services if not service.ok],
        )
        return health

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        errors: list[Exception] = []
        for callback in self._close_callbacks:
            try:
                callback()
            except Exception as exc:  # pragma: no cover - cleanup boundary
                errors.append(exc)
        if errors:
            self._log_exception("sdk.close.failed", errors[0], callback_count=len(self._close_callbacks))
            raise MetadataStoreError("One or more cleanup callbacks failed") from errors[0]
        self._log_info("sdk.close.succeeded", callback_count=len(self._close_callbacks))

    def _set_document_status(
        self,
        metadata: DocumentMetadata,
        status: DocumentStatus,
    ) -> DocumentMetadata:
        updated_metadata = replace(
            metadata,
            status=status,
            updated_at=_utcnow(),
            deleted_at=metadata.deleted_at if status != DocumentStatus.DELETED else _utcnow(),
        )
        try:
            return self._metadata_store.update_metadata(updated_metadata)
        except Exception as exc:
            self._log_exception(
                "document.status_update.failed",
                exc,
                document_id=metadata.document_id,
                storage_key=metadata.storage_key,
                target_status=status.value,
            )
            raise MetadataStoreError(
                f"Failed to persist document status '{status.value}' for {metadata.document_id}"
            ) from exc

    def _set_document_status_best_effort(
        self,
        metadata: DocumentMetadata,
        status: DocumentStatus,
    ) -> None:
        try:
            self._set_document_status(metadata, status)
        except MetadataStoreError:
            return

    def _log_info(self, event: str, **context: object) -> None:
        self._logger.info(event, extra=self._build_log_extra(event, context))

    def _log_warning(self, event: str, **context: object) -> None:
        self._logger.warning(event, extra=self._build_log_extra(event, context))

    def _log_exception(self, event: str, exc: Exception, **context: object) -> None:
        self._logger.exception(
            event,
            extra=self._build_log_extra(event, {**context, "error_type": type(exc).__name__}),
        )

    @staticmethod
    def _build_log_extra(event: str, context: Mapping[str, object]) -> dict[str, object]:
        extra: dict[str, object] = {"dms_event": event}
        for key, value in context.items():
            extra[f"dms_{key}"] = value
        return extra

    def _validate_file_size(self, size: int) -> None:
        if self._max_file_size is not None and size > self._max_file_size:
            raise ValidationError(f"Document size exceeds maximum of {self._max_file_size} bytes")

    def _delete_uploaded_best_effort(self, document_id: str, storage_key: str) -> None:
        try:
            self._object_store.delete_object(document_id, storage_key)
        except Exception as exc:
            raise ConsistencyError(
                f"Failed to roll back object content for {document_id}"
            ) from exc

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
        safe_filename = cls._sanitize_filename(filename)
        return f"documents/{document_id}/{safe_filename}"

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        return filename.strip().replace('..', '.').replace('/', '-').replace('\\', '-')
