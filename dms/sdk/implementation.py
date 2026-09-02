from __future__ import annotations

import asyncio
import hashlib
import logging
import mimetypes
from collections.abc import Callable, Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO, TypeAlias, TypeVar

from dms.domain.interfaces import MetadataStore, ObjectStore, UploadOperationStore
from dms.domain.models import DocumentMetadata, DocumentPartition, DocumentStatus
from dms.sdk.contracts import (
    DocumentCopyResult,
    OperationEvent,
    OperationObserver,
    _LoggingMixin,
    _validate_partition,
    build_log_extra,
    partition_operation_scope_prefix,
)
from dms.sdk.documents import (
    DocumentService,
)
from dms.sdk.errors import (
    ConsistencyError,
    DataResetError,
    DmsError,
    StorageError,
    ValidationError,
)
from dms.sdk.reconciliation import ReconciliationCoordinator
from dms.sdk.types import (
    AsyncDocumentContentStream,
    BatchReconciliationResult,
    DataResetResult,
    DeleteDocumentResult,
    DocumentContent,
    DocumentContentStream,
    DocumentInspection,
    DocumentPage,
    PublicDocumentMetadata,
    ReconciliationPlan,
    ReconciliationResult,
    RecoveryAction,
    RecoveryAuditEvent,
    UploadDocumentRequest,
    UploadDocumentResult,
    UploadDocumentStreamRequest,
    UploadOperationResult,
)
from dms.sdk.upload import UploadService

ObservedResult = TypeVar("ObservedResult")
ObserverConditions: TypeAlias = (
    Mapping[str, object] | Callable[[object], Mapping[str, object]]
)


