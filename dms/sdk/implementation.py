from __future__ import annotations

import asyncio
import logging

from tempfile import SpooledTemporaryFile
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from time import perf_counter
from typing import TypeAlias
from uuid import uuid4

from dms.domain.interfaces import MetadataStore, ObjectStore, UploadOperationStore
from dms.domain.models import DocumentMetadata, DocumentStatus
from dms.sdk.errors import (
    ConsistencyError,
    DocumentDeletedError,
    DocumentNotFoundError,

    MetadataStoreError,

    StorageError,
    ValidationError,

)
from dms.sdk.types import (
    AsyncDocumentContentStream,
    AsyncUploadDocumentStreamRequest,
    AsyncUploadDocumentUnknownSizeStreamRequest,
    BatchReconciliationResult,
    DeleteDocumentResult,
    DocumentContent,
    DocumentContentStream,
    DocumentInspection,
    DocumentPage,
    HealthStatus,
    PublicDocumentMetadata,
    ReconciliationResult,
    ReconciliationPlan,
    RecoveryAuditEvent,
    RecoveryAction,
    RecoveryIssue,

    UploadDocumentRequest,
    UploadDocumentStreamRequest,
    UploadDocumentResult,
    UploadDocumentUnknownSizeStreamRequest,
    UploadOperationResult,
    public_metadata,
)
from dms.sdk.metadata import DefaultMetadataPolicy, MetadataValidator

from dms.sdk.pagination import decode_cursor, encode_cursor
from dms.sdk.upload import UploadService
from dms.sdk.reconciliation import ReconciliationCoordinator
from dms.sdk.lifecycle import LifecycleService


DocumentIdGenerator: TypeAlias = Callable[[], str]

