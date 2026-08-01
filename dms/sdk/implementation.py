from __future__ import annotations

import asyncio
import hashlib
import logging
import mimetypes

from collections.abc import Callable, Iterable, Iterator, Mapping
from contextvars import ContextVar
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO, TypeAlias, TypeVar
from uuid import uuid4

from dms.domain.interfaces import MetadataStore, ObjectStore, UploadOperationStore
from dms.domain.models import DocumentMetadata, DocumentStatus
from dms.sdk.errors import (
    AccessDeniedError,
    ConsistencyError,
    DataResetError,
    DmsError,
    StorageError,
    ValidationError,
)
from dms.sdk.contracts import (
    AccessContext,
    DocumentAccessPolicy,
    DocumentCopyResult,
    DmsOperationContext,
    ManagedResource,
    OperationEvent,
    OperationObserver,
)
from dms.sdk.pagination import encode_cursor
from dms.sdk.types import (
    AsyncDocumentContentStream,
    BatchReconciliationResult,
    DataResetResult,
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

    UploadOperationResult,
    public_metadata,
)
from dms.sdk.metadata import DefaultMetadataPolicy, MetadataValidator
from dms.sdk.observability import build_log_extra
from dms.sdk.upload import UploadService
from dms.sdk.reconciliation import ReconciliationCoordinator
from dms.sdk.lifecycle import LifecycleService
from dms.sdk.documents import DocumentService


