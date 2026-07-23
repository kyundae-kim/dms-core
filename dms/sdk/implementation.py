from __future__ import annotations

import asyncio
import logging

from tempfile import SpooledTemporaryFile
from collections.abc import Callable, Iterable, Mapping
from typing import TypeAlias
from uuid import uuid4

from dms.domain.interfaces import MetadataStore, ObjectStore, UploadOperationStore
from dms.domain.models import DocumentMetadata, DocumentStatus
from dms.sdk.errors import ValidationError
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
    UploadDocumentRequest,
    UploadDocumentStreamRequest,
    UploadDocumentResult,
    UploadDocumentUnknownSizeStreamRequest,
    UploadOperationResult,
)
from dms.sdk.metadata import DefaultMetadataPolicy, MetadataValidator
from dms.sdk.upload import UploadService
from dms.sdk.reconciliation import ReconciliationCoordinator
from dms.sdk.lifecycle import LifecycleService
from dms.sdk.documents import DocumentService


DocumentIdGenerator: TypeAlias = Callable[[], str]

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
        self._service_checks = dict(service_checks or {})
        self._close_callbacks = list(close_callbacks or [])

        if max_file_size is not None and max_file_size <= 0:
            raise ValidationError("max_file_size must be positive")
        self._operation_store = operation_store
        self._recovery_audit_hook = recovery_audit_hook
        self._documents = DocumentService(
            metadata_store=metadata_store,
            object_store=object_store,
            logger=self._logger,
        )
        self._uploads = UploadService(
            metadata_store=metadata_store, object_store=object_store, logger=self._logger,
            id_generator=id_generator or _new_document_id,
            metadata_validator=metadata_validator or DefaultMetadataPolicy(),
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
        return self._documents.get_internal_metadata(document_id)

    def get_document_metadata(self, document_id: str) -> PublicDocumentMetadata:
        return self._documents.get_metadata(document_id)

    def list_documents(
        self,
        *,
        cursor: str | None = None,
        limit: int = 100,
        status: DocumentStatus | None = None,
    ) -> DocumentPage:
        return self.list_documents_page(cursor=cursor, limit=limit, status=status)

    def _list_internal_documents(
        self, *, offset: int = 0, limit: int = 100,
        status: DocumentStatus | None = None,
        excluded_statuses: tuple[DocumentStatus, ...] = (),
    ) -> list[DocumentMetadata]:
        return self._documents.list_internal(
            offset=offset,
            limit=limit,
            status=status,
            excluded_statuses=excluded_statuses,
        )

    def list_documents_page(
        self, *, cursor: str | None = None, limit: int = 100,
        status: DocumentStatus | None = None,
    ) -> DocumentPage:
        return self._documents.list_page(cursor=cursor, limit=limit, status=status)


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
        return self._documents.get_content(document_id)

    def get_document_content_stream(
        self,
        document_id: str,
        *,
        chunk_size: int = 65536,
    ) -> DocumentContentStream:
        return self._documents.get_content_stream(document_id, chunk_size=chunk_size)

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

    def delete_document(
        self,
        document_id: str,
        *,
        hard_delete: bool = False,
    ) -> DeleteDocumentResult:
        return self._documents.delete(document_id, hard_delete=hard_delete)

    def soft_delete_document(self, document_id: str) -> DeleteDocumentResult:
        return self.delete_document(document_id, hard_delete=False)

    def hard_delete_document(self, document_id: str) -> DeleteDocumentResult:
        return self.delete_document(document_id, hard_delete=True)

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
        return self._documents.set_status(metadata, status)

    def _log_info(self, event: str, **context: object) -> None:
        self._logger.info(event, extra=self._build_log_extra(event, context))

    @staticmethod
    def _build_log_extra(event: str, context: Mapping[str, object]) -> dict[str, object]:
        extra: dict[str, object] = {"dms_event": event}
        for key, value in context.items():
            extra[f"dms_{key}"] = value
        return extra