class DefaultDocumentManagementSDK(_LoggingMixin):
    def __init__(
        self,
        *,
        metadata_store: MetadataStore,
        object_store: ObjectStore,
        logger: logging.Logger | None = None,
        max_file_size: int | None = None,
        operation_store: UploadOperationStore | None = None,
        recovery_audit_hook: Callable[[RecoveryAuditEvent], object] | None = None,
        operation_observer: OperationObserver | None = None,
    ) -> None:
        self._metadata_store = metadata_store
        self._object_store = object_store
        self._logger = logger or logging.getLogger("dms.sdk")
        if max_file_size is not None and max_file_size <= 0:
            raise ValidationError("max_file_size must be positive")
        self._operation_store = operation_store
        self._recovery_audit_hook = recovery_audit_hook
        self._operation_observer = operation_observer
        self._documents = DocumentService(
            metadata_store=metadata_store,
            object_store=object_store,
            logger=self._logger,
        )
        self._uploads = UploadService(
            metadata_store=metadata_store,
            object_store=object_store,
            logger=self._logger,
            max_file_size=max_file_size,
            operation_store=operation_store,
            get_internal_metadata=self.get_internal_document_metadata,
        )
        self._reconciliation = ReconciliationCoordinator(
            metadata_store=metadata_store,
            object_store=object_store,
            inspect_override=lambda document_id, **kwargs: self.inspect_document(
                document_id,
                **kwargs,
            ),
            reconcile_override=lambda document_id, action, **kwargs: (
                self.reconcile_document(
                    document_id,
                    action,
                    **kwargs,
                )
            ),
            list_candidates=self.list_recovery_candidates,
            get_metadata=self.get_internal_document_metadata,
            set_failed=self._set_document_status,
            emit_audit=self._emit_recovery_audit,
        )

    def upload_document(
        self,
        request: UploadDocumentRequest,
        *,
        partition: DocumentPartition,
    ) -> UploadDocumentResult:
        return self._run_observed(
            "upload",
            lambda: self._uploads.upload_document(request, partition=partition),
            document_id=request.document_id,
        )

    def upload_file(
        self,
        path: str | Path,
        *,
        filename: str | None = None,
        content_type: str | None = None,
        document_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        created_by: str | None = None,
        partition: DocumentPartition,
    ) -> UploadDocumentResult:
        _validate_partition(partition)
        source_path = Path(path)
        resolved_filename = source_path.name if filename is None else filename
        resolved_content_type = (
            content_type
            if content_type is not None
            else (
                mimetypes.guess_type(resolved_filename)[0] or "application/octet-stream"
            )
        )

        try:
            size = source_path.stat().st_size
            with source_path.open("rb") as stream:
                return self.upload_document_stream(
                    UploadDocumentStreamRequest(
                        stream=stream,
                        size=size,
                        filename=resolved_filename,
                        content_type=resolved_content_type,
                        document_id=document_id,
                        metadata=metadata,
                        created_by=created_by,
                    ),
                    partition=partition,
                )
        except OSError as exc:
            raise StorageError(
                f"Failed to read document file: {source_path}",
                document_id=document_id,
            ) from exc

    def upload_document_stream(
        self,
        request: UploadDocumentStreamRequest,
        *,
        partition: DocumentPartition,
    ) -> UploadDocumentResult:
        return self._run_observed(
            "upload",
            lambda: self._uploads.upload_document_stream(
                request,
                partition=partition,
            ),
            document_id=request.document_id,
        )

    def get_upload_operation(
        self,
        *,
        scope: str,
        idempotency_key: str,
        partition: DocumentPartition,
    ) -> UploadOperationResult:
        return self._uploads.get_upload_operation(
            scope=scope,
            idempotency_key=idempotency_key,
            partition=partition,
        )

    def get_internal_document_metadata(
        self,
        document_id: str,
        *,
        partition: DocumentPartition,
    ) -> DocumentMetadata:
        """Return storage-bearing metadata for administration and recovery."""
        return self._run_observed(
            "metadata.internal",
            lambda: self._documents.get_internal_metadata(
                document_id,
                partition=partition,
            ),
            document_id=document_id,
        )

    def get_document_metadata(
        self,
        document_id: str,
        *,
        partition: DocumentPartition,
    ) -> PublicDocumentMetadata:
        return self._run_observed(
            "metadata.get",
            lambda: self._documents.get_metadata(
                document_id,
                partition=partition,
            ),
            document_id=document_id,
        )

    def list_documents(
        self,
        *,
        partition: DocumentPartition,
        cursor: str | None = None,
        limit: int = 100,
        status: DocumentStatus | None = None,
    ) -> DocumentPage:
        return self.list_documents_page(
            cursor=cursor,
            limit=limit,
            status=status,
            partition=partition,
        )

    def _list_internal_documents(
        self,
        *,
        partition: DocumentPartition,
        offset: int = 0,
        limit: int = 100,
        status: DocumentStatus | None = None,
        excluded_statuses: tuple[DocumentStatus, ...] = (),
    ) -> list[DocumentMetadata]:
        return self._documents.list_internal(
            partition=partition,
            offset=offset,
            limit=limit,
            status=status,
            excluded_statuses=excluded_statuses,
        )

    def list_documents_page(
        self,
        *,
        partition: DocumentPartition,
        cursor: str | None = None,
        limit: int = 100,
        status: DocumentStatus | None = None,
    ) -> DocumentPage:
        return self._run_observed(
            "documents.list",
            lambda: self._list_documents_page(
                cursor=cursor,
                limit=limit,
                status=status,
                partition=partition,
            ),
            conditions={
                "limit": limit,
                "status": getattr(status, "value", status),
            },
        )

    def _list_documents_page(
        self,
        *,
        partition: DocumentPartition,
        cursor: str | None = None,
        limit: int = 100,
        status: DocumentStatus | None = None,
    ) -> DocumentPage:
        return self._documents.list_page(
            partition=partition,
            cursor=cursor,
            limit=limit,
            status=status,
        )

    def iter_documents(
        self,
        *,
        partition: DocumentPartition,
        status: DocumentStatus | None = None,
        page_size: int = 100,
    ) -> Iterator[PublicDocumentMetadata]:
        cursor: str | None = None
        while True:
            page = self.list_documents(
                cursor=cursor,
                limit=page_size,
                status=status,
                partition=partition,
            )
            yield from page.items
            if page.next_cursor is None:
                return
            cursor = page.next_cursor

    def inspect_document(
        self,
        document_id: str,
        *,
        partition: DocumentPartition,
    ) -> DocumentInspection:
        """Inspect consistency inside one exact partition."""
        return self._run_observed(
            "document.inspect",
            lambda: self._reconciliation.inspect_document(
                document_id,
                partition=partition,
            ),
            document_id=document_id,
        )

    def _list_recovery_candidates(
        self,
        *,
        status: DocumentStatus,
        partition: DocumentPartition,
        offset: int = 0,
        limit: int = 100,
    ) -> list[DocumentMetadata]:
        self._validate_recovery_page(status=status, offset=offset, limit=limit)
        return self._list_internal_documents(
            partition=partition,
            offset=offset,
            limit=limit,
            status=status,
        )

    def list_recovery_candidates(
        self,
        *,
        partition: DocumentPartition,
        status: DocumentStatus,
        offset: int = 0,
        limit: int = 100,
    ) -> list[DocumentMetadata]:
        return self._run_observed(
            "recovery.list",
            lambda: self._list_recovery_candidates(
                partition=partition,
                status=status,
                offset=offset,
                limit=limit,
            ),
            conditions={
                "status": getattr(status, "value", status),
                "offset": offset,
                "limit": limit,
            },
        )

    def iter_recovery_candidates(
        self,
        *,
        partition: DocumentPartition,
        status: DocumentStatus,
        page_size: int = 100,
    ) -> Iterator[DocumentMetadata]:
        offset = 0
        while True:
            items = self.list_recovery_candidates(
                status=status,
                offset=offset,
                limit=page_size,
                partition=partition,
            )
            if not items:
                return
            yield from items
            if len(items) < page_size:
                return
            offset += len(items)

    def reconcile_document(
        self,
        document_id: str,
        action: RecoveryAction,
        *,
        storage_key: str | None = None,
        dry_run: bool = False,
        actor: str | None = None,
        partition: DocumentPartition,
    ) -> ReconciliationResult:
        return self._run_observed(
            "recovery.execute",
            lambda: self._reconciliation.reconcile_document(
                document_id,
                action,
                storage_key=storage_key,
                dry_run=dry_run,
                actor=actor,
                partition=partition,
            ),
            document_id=document_id,
            conditions={"action": getattr(action, "value", action), "dry_run": dry_run},
        )

    def execute_reconciliation_plan(
        self,
        plan: ReconciliationPlan,
        *,
        partition: DocumentPartition,
        actor: str | None = None,
    ) -> BatchReconciliationResult:
        return self._run_observed(
            "recovery.plan.execute",
            lambda: self._reconciliation.execute_reconciliation_plan(
                plan,
                actor=actor,
                partition=partition,
            ),
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

    def reconcile_documents(
        self,
        *,
        status: DocumentStatus,
        action: RecoveryAction,
        offset: int = 0,
        limit: int = 100,
        dry_run: bool = False,
        actor: str | None = None,
        partition: DocumentPartition,
    ) -> BatchReconciliationResult:
        def reconcile_batch() -> BatchReconciliationResult:
            if not isinstance(action, RecoveryAction):
                raise ValidationError("action must be a RecoveryAction")
            candidates = self.list_recovery_candidates(
                status=status,
                offset=offset,
                limit=limit,
                partition=partition,
            )
            return self._reconciliation.reconcile_documents(
                status=status,
                action=action,
                offset=offset,
                limit=limit,
                dry_run=dry_run,
                actor=actor,
                partition=partition,
                candidates=candidates,
            )

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
    def _validate_recovery_page(
        *, status: DocumentStatus, offset: int, limit: int
    ) -> None:
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
        partition: DocumentPartition,
    ) -> DocumentContent:
        return self._run_observed(
            "content.get",
            lambda: self._documents.get_content(
                document_id,
                partition=partition,
            ),
            document_id=document_id,
        )

    def get_document_content_stream(
        self,
        document_id: str,
        *,
        chunk_size: int = 65536,
        partition: DocumentPartition,
    ) -> DocumentContentStream:
        if chunk_size <= 0:
            raise ValidationError("chunk_size must be positive")
        return self._run_observed(
            "content.stream",
            lambda: self._documents.get_content_stream(
                document_id,
                chunk_size=chunk_size,
                partition=partition,
            ),
            document_id=document_id,
            conditions={"chunk_size": chunk_size},
        )

    def iter_document_chunks(
        self,
        document_id: str,
        *,
        chunk_size: int = 65536,
        partition: DocumentPartition,
    ) -> Iterator[bytes]:
        source = self.get_document_content_stream(
            document_id,
            chunk_size=chunk_size,
            partition=partition,
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
        partition: DocumentPartition,
    ) -> DocumentCopyResult:
        metadata = self._documents.get_internal_metadata(
            document_id,
            partition=partition,
        )
        source = self.get_document_content_stream(
            document_id,
            chunk_size=chunk_size,
            partition=partition,
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
        partition: DocumentPartition,
    ) -> AsyncDocumentContentStream:
        open_task = asyncio.create_task(
            asyncio.to_thread(
                self.get_document_content_stream,
                document_id,
                chunk_size=chunk_size,
                partition=partition,
            )
        )
        try:
            source = await asyncio.shield(open_task)
        except asyncio.CancelledError:
            source = await open_task
            await asyncio.to_thread(source.close)
            raise
        return AsyncDocumentContentStream(
            document_id=document_id, _source=source, chunk_size=chunk_size
        )

    def delete_document(
        self,
        document_id: str,
        *,
        partition: DocumentPartition,
        hard_delete: bool = False,
    ) -> DeleteDocumentResult:
        return self._run_observed(
            "document.delete",
            lambda: self._documents.delete(
                document_id,
                hard_delete=hard_delete,
                partition=partition,
            ),
            document_id=document_id,
            conditions={"hard_delete": hard_delete},
        )

    def soft_delete_document(
        self,
        document_id: str,
        *,
        partition: DocumentPartition,
    ) -> DeleteDocumentResult:
        return self.delete_document(
            document_id,
            hard_delete=False,
            partition=partition,
        )

    def hard_delete_document(
        self,
        document_id: str,
        *,
        partition: DocumentPartition,
    ) -> DeleteDocumentResult:
        return self.delete_document(
            document_id,
            hard_delete=True,
            partition=partition,
        )

    def clear_all_data(self) -> DataResetResult:
        return self._reset_data(operation="data.clear_all", partition=None)

    def clear_partition_data(
        self,
        *,
        partition: DocumentPartition,
    ) -> DataResetResult:
        if not isinstance(partition, DocumentPartition):
            raise ValidationError("partition must be a DocumentPartition")
        return self._reset_data(
            operation="data.clear_partition",
            partition=partition,
        )

    def initialize_for_data_load(self) -> DataResetResult:
        """Clear all DMS-owned data for a fresh load."""
        return self._reset_data(
            operation="data.initialize_for_data_load",
            partition=None,
        )

    def initialize_partition_for_data_load(
        self,
        *,
        partition: DocumentPartition,
    ) -> DataResetResult:
        """Clear one partition and leave it ready for a fresh load."""
        if not isinstance(partition, DocumentPartition):
            raise ValidationError("partition must be a DocumentPartition")
        return self._reset_data(
            operation="data.initialize_partition_for_data_load",
            partition=partition,
        )

    def _reset_data(
        self,
        *,
        operation: str,
        partition: DocumentPartition | None,
    ) -> DataResetResult:
        def reset() -> DataResetResult:
            counts: dict[str, int] = {}
            errors: list[Exception] = []
            failed_stores: list[str] = []
            if partition is None:
                stores: list[tuple[str, Callable[[], int]]] = [
                    ("objects", self._object_store.clear_all),
                    ("metadata", self._metadata_store.clear_all),
                ]
                if self._operation_store is not None:
                    stores.append(
                        ("upload_operations", self._operation_store.clear_all)
                    )
            else:
                stores = [
                    (
                        "objects",
                        lambda: self._object_store.clear_partition(
                            partition=partition,
                        ),
                    ),
                    (
                        "metadata",
                        lambda: self._metadata_store.clear_partition(
                            partition=partition,
                        ),
                    ),
                ]
                if self._operation_store is not None:
                    scope_prefix = partition_operation_scope_prefix(partition)
                    stores.append(
                        (
                            "upload_operations",
                            lambda: self._operation_store.clear_all(
                                scope_prefix=scope_prefix
                            ),
                        )
                    )
            for name, clear_all in stores:
                try:
                    counts[name] = clear_all()
                except Exception as exc:  # noqa: BLE001 - aggregate arbitrary store failures
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
            self._notify_observer(
                OperationEvent(
                    operation=operation,
                    succeeded=False,
                    document_id=document_id,
                    conditions=self._resolve_observer_conditions(conditions, exc),
                    error_code=exc.code
                    if isinstance(exc, DmsError)
                    else "unexpected_error",
                    started_at=started_at,
                    completed_at=datetime.now(UTC),
                )
            )
            raise
        result_document_id = getattr(result, "document_id", None)
        self._notify_observer(
            OperationEvent(
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
            )
        )
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