_MAX_PAGE_LIMIT = 1000
_PUBLIC_EXCLUDED_STATUSES = (DocumentStatus.DELETING, DocumentStatus.DELETED)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _new_document_id() -> str:
    return str(uuid4())


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
        recovery_audit_hook: Callable[[RecoveryAuditEvent], object] | None = None,
    ) -> None:
        self._metadata_store = metadata_store
        self._object_store = object_store
        self._logger = logger or logging.getLogger("dms.sdk")
        self._id_generator = id_generator or _new_document_id
        self._service_checks = dict(service_checks or {})
        self._close_callbacks = list(close_callbacks or [])

        if max_file_size is not None and max_file_size <= 0:
            raise ValidationError("max_file_size must be positive")
        self._max_file_size = max_file_size
        self._operation_store = operation_store
        self._metadata_validator = metadata_validator or DefaultMetadataPolicy()
        self._recovery_audit_hook = recovery_audit_hook
        self._uploads = UploadService(
            metadata_store=metadata_store, object_store=object_store, logger=self._logger,
            id_generator=self._id_generator, metadata_validator=self._metadata_validator,
            max_file_size=max_file_size, operation_store=operation_store,
            get_internal_metadata=self.get_internal_document_metadata,
            stream_upload=lambda request: self.upload_document_stream(request),
            spool_factory=SpooledTemporaryFile,
        )
        self._reconciliation = ReconciliationCoordinator(
            metadata_store=metadata_store, object_store=object_store,
            inspect_override=lambda document_id: self.inspect_document(document_id),
            reconcile_override=lambda document_id, action, **kwargs: self.reconcile_document(document_id, action, **kwargs),
            list_candidates=self.list_recovery_candidates,
            get_metadata=self.get_internal_document_metadata,
            set_failed=self._set_document_status,
            emit_audit=self._emit_recovery_audit,
        )

        self._lifecycle = LifecycleService(
            service_checks=self._service_checks,
            close_callbacks=self._close_callbacks,
            logger=self._logger,
        )

    def __enter__(self) -> DefaultDocumentManagementSDK:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()

    async def __aenter__(self) -> DefaultDocumentManagementSDK:
        return self

    async def __aexit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        await self.aclose()

    def upload_document(self, request: UploadDocumentRequest) -> UploadDocumentResult:
        return self._uploads.upload_document(request)

    def upload_document_stream(self, request: UploadDocumentStreamRequest) -> UploadDocumentResult:
        return self._uploads.upload_document_stream(request)

    def upload_document_unknown_size_stream(
        self, request: UploadDocumentUnknownSizeStreamRequest
    ) -> UploadDocumentResult:
        return self._uploads.upload_document_unknown_size_stream(request)

    async def upload_document_async_stream(
        self, request: AsyncUploadDocumentStreamRequest,
    ) -> UploadDocumentResult:
        return await self._uploads.upload_document_async_stream(request)

    async def upload_document_async_unknown_size_stream(
        self, request: AsyncUploadDocumentUnknownSizeStreamRequest,
    ) -> UploadDocumentResult:
        return await self._uploads.upload_document_async_unknown_size_stream(request)

    def get_upload_operation(self, *, scope: str, idempotency_key: str) -> UploadOperationResult:
        return self._uploads.get_upload_operation(scope=scope, idempotency_key=idempotency_key)

    def get_internal_document_metadata(self, document_id: str) -> DocumentMetadata:
        """Return storage-bearing metadata for privileged administration and recovery."""
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

    def get_document_metadata(self, document_id: str) -> PublicDocumentMetadata:
        return self._get_document_metadata(document_id)

    def _get_document_metadata(self, document_id: str) -> PublicDocumentMetadata:
        metadata = self.get_internal_document_metadata(document_id)
        if metadata.status in _PUBLIC_EXCLUDED_STATUSES:
            raise DocumentNotFoundError(
                f"Document not found: {document_id}", document_id=document_id)
        return public_metadata(metadata)

    def list_documents(
        self,
        *,
        cursor: str | None = None,
        limit: int = 100,
        status: DocumentStatus | None = None,
    ) -> DocumentPage:
        return self.list_documents_page(cursor=cursor, limit=limit, status=status)

    def _list_documents(
        self, *, offset: int, limit: int, status: DocumentStatus | None,
    ) -> list[PublicDocumentMetadata]:
        self._validate_public_status(status)
        return [public_metadata(item) for item in self._list_internal_documents(
            offset=offset, limit=limit, status=status,
            excluded_statuses=_PUBLIC_EXCLUDED_STATUSES)]

    def _list_internal_documents(
        self, *, offset: int = 0, limit: int = 100,
        status: DocumentStatus | None = None,
        excluded_statuses: tuple[DocumentStatus, ...] = (),
    ) -> list[DocumentMetadata]:
        if offset < 0:
            raise ValidationError("offset must not be negative")
        if limit <= 0:
            raise ValidationError("limit must be positive")

        try:
            if excluded_statuses:
                metadata = self._metadata_store.list_metadata(
                    offset=offset, limit=limit, status=status,
                    excluded_statuses=excluded_statuses)
            else:
                metadata = self._metadata_store.list_metadata(
                    offset=offset, limit=limit, status=status)
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

    def list_documents_page(
        self, *, cursor: str | None = None, limit: int = 100,
        status: DocumentStatus | None = None,
    ) -> DocumentPage:
        return self._list_documents_page(cursor=cursor, limit=limit, status=status)

    def _list_documents_page(
        self, *, cursor: str | None, limit: int, status: DocumentStatus | None,
    ) -> DocumentPage:
        self._validate_public_status(status)
        if limit <= 0 or limit > _MAX_PAGE_LIMIT:
            raise ValidationError("limit must be between 1 and 1000")
        after_created_at: datetime | None = None
        after_document_id: str | None = None
        if cursor is not None:
            after_created_at, after_document_id, cursor_status, cursor_page_size = decode_cursor(cursor)
            requested_status = status.value if status is not None else None
            if cursor_status != requested_status:
                raise ValidationError("cursor status filter does not match the request")
            if cursor_page_size != limit:
                raise ValidationError("cursor page size does not match the request")
        try:
            metadata = self._metadata_store.list_metadata_page(
                after_created_at=after_created_at, after_document_id=after_document_id,
                limit=limit + 1, status=status,
                excluded_statuses=_PUBLIC_EXCLUDED_STATUSES,
            )
        except Exception as exc:
            raise MetadataStoreError("Failed to list document metadata page") from exc
        has_more = len(metadata) > limit
        items = metadata[:limit]
        next_cursor = None
        if has_more and items:
            last = items[-1]
            next_cursor = encode_cursor(last.created_at, last.document_id, status, limit)
        return DocumentPage(items=[public_metadata(item) for item in items],
            next_cursor=next_cursor, has_more=has_more)

    @staticmethod
    def _validate_public_status(status: DocumentStatus | None) -> None:
        if status in _PUBLIC_EXCLUDED_STATUSES:
            raise ValidationError(
                "deleted statuses are not available through public document queries")


    def inspect_document(self, document_id: str) -> DocumentInspection:
        """Inspect consistency; missing metadata is a result, not a not-found error."""
        return self._reconciliation.inspect_document(document_id)

    def list_recovery_candidates(self, *, status: DocumentStatus,
                                 offset: int = 0, limit: int = 100) -> list[DocumentMetadata]:
        self._validate_recovery_page(status=status, offset=offset, limit=limit)
        return self._list_internal_documents(offset=offset, limit=limit, status=status)


    def reconcile_document(self, document_id: str, action: RecoveryAction, *,
                           storage_key: str | None = None,
                           dry_run: bool = False,
                           actor: str | None = None) -> ReconciliationResult:
        return self._reconciliation.reconcile_document(
            document_id, action, storage_key=storage_key, dry_run=dry_run, actor=actor)

    def execute_reconciliation_plan(
        self, plan: ReconciliationPlan, *, actor: str | None = None
    ) -> BatchReconciliationResult:
        return self._reconciliation.execute_reconciliation_plan(plan, actor=actor)

    def _emit_recovery_audit(self, event: RecoveryAuditEvent) -> None:
        if self._recovery_audit_hook is None:
            return
        try:
            self._recovery_audit_hook(event)
        except Exception:
            self._logger.exception("recovery audit hook failed")

    def reconcile_documents(self, *, status: DocumentStatus, action: RecoveryAction,
                            offset: int = 0, limit: int = 100,
                            dry_run: bool = False,
                            actor: str | None = None) -> BatchReconciliationResult:
        return self._reconciliation.reconcile_documents(
            status=status, action=action, offset=offset, limit=limit,
            dry_run=dry_run, actor=actor)

    @staticmethod
    def _validate_recovery_page(*, status: DocumentStatus, offset: int, limit: int) -> None:
        if status not in (DocumentStatus.FAILED, DocumentStatus.DELETING):
            raise ValidationError("recovery status must be FAILED or DELETING")
        if offset < 0:
            raise ValidationError("offset must not be negative")
        if limit <= 0 or limit > 1000:
            raise ValidationError("recovery limit must be between 1 and 1000")

    def get_document_content(self, document_id: str) -> DocumentContent:
        return self._get_document_content(document_id)

    def _get_document_content(self, document_id: str) -> DocumentContent:
        started = perf_counter()
        metadata = self.get_internal_document_metadata(document_id)
        self._ensure_content_readable(metadata)
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
        return self._get_document_content_stream(document_id, chunk_size=chunk_size)

    async def get_document_content_async_stream(
        self, document_id: str, *, chunk_size: int = 65536,
    ) -> AsyncDocumentContentStream:
        open_task = asyncio.create_task(asyncio.to_thread(
            self.get_document_content_stream, document_id, chunk_size=chunk_size
        ))
        try:
            source = await asyncio.shield(open_task)
        except asyncio.CancelledError:
            try:
                source = await open_task
            except Exception:
                raise
            await asyncio.to_thread(source.close)
            raise
        return AsyncDocumentContentStream(
            document_id=document_id, _source=source, chunk_size=chunk_size
        )

    def _get_document_content_stream(
        self, document_id: str, *, chunk_size: int,
    ) -> DocumentContentStream:
        if chunk_size <= 0:
            raise ValidationError("chunk_size must be positive")

        started = perf_counter()
        metadata = self.get_internal_document_metadata(document_id)
        self._ensure_content_readable(metadata)
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
        return self._delete_document(document_id, hard_delete=hard_delete)

    def _delete_document(
        self, document_id: str, *, hard_delete: bool,
    ) -> DeleteDocumentResult:
        started = perf_counter()
        metadata = self.get_internal_document_metadata(document_id)
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

    def soft_delete_document(self, document_id: str) -> DeleteDocumentResult:
        return self.delete_document(document_id, hard_delete=False)

    def hard_delete_document(self, document_id: str) -> DeleteDocumentResult:
        return self.delete_document(document_id, hard_delete=True)

    @staticmethod
    def _ensure_content_readable(metadata: DocumentMetadata) -> None:
        if metadata.status in (DocumentStatus.DELETING, DocumentStatus.DELETED):
            raise DocumentDeletedError(
                f"Document content is unavailable after deletion: {metadata.document_id}",
                document_id=metadata.document_id,
            )

    def check_health(self) -> HealthStatus:
        health = self._lifecycle.check_health()
        self._log_info(
            "sdk.health.checked",
            ok=health.ok,
            service_count=len(health.services),
            failed_services=[service.service for service in health.services if not service.ok],
        )
        return health

    def close(self) -> None:
        was_closed = self._lifecycle.closed
        self._lifecycle.close()
        if was_closed:
            return
        self._log_info("sdk.close.succeeded", callback_count=len(self._close_callbacks))

    async def aclose(self) -> None:
        await asyncio.to_thread(self.close)

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
