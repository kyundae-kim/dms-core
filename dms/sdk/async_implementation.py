from __future__ import annotations

import asyncio
import hashlib
import inspect
import logging
import mimetypes
from collections.abc import Awaitable, Callable, Mapping
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO, TypeVar

from dms.domain.interfaces import (
    AsyncMetadataStore,
    AsyncObjectStore,
    AsyncUploadOperationStore,
)
from dms.domain.models import DocumentMetadata, DocumentPartition, DocumentStatus
from dms.sdk.contracts import (
    AccessContext,
    AccessPolicy,
    DocumentCopyResult,
    OperationEvent,
    OperationObserver,
    _enforce_access_async,
    _LoggingMixin,
    _validate_partition,
    build_log_extra,
    partition_operation_scope_prefix,
)
from dms.sdk.documents import (
    AsyncDocumentService,
)
from dms.sdk.errors import (
    ConsistencyError,
    DataResetError,
    DmsError,
    DocumentNotFoundError,
    StorageError,
    ValidationError,
)
from dms.sdk.reconciliation import AsyncReconciliationCoordinator
from dms.sdk.types import (
    AsyncDocumentContentStream,
    BatchReconciliationResult,
    DataResetResult,
    DeleteDocumentResult,
    DocumentContent,
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
from dms.sdk.upload import AsyncUploadService

_ResultT = TypeVar("_ResultT")
_recovery_access_context: ContextVar[AccessContext | None] = ContextVar(
    "dms_async_recovery_access_context",
    default=None,
)


class AsyncDocumentManagementCore(_LoggingMixin):
    """Async application core using async storage ports for every operation."""

    def __init__(
        self,
        *,
        metadata_store: AsyncMetadataStore,
        object_store: AsyncObjectStore,
        operation_store: AsyncUploadOperationStore | None = None,
        logger: logging.Logger | None = None,
        max_file_size: int | None = None,
        recovery_audit_hook: Callable[[RecoveryAuditEvent], object] | None = None,
        access_policy: AccessPolicy | None = None,
        operation_observer: OperationObserver | None = None,
    ) -> None:
        self._metadata_store = metadata_store
        self._object_store = object_store
        self._operation_store = operation_store
        self._logger = logger or logging.getLogger("dms.sdk")
        if max_file_size is not None and max_file_size <= 0:
            raise ValidationError("max_file_size must be positive")
        self._recovery_audit_hook = recovery_audit_hook
        self._access_policy = access_policy
        self._operation_observer = operation_observer
        self._documents = AsyncDocumentService(
            metadata_store=metadata_store,
            object_store=object_store,
            logger=self._logger,
        )
        self._uploads = AsyncUploadService(
            metadata_store=metadata_store,
            object_store=object_store,
            logger=self._logger,
            max_file_size=max_file_size,
            operation_store=operation_store,
            get_internal_metadata=self._get_internal_document_metadata_unchecked,
        )
        self._reconciliation = AsyncReconciliationCoordinator(
            metadata_store=metadata_store,
            object_store=object_store,
            inspect_override=self._reconciliation_inspect,
            reconcile_override=self._reconciliation_reconcile,
            list_candidates=self._list_recovery_candidates,
            get_metadata=self._reconciliation_metadata,
            set_failed=self._set_document_status,
            emit_audit=self._emit_recovery_audit,
        )

    async def _get_internal_document_metadata_unchecked(
        self,
        document_id: str,
        *,
        partition: DocumentPartition,
    ) -> DocumentMetadata:
        return await self._documents.get_internal_metadata(
            document_id,
            partition=partition,
        )

    @staticmethod
    def _effective_access_context(
        access_context: AccessContext | None,
    ) -> AccessContext | None:
        return access_context or _recovery_access_context.get()

    async def _require_access(
        self,
        operation: str,
        access_context: AccessContext | None,
        metadata: DocumentMetadata | PublicDocumentMetadata | None,
    ) -> None:
        await _enforce_access_async(
            self._access_policy,
            operation=operation,
            context=self._effective_access_context(access_context),
            metadata=metadata,
        )

    async def upload_document(
        self,
        request: UploadDocumentRequest,
        *,
        partition: DocumentPartition,
        access_context: AccessContext | None = None,
    ) -> UploadDocumentResult:
        async def upload() -> UploadDocumentResult:
            await self._require_access("upload", access_context, None)
            return await self._uploads.upload_document(
                request,
                partition=partition,
            )

        return await self._run_observed(
            "upload",
            upload,
            document_id=request.document_id,
        )

    async def upload_file(
        self,
        path: str | Path,
        *,
        filename: str | None = None,
        content_type: str | None = None,
        document_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        created_by: str | None = None,
        partition: DocumentPartition,
        access_context: AccessContext | None = None,
    ) -> UploadDocumentResult:
        _validate_partition(partition)
        await self._require_access("upload", access_context, None)
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
            size = (await asyncio.to_thread(source_path.stat)).st_size
            stream = await asyncio.to_thread(source_path.open, "rb")
            try:
                return await self.upload_document_stream(
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
                    access_context=access_context,
                )
            finally:
                await asyncio.to_thread(stream.close)
        except OSError as exc:
            raise StorageError(
                f"Failed to read document file: {source_path}",
                document_id=document_id,
            ) from exc

    async def upload_document_stream(
        self,
        request: UploadDocumentStreamRequest,
        *,
        partition: DocumentPartition,
        access_context: AccessContext | None = None,
    ) -> UploadDocumentResult:
        async def upload() -> UploadDocumentResult:
            await self._require_access("upload", access_context, None)
            return await self._uploads.upload_document_stream(
                request,
                partition=partition,
            )

        return await self._run_observed(
            "upload",
            upload,
            document_id=request.document_id,
        )

    async def get_upload_operation(
        self,
        *,
        scope: str,
        idempotency_key: str,
        partition: DocumentPartition,
        access_context: AccessContext | None = None,
    ) -> UploadOperationResult:
        await self._require_access("upload.operation.get", access_context, None)
        return await self._uploads.get_upload_operation(
            scope=scope,
            idempotency_key=idempotency_key,
            partition=partition,
        )

    async def get_internal_document_metadata(
        self,
        document_id: str,
        *,
        partition: DocumentPartition,
        access_context: AccessContext | None = None,
    ) -> DocumentMetadata:
        async def get_metadata() -> DocumentMetadata:
            metadata = await self._documents.get_internal_metadata(
                document_id,
                partition=partition,
            )
            await self._require_access("metadata.internal", access_context, metadata)
            return metadata

        return await self._run_observed(
            "metadata.internal",
            get_metadata,
            document_id=document_id,
        )

    async def get_document_metadata(
        self,
        document_id: str,
        *,
        partition: DocumentPartition,
        access_context: AccessContext | None = None,
    ) -> PublicDocumentMetadata:
        async def get_metadata() -> PublicDocumentMetadata:
            metadata = await self._documents.get_metadata(
                document_id,
                partition=partition,
            )
            await self._require_access("metadata.get", access_context, metadata)
            return metadata

        return await self._run_observed(
            "metadata.get",
            get_metadata,
            document_id=document_id,
        )

    async def list_documents_page(
        self,
        *,
        partition: DocumentPartition,
        cursor: str | None = None,
        limit: int = 100,
        status: DocumentStatus | None = None,
        access_context: AccessContext | None = None,
    ) -> DocumentPage:
        return await self._run_observed(
            "documents.list",
            lambda: self._list_documents_page(
                cursor=cursor,
                limit=limit,
                status=status,
                partition=partition,
                access_context=access_context,
            ),
            conditions={
                "limit": limit,
                "status": getattr(status, "value", status),
            },
        )

    async def list_documents(
        self,
        *,
        partition: DocumentPartition,
        cursor: str | None = None,
        limit: int = 100,
        status: DocumentStatus | None = None,
        access_context: AccessContext | None = None,
    ) -> DocumentPage:
        return await self.list_documents_page(
            cursor=cursor,
            limit=limit,
            status=status,
            partition=partition,
            access_context=access_context,
        )

    async def _list_documents_page(
        self,
        *,
        partition: DocumentPartition,
        cursor: str | None,
        limit: int,
        status: DocumentStatus | None,
        access_context: AccessContext | None,
    ) -> DocumentPage:
        await self._require_access("documents.list", access_context, None)
        return await self._documents.list_page(
            partition=partition,
            cursor=cursor,
            limit=limit,
            status=status,
        )

    async def inspect_document(
        self,
        document_id: str,
        *,
        partition: DocumentPartition,
        access_context: AccessContext | None = None,
    ) -> DocumentInspection:
        effective_access_context = self._effective_access_context(access_context)

        async def inspect() -> DocumentInspection:
            inspection = await self._reconciliation.inspect_document(
                document_id,
                partition=partition,
            )
            metadata = (
                await self._get_internal_document_metadata_unchecked(
                    document_id,
                    partition=partition,
                )
                if inspection.metadata_exists
                else None
            )
            await self._require_access(
                "document.inspect",
                effective_access_context,
                metadata,
            )
            return inspection

        return await self._run_observed(
            "document.inspect",
            inspect,
            document_id=document_id,
        )

    async def _list_recovery_candidates(
        self,
        *,
        partition: DocumentPartition,
        status: DocumentStatus,
        offset: int = 0,
        limit: int = 100,
    ) -> list[DocumentMetadata]:
        self._validate_recovery_page(status=status, offset=offset, limit=limit)
        return await self._documents.list_internal(
            partition=partition,
            offset=offset,
            limit=limit,
            status=status,
        )

    async def list_recovery_candidates(
        self,
        *,
        partition: DocumentPartition,
        status: DocumentStatus,
        offset: int = 0,
        limit: int = 100,
        access_context: AccessContext | None = None,
    ) -> list[DocumentMetadata]:
        async def list_candidates() -> list[DocumentMetadata]:
            await self._require_access("recovery.list", access_context, None)
            return await self._list_recovery_candidates(
                partition=partition,
                status=status,
                offset=offset,
                limit=limit,
            )

        return await self._run_observed(
            "recovery.list",
            list_candidates,
            conditions={
                "status": getattr(status, "value", status),
                "offset": offset,
                "limit": limit,
            },
        )

    async def reconcile_document(
        self,
        document_id: str,
        action: RecoveryAction,
        *,
        storage_key: str | None = None,
        dry_run: bool = False,
        actor: str | None = None,
        partition: DocumentPartition,
        access_context: AccessContext | None = None,
    ) -> ReconciliationResult:
        effective_access_context = self._effective_access_context(access_context)

        async def reconcile() -> ReconciliationResult:
            if self._access_policy is not None:
                metadata: DocumentMetadata | None
                try:
                    metadata = await self._get_internal_document_metadata_unchecked(
                        document_id,
                        partition=partition,
                    )
                except DocumentNotFoundError:
                    metadata = None
                await self._require_access(
                    "recovery.execute",
                    effective_access_context,
                    metadata,
                )
            token = _recovery_access_context.set(effective_access_context)
            try:
                return await self._reconciliation.reconcile_document(
                    document_id,
                    action,
                    storage_key=storage_key,
                    dry_run=dry_run,
                    actor=actor,
                    partition=partition,
                )
            finally:
                _recovery_access_context.reset(token)

        return await self._run_observed(
            "recovery.execute",
            reconcile,
            document_id=document_id,
            conditions={
                "action": getattr(action, "value", action),
                "dry_run": dry_run,
            },
        )

    async def execute_reconciliation_plan(
        self,
        plan: ReconciliationPlan,
        *,
        partition: DocumentPartition,
        actor: str | None = None,
        access_context: AccessContext | None = None,
    ) -> BatchReconciliationResult:
        effective_access_context = self._effective_access_context(access_context)

        async def execute() -> BatchReconciliationResult:
            if self._access_policy is not None:
                if not isinstance(plan, ReconciliationPlan):
                    raise ValidationError("plan must be a ReconciliationPlan")
                if plan.partition != partition:
                    raise ValidationError(
                        "reconciliation plan partition does not match request"
                    )
                for item in plan.items:
                    try:
                        metadata = await self._get_internal_document_metadata_unchecked(
                            item.document_id,
                            partition=partition,
                        )
                    except DocumentNotFoundError:
                        metadata = None
                    await self._require_access(
                        "recovery.execute",
                        effective_access_context,
                        metadata,
                    )
            token = _recovery_access_context.set(effective_access_context)
            try:
                return await self._reconciliation.execute_reconciliation_plan(
                    plan,
                    actor=actor,
                    partition=partition,
                )
            finally:
                _recovery_access_context.reset(token)

        return await self._run_observed(
            "recovery.plan.execute",
            execute,
            conditions={"item_count": len(getattr(plan, "items", ()))},
        )

    async def reconcile_documents(
        self,
        *,
        status: DocumentStatus,
        action: RecoveryAction,
        offset: int = 0,
        limit: int = 100,
        dry_run: bool = False,
        actor: str | None = None,
        partition: DocumentPartition,
        access_context: AccessContext | None = None,
    ) -> BatchReconciliationResult:
        async def reconcile_batch() -> BatchReconciliationResult:
            if not isinstance(action, RecoveryAction):
                raise ValidationError("action must be a RecoveryAction")
            await self._require_access("recovery.execute", access_context, None)
            candidates = await self.list_recovery_candidates(
                status=status,
                offset=offset,
                limit=limit,
                partition=partition,
                access_context=access_context,
            )
            token = _recovery_access_context.set(
                self._effective_access_context(access_context)
            )
            try:
                return await self._reconciliation.reconcile_documents(
                    status=status,
                    action=action,
                    offset=offset,
                    limit=limit,
                    dry_run=dry_run,
                    actor=actor,
                    partition=partition,
                    candidates=candidates,
                )
            finally:
                _recovery_access_context.reset(token)

        return await self._run_observed(
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

    async def get_document_content(
        self,
        document_id: str,
        *,
        partition: DocumentPartition,
        access_context: AccessContext | None = None,
    ) -> DocumentContent:
        async def get_content() -> DocumentContent:
            metadata = await self._get_internal_document_metadata_unchecked(
                document_id,
                partition=partition,
            )
            await self._require_access("content.get", access_context, metadata)
            return await self._documents.get_content(
                document_id,
                partition=partition,
            )

        return await self._run_observed(
            "content.get",
            get_content,
            document_id=document_id,
        )

    async def get_document_content_stream(
        self,
        document_id: str,
        *,
        chunk_size: int = 65536,
        partition: DocumentPartition,
        access_context: AccessContext | None = None,
    ) -> AsyncDocumentContentStream:
        if chunk_size <= 0:
            raise ValidationError("chunk_size must be positive")

        async def get_stream() -> AsyncDocumentContentStream:
            metadata = await self._get_internal_document_metadata_unchecked(
                document_id,
                partition=partition,
            )
            await self._require_access("content.stream", access_context, metadata)
            return await self._documents.get_content_stream(
                document_id,
                chunk_size=chunk_size,
                partition=partition,
            )

        return await self._run_observed(
            "content.stream",
            get_stream,
            document_id=document_id,
            conditions={"chunk_size": chunk_size},
        )

    async def get_document_content_async_stream(
        self,
        document_id: str,
        *,
        chunk_size: int = 65536,
        partition: DocumentPartition,
        access_context: AccessContext | None = None,
    ) -> AsyncDocumentContentStream:
        return await self.get_document_content_stream(
            document_id,
            chunk_size=chunk_size,
            partition=partition,
            access_context=access_context,
        )

    async def iter_document_chunks(
        self,
        document_id: str,
        *,
        chunk_size: int = 65536,
        partition: DocumentPartition,
        access_context: AccessContext | None = None,
    ):
        source = await self.get_document_content_stream(
            document_id,
            chunk_size=chunk_size,
            partition=partition,
            access_context=access_context,
        )
        try:
            async for chunk in source.aiter_chunks_closing(chunk_size):
                yield chunk
        finally:
            await source.aclose()

    async def copy_document_to(
        self,
        document_id: str,
        sink: BinaryIO,
        *,
        chunk_size: int = 65536,
        verify_checksum: bool = True,
        partition: DocumentPartition,
        access_context: AccessContext | None = None,
    ) -> DocumentCopyResult:
        metadata = await self._get_internal_document_metadata_unchecked(
            document_id,
            partition=partition,
        )
        await self._require_access("content.copy", access_context, metadata)
        source = await self.get_document_content_stream(
            document_id,
            chunk_size=chunk_size,
            partition=partition,
            access_context=access_context,
        )
        digest = hashlib.sha256()
        copied = 0
        failure: BaseException | None = None
        try:
            async for chunk in source.aiter_chunks_closing(chunk_size):
                await asyncio.to_thread(sink.write, chunk)
                copied += len(chunk)
                digest.update(chunk)
        except BaseException as exc:
            failure = exc
            raise
        finally:
            try:
                await source.aclose()
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

    async def delete_document(
        self,
        document_id: str,
        *,
        partition: DocumentPartition,
        hard_delete: bool = False,
        access_context: AccessContext | None = None,
    ) -> DeleteDocumentResult:
        async def delete() -> DeleteDocumentResult:
            metadata = await self._get_internal_document_metadata_unchecked(
                document_id,
                partition=partition,
            )
            await self._require_access(
                "document.hard_delete" if hard_delete else "document.delete",
                access_context,
                metadata,
            )
            return await self._documents.delete(
                document_id,
                hard_delete=hard_delete,
                partition=partition,
            )

        return await self._run_observed(
            "document.delete",
            delete,
            document_id=document_id,
            conditions={"hard_delete": hard_delete},
        )

    async def soft_delete_document(
        self,
        document_id: str,
        *,
        partition: DocumentPartition,
        access_context: AccessContext | None = None,
    ) -> DeleteDocumentResult:
        return await self.delete_document(
            document_id,
            hard_delete=False,
            partition=partition,
            access_context=access_context,
        )

    async def hard_delete_document(
        self,
        document_id: str,
        *,
        partition: DocumentPartition,
        access_context: AccessContext | None = None,
    ) -> DeleteDocumentResult:
        return await self.delete_document(
            document_id,
            hard_delete=True,
            partition=partition,
            access_context=access_context,
        )

    async def clear_all_data(
        self,
        *,
        access_context: AccessContext | None = None,
    ) -> DataResetResult:
        return await self._reset_data(
            operation="data.clear_all",
            partition=None,
            access_context=access_context,
        )

    async def clear_partition_data(
        self,
        *,
        partition: DocumentPartition,
        access_context: AccessContext | None = None,
    ) -> DataResetResult:
        if not isinstance(partition, DocumentPartition):
            raise ValidationError("partition must be a DocumentPartition")
        return await self._reset_data(
            operation="data.clear_partition",
            partition=partition,
            access_context=access_context,
        )

    async def initialize_for_data_load(
        self,
        *,
        access_context: AccessContext | None = None,
    ) -> DataResetResult:
        return await self._reset_data(
            operation="data.initialize_for_data_load",
            partition=None,
            access_context=access_context,
        )

    async def initialize_partition_for_data_load(
        self,
        *,
        partition: DocumentPartition,
        access_context: AccessContext | None = None,
    ) -> DataResetResult:
        if not isinstance(partition, DocumentPartition):
            raise ValidationError("partition must be a DocumentPartition")
        return await self._reset_data(
            operation="data.initialize_partition_for_data_load",
            partition=partition,
            access_context=access_context,
        )

    async def _reset_data(
        self,
        *,
        operation: str,
        partition: DocumentPartition | None,
        access_context: AccessContext | None,
    ) -> DataResetResult:
        async def reset() -> DataResetResult:
            await self._require_access(operation, access_context, None)
            counts: dict[str, int] = {}
            errors: list[Exception] = []
            failed_stores: list[str] = []
            if partition is None:
                stores: list[tuple[str, Callable[[], Awaitable[int]]]] = [
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
                    counts[name] = await clear_all()
                except Exception as exc:  # noqa: BLE001 - reset continues across stores
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

        return await self._run_observed(
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

    async def _reconciliation_inspect(
        self,
        document_id: str,
        **kwargs: object,
    ) -> DocumentInspection:
        return await self._reconciliation.inspect_document(document_id, **kwargs)

    async def _reconciliation_reconcile(
        self,
        document_id: str,
        action: RecoveryAction,
        **kwargs: object,
    ) -> ReconciliationResult:
        return await self.reconcile_document(document_id, action, **kwargs)

    async def _reconciliation_metadata(
        self,
        document_id: str,
        **kwargs: object,
    ) -> DocumentMetadata:
        return await self.get_internal_document_metadata(document_id, **kwargs)

    async def _emit_recovery_audit(self, event: RecoveryAuditEvent) -> None:
        if self._recovery_audit_hook is None:
            return
        try:
            result = self._recovery_audit_hook(event)
            if inspect.isawaitable(result):
                await result
        except Exception:
            self._logger.exception("recovery audit hook failed")

    async def _set_document_status(
        self,
        metadata: DocumentMetadata,
        status: DocumentStatus,
    ) -> DocumentMetadata:
        return await self._documents.set_status(metadata, status)

    @staticmethod
    def _validate_recovery_page(
        *,
        status: DocumentStatus,
        offset: int,
        limit: int,
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

    async def _run_observed(
        self,
        operation: str,
        callback: Callable[[], Awaitable[_ResultT]],
        *,
        document_id: str | None = None,
        conditions: Mapping[str, object]
        | Callable[[object], Mapping[str, object]]
        | None = None,
    ) -> _ResultT:
        started_at = datetime.now(UTC)
        try:
            result = await callback()
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
        conditions: Mapping[str, object]
        | Callable[[object], Mapping[str, object]]
        | None,
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