DocumentIdGenerator: TypeAlias = Callable[[], str]
ObservedResult = TypeVar("ObservedResult")
ObserverConditions: TypeAlias = (
    Mapping[str, object] | Callable[[object], Mapping[str, object]]
)
_recovery_access_context: ContextVar[AccessContext | None] = ContextVar(
    "dms_recovery_access_context",
    default=None,
)

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
        managed_resources: Iterable[ManagedResource] | None = None,
        max_file_size: int | None = None,
        operation_store: UploadOperationStore | None = None,
        metadata_validator: MetadataValidator | None = None,
        recovery_audit_hook: Callable[[RecoveryAuditEvent], object] | None = None,
        access_policy: DocumentAccessPolicy | None = None,
        operation_observer: OperationObserver | None = None,
    ) -> None:
        # Retain injected adapters on the facade for existing integration seams.
        self._metadata_store = metadata_store
        self._object_store = object_store
        self._logger = logger or logging.getLogger("dms.sdk")
        self._service_checks = dict(service_checks or {})
        self._close_callbacks = list(close_callbacks or [])
        self._managed_resources = list(managed_resources or [])
        self._lifecycle = LifecycleService(
            service_checks=self._service_checks,
            close_callbacks=self._close_callbacks,
            managed_resources=self._managed_resources,
            logger=self._logger,
        )
        try:
            if max_file_size is not None and max_file_size <= 0:
                raise ValidationError("max_file_size must be positive")
            self._operation_store = operation_store
            self._recovery_audit_hook = recovery_audit_hook
            self._access_policy = access_policy
            self._operation_observer = operation_observer
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
            )
            self._reconciliation = ReconciliationCoordinator(
                metadata_store=metadata_store, object_store=object_store,
                inspect_override=lambda document_id: self.inspect_document(document_id),
                reconcile_override=lambda document_id, action, **kwargs: self.reconcile_document(
                    document_id,
                    action,
                    **kwargs,
                ),
                list_candidates=self.list_recovery_candidates,
                get_metadata=self.get_internal_document_metadata,
                set_failed=self._set_document_status,
                emit_audit=self._emit_recovery_audit,
            )
        except Exception as failure:
            try:
                self._lifecycle.close()
            except Exception as cleanup_error:
                failure.add_note(f"Managed-resource rollback failed: {cleanup_error}")
            raise

    def __enter__(self) -> DefaultDocumentManagementSDK:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()

    async def __aenter__(self) -> DefaultDocumentManagementSDK:
        return self

    async def __aexit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        await self.aclose()

    def scoped(self, context: DmsOperationContext) -> ScopedDocumentManagementSDK:
        return ScopedDocumentManagementSDK(self, context)

    def upload_document(self, request: UploadDocumentRequest) -> UploadDocumentResult:
        return self._run_observed(
            "upload",
            lambda: self._uploads.upload_document(request),
            document_id=request.document_id,
        )

    def upload_file(
        self,
        path: str | Path,
        *,
        filename: str | None = None,
        content_type: str | None = None,
        document_id: str | None = None,
        metadata: Mapping[str, object] | None = None,
        created_by: str | None = None,
    ) -> UploadDocumentResult:
        source_path = Path(path)
        resolved_filename = source_path.name if filename is None else filename
        resolved_content_type = content_type if content_type is not None else (
            mimetypes.guess_type(resolved_filename)[0] or "application/octet-stream"
        )

        try:
            size = source_path.stat().st_size
            with source_path.open("rb") as stream:
                return self.upload_document_stream(UploadDocumentStreamRequest(
                    stream=stream,
                    size=size,
                    filename=resolved_filename,
                    content_type=resolved_content_type,
                    document_id=document_id,
                    metadata=dict(metadata or {}),
                    created_by=created_by,
                ))
        except OSError as exc:
            raise StorageError(
                f"Failed to read document file: {source_path}",
                document_id=document_id,
            ) from exc

    def upload_document_stream(self, request: UploadDocumentStreamRequest) -> UploadDocumentResult:
        return self._run_observed(
            "upload",
            lambda: self._uploads.upload_document_stream(request),
            document_id=request.document_id,
        )



    def get_upload_operation(self, *, scope: str, idempotency_key: str) -> UploadOperationResult:
        return self._uploads.get_upload_operation(scope=scope, idempotency_key=idempotency_key)

    def get_internal_document_metadata(
        self,
        document_id: str,
        *,
        access_context: AccessContext | None = None,
    ) -> DocumentMetadata:
        """Return storage-bearing metadata for privileged administration and recovery."""
        effective_access_context = access_context or _recovery_access_context.get()

        def get_metadata() -> DocumentMetadata:
            metadata = self._documents.get_internal_metadata(document_id)
            self._require_access("metadata.internal", effective_access_context, metadata)
            return metadata

        return self._run_observed(
            "metadata.internal",
            get_metadata,
            document_id=document_id,
        )

    def get_document_metadata(
        self,
        document_id: str,
        *,
        access_context: AccessContext | None = None,
    ) -> PublicDocumentMetadata:
        def get_metadata() -> PublicDocumentMetadata:
            metadata = self._documents.get_metadata(document_id)
            self._require_access("metadata.get", access_context, metadata)
            return metadata

        return self._run_observed(
            "metadata.get",
            get_metadata,
            document_id=document_id,
        )

    def list_documents(
        self,
        *,
        cursor: str | None = None,
        limit: int = 100,
        status: DocumentStatus | None = None,
        access_context: AccessContext | None = None,
    ) -> DocumentPage:
        return self.list_documents_page(
            cursor=cursor,
            limit=limit,
            status=status,
            access_context=access_context,
        )

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
        access_context: AccessContext | None = None,
    ) -> DocumentPage:
        return self._run_observed(
            "documents.list",
            lambda: self._list_documents_page(
                cursor=cursor,
                limit=limit,
                status=status,
                access_context=access_context,
            ),
            conditions={
                "limit": limit,
                "status": getattr(status, "value", status),
            },
        )

    def _list_documents_page(
        self, *, cursor: str | None = None, limit: int = 100,
        status: DocumentStatus | None = None,
        access_context: AccessContext | None = None,
    ) -> DocumentPage:
        if self._access_policy is None:
            return self._documents.list_page(cursor=cursor, limit=limit, status=status)
        scan_cursor = cursor
        allowed: list[PublicDocumentMetadata] = []
        scan_size = limit
        while len(allowed) <= limit:
            page = self._documents.list_page(
                cursor=scan_cursor,
                limit=scan_size,
                status=status,
            )
            allowed.extend(
                item
                for item in page.items
                if self._allows("documents.list", access_context, item)
            )
            if page.next_cursor is None or len(allowed) > limit:
                break
            scan_cursor = page.next_cursor
        has_more = len(allowed) > limit
        items = allowed[:limit]
        next_cursor = None
        if has_more and items:
            last = items[-1]
            next_cursor = encode_cursor(
                last.created_at,
                last.document_id,
                status,
                limit,
            )
        return DocumentPage(
            items=items,
            next_cursor=next_cursor,
            has_more=has_more,
        )

    def iter_documents(
        self,
        *,
        status: DocumentStatus | None = None,
        page_size: int = 100,
        access_context: AccessContext | None = None,
    ) -> Iterator[PublicDocumentMetadata]:
        cursor: str | None = None
        while True:
            page = self.list_documents(
                cursor=cursor,
                limit=page_size,
                status=status,
                access_context=access_context,
            )
            yield from page.items
            if page.next_cursor is None:
                return
            cursor = page.next_cursor


    def inspect_document(
        self,
        document_id: str,
        *,
        access_context: AccessContext | None = None,
    ) -> DocumentInspection:
        """Inspect consistency; missing metadata is a result, not a not-found error."""
        effective_access_context = access_context or _recovery_access_context.get()

        def inspect() -> DocumentInspection:
            inspection = self._reconciliation.inspect_document(document_id)
            metadata = (
                self._documents.get_internal_metadata(document_id)
                if inspection.metadata_exists
                else None
            )
            self._require_access("document.inspect", effective_access_context, metadata)
            return inspection

        return self._run_observed(
            "document.inspect",
            inspect,
            document_id=document_id,
        )

    def _list_recovery_candidates(self, *, status: DocumentStatus,
                                  offset: int = 0, limit: int = 100) -> list[DocumentMetadata]:
        self._validate_recovery_page(status=status, offset=offset, limit=limit)
        return self._list_internal_documents(offset=offset, limit=limit, status=status)

    def list_recovery_candidates(
        self,
        *,
        status: DocumentStatus,
        offset: int = 0,
        limit: int = 100,
        access_context: AccessContext | None = None,
    ) -> list[DocumentMetadata]:
        def list_candidates() -> list[DocumentMetadata]:
            self._validate_recovery_page(status=status, offset=offset, limit=limit)
            if self._access_policy is None:
                return self._list_recovery_candidates(
                    status=status,
                    offset=offset,
                    limit=limit,
                )
            allowed: list[DocumentMetadata] = []
            scan_offset = 0
            scan_limit = min(max(limit, 100), 1000)
            while len(allowed) < offset + limit:
                batch = self._list_recovery_candidates(
                    status=status,
                    offset=scan_offset,
                    limit=scan_limit,
                )
                allowed.extend(
                    item
                    for item in batch
                    if self._allows("recovery.list", access_context, item)
                )
                if len(batch) < scan_limit:
                    break
                scan_offset += len(batch)
            return allowed[offset:offset + limit]

        return self._run_observed(
            "recovery.list",
            list_candidates,
            conditions={
                "status": getattr(status, "value", status),
                "offset": offset,
                "limit": limit,
            },
        )

    def iter_recovery_candidates(
        self,
        *,
        status: DocumentStatus,
        page_size: int = 100,
        access_context: AccessContext | None = None,
    ) -> Iterator[DocumentMetadata]:
        offset = 0
        while True:
            items = self.list_recovery_candidates(
                status=status,
                offset=offset,
                limit=page_size,
                access_context=access_context,
            )
            if not items:
                return
            yield from items
            if len(items) < page_size:
                return
            offset += len(items)


    def reconcile_document(self, document_id: str, action: RecoveryAction, *,
                           storage_key: str | None = None,
                           dry_run: bool = False,
                           actor: str | None = None,
                           access_context: AccessContext | None = None) -> ReconciliationResult:
        effective_access_context = access_context or _recovery_access_context.get()

        def reconcile() -> ReconciliationResult:
            inspection = self._reconciliation.inspect_document(document_id)
            metadata = (
                self._documents.get_internal_metadata(document_id)
                if inspection.metadata_exists
                else None
            )
            self._require_access("recovery.execute", effective_access_context, metadata)
            token = _recovery_access_context.set(effective_access_context)
            try:
                return self._reconciliation.reconcile_document(
                    document_id,
                    action,
                    storage_key=storage_key,
                    dry_run=dry_run,
                    actor=actor,
                )
            finally:
                _recovery_access_context.reset(token)

        return self._run_observed(
            "recovery.execute",
            reconcile,
            document_id=document_id,
            conditions={"action": getattr(action, "value", action), "dry_run": dry_run},
        )

    def execute_reconciliation_plan(
        self,
        plan: ReconciliationPlan,
        *,
        actor: str | None = None,
        access_context: AccessContext | None = None,
    ) -> BatchReconciliationResult:
        def execute() -> BatchReconciliationResult:
            if not isinstance(plan, ReconciliationPlan):
                raise ValidationError("plan must be a ReconciliationPlan")
            for item in plan.items:
                inspection = self._reconciliation.inspect_document(item.document_id)
                metadata = (
                    self._documents.get_internal_metadata(item.document_id)
                    if inspection.metadata_exists
                    else None
                )
                self._require_access("recovery.execute", access_context, metadata)
            token = _recovery_access_context.set(access_context)
            try:
                return self._reconciliation.execute_reconciliation_plan(plan, actor=actor)
            finally:
                _recovery_access_context.reset(token)

        return self._run_observed(
            "recovery.plan.execute",
            execute,
            conditions={"item_count": len(getattr(plan, "items", ()))},
        )

    def _emit_recovery_audit(self, event: RecoveryAuditEvent) -> None:
        if self._recovery_audit_hook is None:
            return
        try:
            self._recovery_audit_hook(event)
        except Exception:
            self._logger.exception("recovery audit hook failed")

    def _set_document_status(
        self,
        metadata: DocumentMetadata,
        status: DocumentStatus,
    ) -> DocumentMetadata:
        return self._documents.set_status(metadata, status)

    def reconcile_documents(self, *, status: DocumentStatus, action: RecoveryAction,
                            offset: int = 0, limit: int = 100,
                            dry_run: bool = False,
                            actor: str | None = None,
                            access_context: AccessContext | None = None,
                            ) -> BatchReconciliationResult:
        def reconcile_batch() -> BatchReconciliationResult:
            if not isinstance(action, RecoveryAction):
                raise ValidationError("action must be a RecoveryAction")
            candidates = self.list_recovery_candidates(
                status=status,
                offset=offset,
                limit=limit,
                access_context=access_context,
            )
            token = _recovery_access_context.set(access_context)
            try:
                return self._reconciliation.reconcile_documents(
                    status=status,
                    action=action,
                    offset=offset,
                    limit=limit,
                    dry_run=dry_run,
                    actor=actor,
                    candidates=candidates,
                )
            finally:
                _recovery_access_context.reset(token)

        return self._run_observed(
            "recovery.batch.execute",
            reconcile_batch,
            conditions={
                "status": getattr(status, "value", status),
                "action": getattr(action, "value", action),
                "offset": offset,
                "limit": limit,
                "dry_run": dry_run,
            },
        )

    @staticmethod
    def _validate_recovery_page(*, status: DocumentStatus, offset: int, limit: int) -> None:
        if not isinstance(status, DocumentStatus) or status not in (
            DocumentStatus.FAILED,
            DocumentStatus.DELETING,
        ):
            raise ValidationError("recovery status must be FAILED or DELETING")
        if offset < 0:
            raise ValidationError("offset must not be negative")
        if limit <= 0 or limit > 1000:
            raise ValidationError("recovery limit must be between 1 and 1000")

    def get_document_content(
        self,
        document_id: str,
        *,
        access_context: AccessContext | None = None,
    ) -> DocumentContent:
        def get_content() -> DocumentContent:
            metadata = self._documents.get_internal_metadata(document_id)
            self._require_access("content.get", access_context, metadata)
            return self._documents.get_content(document_id)

        return self._run_observed(
            "content.get",
            get_content,
            document_id=document_id,
        )

    def get_document_content_stream(
        self,
        document_id: str,
        *,
        chunk_size: int = 65536,
        access_context: AccessContext | None = None,
    ) -> DocumentContentStream:
        if chunk_size <= 0:
            raise ValidationError("chunk_size must be positive")

        def get_stream() -> DocumentContentStream:
            metadata = self._documents.get_internal_metadata(document_id)
            self._require_access("content.stream", access_context, metadata)
            return self._documents.get_content_stream(document_id, chunk_size=chunk_size)

        return self._run_observed(
            "content.stream",
            get_stream,
            document_id=document_id,
            conditions={"chunk_size": chunk_size},
        )

    def iter_document_chunks(
        self,
        document_id: str,
        *,
        chunk_size: int = 65536,
        access_context: AccessContext | None = None,
    ) -> Iterator[bytes]:
        source = self.get_document_content_stream(
            document_id,
            chunk_size=chunk_size,
            access_context=access_context,
        )
        try:
            yield from source.iter_chunks(chunk_size)
        finally:
            source.close()

    def copy_document_to(
        self,
        document_id: str,
        sink: BinaryIO,
        *,
        chunk_size: int = 65536,
        verify_checksum: bool = True,
        access_context: AccessContext | None = None,
    ) -> DocumentCopyResult:
        metadata = self._documents.get_internal_metadata(document_id)
        source = self.get_document_content_stream(
            document_id,
            chunk_size=chunk_size,
            access_context=access_context,
        )
        digest = hashlib.sha256()
        copied = 0
        failure: BaseException | None = None
        try:
            for chunk in source.iter_chunks(chunk_size):
                sink.write(chunk)
                copied += len(chunk)
                digest.update(chunk)
        except BaseException as exc:
            failure = exc
            raise
        finally:
            try:
                source.close()
            except Exception:
                if failure is None:
                    raise
        checksum = digest.hexdigest()
        if copied != source.size:
            raise ConsistencyError(
                f"copied size {copied} does not match stored size {source.size}",
                document_id=document_id,
            )
        checksum_verified = False
        expected_checksum = metadata.checksum or source.checksum
        if verify_checksum and expected_checksum is not None:
            if checksum != expected_checksum:
                raise ConsistencyError(
                    "copied content checksum does not match stored checksum",
                    document_id=document_id,
                )
            checksum_verified = True
        return DocumentCopyResult(
            document_id=document_id,
            bytes_copied=copied,
            checksum=checksum,
            checksum_verified=checksum_verified,
        )

    async def get_document_content_async_stream(
        self,
        document_id: str,
        *,
        chunk_size: int = 65536,
        access_context: AccessContext | None = None,
    ) -> AsyncDocumentContentStream:
        open_task = asyncio.create_task(asyncio.to_thread(
            self.get_document_content_stream,
            document_id,
            chunk_size=chunk_size,
            access_context=access_context,
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
        access_context: AccessContext | None = None,
    ) -> DeleteDocumentResult:
        def delete() -> DeleteDocumentResult:
            metadata = self._documents.get_internal_metadata(document_id)
            self._require_access("document.delete", access_context, metadata)
            return self._documents.delete(document_id, hard_delete=hard_delete)

        return self._run_observed(
            "document.delete",
            delete,
            document_id=document_id,
            conditions={"hard_delete": hard_delete},
        )

    def soft_delete_document(
        self,
        document_id: str,
        *,
        access_context: AccessContext | None = None,
    ) -> DeleteDocumentResult:
        return self.delete_document(
            document_id,
            hard_delete=False,
            access_context=access_context,
        )

    def hard_delete_document(
        self,
        document_id: str,
        *,
        access_context: AccessContext | None = None,
    ) -> DeleteDocumentResult:
        return self.delete_document(
            document_id,
            hard_delete=True,
            access_context=access_context,
        )

    def clear_all_data(
        self,
        *,
        access_context: AccessContext | None = None,
    ) -> DataResetResult:
        return self._reset_all_data(
            operation="data.clear_all",
            access_context=access_context,
        )

    def initialize_for_data_load(
        self,
        *,
        access_context: AccessContext | None = None,
    ) -> DataResetResult:
        """Clear DMS-owned data and leave the stores ready for a fresh load."""
        return self._reset_all_data(
            operation="data.initialize_for_data_load",
            access_context=access_context,
        )

    def _reset_all_data(
        self,
        *,
        operation: str,
        access_context: AccessContext | None,
    ) -> DataResetResult:
        def reset() -> DataResetResult:
            self._require_access(operation, access_context, None)
            counts: dict[str, int] = {}
            errors: list[Exception] = []
            failed_stores: list[str] = []
            stores: list[tuple[str, Callable[[], int]]] = [
                ("objects", self._object_store.clear_all),
                ("metadata", self._metadata_store.clear_all),
            ]
            if self._operation_store is not None:
                stores.append(("upload_operations", self._operation_store.clear_all))
            for name, clear_all in stores:
                try:
                    counts[name] = clear_all()
                except Exception as exc:
                    partial_count = getattr(exc, "dms_deleted_count", 0)
                    counts[name] = (
                        partial_count
                        if isinstance(partial_count, int) and partial_count >= 0
                        else 0
                    )
                    errors.append(exc)
                    failed_stores.append(name)
                    self._logger.error(
                        "sdk.data_reset.store_failed",
                        extra=build_log_extra(
                            "sdk.data_reset.store_failed",
                            {"store": name, "error_type": type(exc).__name__},
                        ),
                    )
            result = DataResetResult(
                metadata_deleted=counts.get("metadata", 0),
                objects_deleted=counts.get("objects", 0),
                upload_operations_deleted=counts.get("upload_operations", 0),
                ready_for_data_load=not failed_stores,
            )
            if errors:
                raise DataResetError(
                    "DMS data reset did not complete for every store",
                    result=result,
                    errors=tuple(errors),
                    failed_stores=tuple(failed_stores),
                )
            self._log_info(
                "sdk.data_reset.succeeded",
                metadata_deleted=result.metadata_deleted,
                objects_deleted=result.objects_deleted,
                upload_operations_deleted=result.upload_operations_deleted,
                ready_for_data_load=result.ready_for_data_load,
            )
            return result

        return self._run_observed(
            operation,
            reset,
            conditions=self._data_reset_observer_conditions,
        )

    @staticmethod
    def _data_reset_observer_conditions(outcome: object) -> Mapping[str, object]:
        if isinstance(outcome, DataResetResult):
            return {"ready_for_data_load": outcome.ready_for_data_load}
        if isinstance(outcome, DataResetError):
            return {"ready_for_data_load": outcome.result.ready_for_data_load}
        return {}

    def check_health(self) -> HealthStatus:
        def check() -> HealthStatus:
            health = self._lifecycle.check_health()
            self._log_info(
                "sdk.health.checked",
                ok=health.ok,
                service_count=len(health.services),
                failed_services=[service.service for service in health.services if not service.ok],
            )
            return health

        return self._run_observed("health.check", check)

    def close(self) -> None:
        was_closed = self._lifecycle.closed
        self._lifecycle.close()
        if was_closed:
            return
        self._log_info(
            "sdk.close.succeeded",
            callback_count=self._lifecycle.resource_count,
        )

    async def aclose(self) -> None:
        was_closed = self._lifecycle.closed
        await self._lifecycle.aclose()
        if was_closed:
            return
        self._log_info(
            "sdk.close.succeeded",
            callback_count=self._lifecycle.resource_count,
        )

    def _allows(
        self,
        operation: str,
        context: AccessContext | None,
        metadata: DocumentMetadata | PublicDocumentMetadata | None,
    ) -> bool:
        if self._access_policy is None:
            return True
        projected = public_metadata(metadata) if metadata is not None else None
        try:
            return bool(self._access_policy.allows(
                operation=operation,
                context=context,
                metadata=projected,
            ))
        except Exception as exc:
            raise AccessDeniedError(
                "The access policy could not authorize the operation",
                document_id=projected.document_id if projected is not None else None,
            ) from exc

    def _require_access(
        self,
        operation: str,
        context: AccessContext | None,
        metadata: DocumentMetadata | PublicDocumentMetadata | None,
    ) -> None:
        if self._allows(operation, context, metadata):
            return
        projected = public_metadata(metadata) if metadata is not None else None
        raise AccessDeniedError(
            "Access to the document operation was denied",
            document_id=projected.document_id if projected is not None else None,
        )

    def _log_info(self, event: str, **context: object) -> None:
        self._logger.info(event, extra=build_log_extra(event, context))

    def _run_observed(
        self,
        operation: str,
        callback: Callable[[], ObservedResult],
        *,
        document_id: str | None = None,
        conditions: ObserverConditions | None = None,
    ) -> ObservedResult:
        started_at = datetime.now(UTC)
        try:
            result = callback()
        except Exception as exc:
            self._notify_observer(OperationEvent(
                operation=operation,
                succeeded=False,
                document_id=document_id,
                conditions=self._resolve_observer_conditions(conditions, exc),
                error_code=exc.code if isinstance(exc, DmsError) else "unexpected_error",
                started_at=started_at,
                completed_at=datetime.now(UTC),
            ))
            raise
        result_document_id = getattr(result, "document_id", None)
        self._notify_observer(OperationEvent(
            operation=operation,
            succeeded=True,
            document_id=(
                result_document_id
                if isinstance(result_document_id, str)
                else document_id
            ),
            conditions=self._resolve_observer_conditions(conditions, result),
            error_code=None,
            started_at=started_at,
            completed_at=datetime.now(UTC),
        ))
        return result

    @staticmethod
    def _resolve_observer_conditions(
        conditions: ObserverConditions | None,
        outcome: object,
    ) -> Mapping[str, object]:
        if conditions is None:
            return {}
        if callable(conditions):
            return conditions(outcome)
        return conditions

    def _notify_observer(self, event: OperationEvent) -> None:
        if self._operation_observer is None:
            return
        try:
            self._operation_observer(event)
        except Exception:
            self._logger.warning(
                "sdk.operation_observer.failed",
                extra={"dms_event": "sdk.operation_observer.failed"},
                exc_info=True,
            )

class ScopedDocumentManagementSDK:
    """An immutable per-operation facade that never mutates the shared SDK."""

    def __init__(
        self,
        sdk: DefaultDocumentManagementSDK,
        context: DmsOperationContext,
    ) -> None:
        self._sdk = sdk
        self.context = context

    def _metadata(self, metadata: Mapping[str, object] | None) -> dict[str, object]:
        return {**self.context.default_metadata, **dict(metadata or {})}

    def _created_by(self, created_by: str | None) -> str | None:
        return created_by if created_by is not None else self.context.created_by

    def _idempotency_scope(self, scope: str | None) -> str | None:
        return scope if scope is not None else self.context.idempotency_scope

    def _call(
        self,
        method: Callable[..., ObservedResult],
        *args: object,
        **kwargs: object,
    ) -> ObservedResult:
        return method(*args, access_context=self.context.access, **kwargs)

    def upload_document(self, request: UploadDocumentRequest) -> UploadDocumentResult:
        return self._sdk.upload_document(replace(
            request,
            metadata=self._metadata(request.metadata),
            created_by=self._created_by(request.created_by),
            idempotency_scope=self._idempotency_scope(request.idempotency_scope),
        ))

    def upload_document_stream(
        self,
        request: UploadDocumentStreamRequest,
    ) -> UploadDocumentResult:
        return self._sdk.upload_document_stream(replace(
            request,
            metadata=self._metadata(request.metadata),
            created_by=self._created_by(request.created_by),
        ))

    def get_upload_operation(
        self,
        *,
        idempotency_key: str,
        scope: str | None = None,
    ) -> UploadOperationResult:
        resolved_scope = self._idempotency_scope(scope)
        if resolved_scope is None:
            raise ValidationError("idempotency scope is required")
        return self._sdk.get_upload_operation(
            scope=resolved_scope,
            idempotency_key=idempotency_key,
        )

    def upload_file(
        self,
        path: str | Path,
        *,
        filename: str | None = None,
        content_type: str | None = None,
        document_id: str | None = None,
        metadata: Mapping[str, object] | None = None,
        created_by: str | None = None,
    ) -> UploadDocumentResult:
        return self._sdk.upload_file(
            path,
            filename=filename,
            content_type=content_type,
            document_id=document_id,
            metadata=self._metadata(metadata),
            created_by=self._created_by(created_by),
        )

    def get_document_metadata(self, document_id: str) -> PublicDocumentMetadata:
        return self._call(self._sdk.get_document_metadata, document_id)

    def get_internal_document_metadata(self, document_id: str) -> DocumentMetadata:
        return self._call(self._sdk.get_internal_document_metadata, document_id)

    def list_documents(
        self,
        *,
        cursor: str | None = None,
        limit: int = 100,
        status: DocumentStatus | None = None,
    ) -> DocumentPage:
        return self._call(
            self._sdk.list_documents,
            cursor=cursor,
            limit=limit,
            status=status,
        )

    def list_documents_page(
        self,
        *,
        cursor: str | None = None,
        limit: int = 100,
        status: DocumentStatus | None = None,
    ) -> DocumentPage:
        return self._call(
            self._sdk.list_documents_page,
            cursor=cursor,
            limit=limit,
            status=status,
        )

    def iter_documents(
        self,
        *,
        status: DocumentStatus | None = None,
        page_size: int = 100,
    ) -> Iterator[PublicDocumentMetadata]:
        return self._call(
            self._sdk.iter_documents,
            status=status,
            page_size=page_size,
        )

    def get_document_content(self, document_id: str) -> DocumentContent:
        return self._call(self._sdk.get_document_content, document_id)

    async def get_document_content_async_stream(
        self,
        document_id: str,
        *,
        chunk_size: int = 65536,
    ) -> AsyncDocumentContentStream:
        return await self._sdk.get_document_content_async_stream(
            document_id,
            chunk_size=chunk_size,
            access_context=self.context.access,
        )

    def get_document_content_stream(
        self,
        document_id: str,
        *,
        chunk_size: int = 65536,
    ) -> DocumentContentStream:
        return self._call(
            self._sdk.get_document_content_stream,
            document_id,
            chunk_size=chunk_size,
        )

    def iter_document_chunks(
        self,
        document_id: str,
        *,
        chunk_size: int = 65536,
    ) -> Iterator[bytes]:
        return self._call(
            self._sdk.iter_document_chunks,
            document_id,
            chunk_size=chunk_size,
        )

    def copy_document_to(
        self,
        document_id: str,
        sink: BinaryIO,
        *,
        chunk_size: int = 65536,
        verify_checksum: bool = True,
    ) -> DocumentCopyResult:
        return self._call(
            self._sdk.copy_document_to,
            document_id,
            sink,
            chunk_size=chunk_size,
            verify_checksum=verify_checksum,
        )

    def delete_document(
        self,
        document_id: str,
        *,
        hard_delete: bool = False,
    ) -> DeleteDocumentResult:
        return self._call(
            self._sdk.delete_document,
            document_id,
            hard_delete=hard_delete,
        )

    def soft_delete_document(self, document_id: str) -> DeleteDocumentResult:
        return self._call(self._sdk.soft_delete_document, document_id)

    def hard_delete_document(self, document_id: str) -> DeleteDocumentResult:
        return self._call(self._sdk.hard_delete_document, document_id)

    def clear_all_data(self) -> DataResetResult:
        return self._call(self._sdk.clear_all_data)

    def initialize_for_data_load(self) -> DataResetResult:
        return self._call(self._sdk.initialize_for_data_load)

    def inspect_document(self, document_id: str) -> DocumentInspection:
        return self._call(self._sdk.inspect_document, document_id)

    def list_recovery_candidates(
        self,
        *,
        status: DocumentStatus,
        offset: int = 0,
        limit: int = 100,
    ) -> list[DocumentMetadata]:
        return self._call(
            self._sdk.list_recovery_candidates,
            status=status,
            offset=offset,
            limit=limit,
        )

    def iter_recovery_candidates(
        self,
        *,
        status: DocumentStatus,
        page_size: int = 100,
    ) -> Iterator[DocumentMetadata]:
        return self._call(
            self._sdk.iter_recovery_candidates,
            status=status,
            page_size=page_size,
        )

    def reconcile_document(
        self,
        document_id: str,
        action: RecoveryAction,
        *,
        storage_key: str | None = None,
        dry_run: bool = False,
        actor: str | None = None,
    ) -> ReconciliationResult:
        return self._call(
            self._sdk.reconcile_document,
            document_id,
            action,
            storage_key=storage_key,
            dry_run=dry_run,
            actor=actor if actor is not None else self.context.audit_actor,
        )

    def execute_reconciliation_plan(
        self,
        plan: ReconciliationPlan,
        *,
        actor: str | None = None,
    ) -> BatchReconciliationResult:
        return self._call(
            self._sdk.execute_reconciliation_plan,
            plan,
            actor=actor if actor is not None else self.context.audit_actor,
        )

    def reconcile_documents(
        self,
        *,
        status: DocumentStatus,
        action: RecoveryAction,
        offset: int = 0,
        limit: int = 100,
        dry_run: bool = False,
        actor: str | None = None,
    ) -> BatchReconciliationResult:
        return self._call(
            self._sdk.reconcile_documents,
            status=status,
            action=action,
            offset=offset,
            limit=limit,
            dry_run=dry_run,
            actor=actor if actor is not None else self.context.audit_actor,
        )

    def check_health(self) -> HealthStatus:
        return self._sdk.check_health()
