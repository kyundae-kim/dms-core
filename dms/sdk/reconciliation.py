from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable

from dms.domain.interfaces import (
    AsyncMetadataStore,
    AsyncObjectStore,
    MetadataStore,
    ObjectStore,
)
from dms.domain.models import DocumentMetadata, DocumentPartition, DocumentStatus
from dms.sdk.contracts import _validate_partition, partition_storage_prefix
from dms.sdk.errors import (
    DocumentNotFoundError,
    MetadataStoreError,
    StorageError,
    ValidationError,
)
from dms.sdk.types import (
    BatchReconciliationResult,
    DocumentInspection,
    ReconciliationPlan,
    ReconciliationResult,
    RecoveryAction,
    RecoveryAuditEvent,
    RecoveryIssue,
)


class ReconciliationCoordinator:
    """Owns consistency inspection and audited reconciliation operations."""

    def __init__(
        self,
        *,
        metadata_store: MetadataStore,
        object_store: ObjectStore,
        inspect_override: Callable[[str], DocumentInspection],
        reconcile_override: Callable[..., ReconciliationResult],
        list_candidates: Callable[..., list[DocumentMetadata]],
        get_metadata: Callable[[str], DocumentMetadata],
        set_failed: Callable[[DocumentMetadata, DocumentStatus], DocumentMetadata],
        emit_audit: Callable[[RecoveryAuditEvent], None],
    ) -> None:
        self._metadata_store = metadata_store
        self._object_store = object_store
        self._inspect_override = inspect_override
        self._reconcile_override = reconcile_override
        self._list_candidates = list_candidates
        self._get_metadata = get_metadata
        self._set_failed = set_failed
        self._emit_audit = emit_audit

    def inspect_document(
        self,
        document_id: str,
        *,
        partition: DocumentPartition,
    ) -> DocumentInspection:
        _validate_partition(partition)
        try:
            metadata = self._metadata_store.get_metadata(
                document_id,
                partition=partition,
            )
        except LookupError:
            return DocumentInspection(
                document_id=document_id,
                metadata_exists=False,
                object_exists=None,
                status=None,
                consistent=False,
                issue=RecoveryIssue.METADATA_MISSING,
                storage_key=None,
            )
        except Exception as exc:
            raise MetadataStoreError(
                f"Failed to load metadata for {document_id}"
            ) from exc
        try:
            object_exists = self._object_store.object_exists(
                document_id, metadata.storage_key
            )
        except Exception as exc:
            raise StorageError(
                f"Failed to inspect document content for {document_id}"
            ) from exc
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
        return DocumentInspection(
            document_id=document_id,
            metadata_exists=True,
            object_exists=object_exists,
            status=metadata.status,
            consistent=consistent,
            issue=issue,
            storage_key=metadata.storage_key,
        )

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
        try:
            result = self._apply(
                document_id,
                action,
                storage_key=storage_key,
                dry_run=dry_run,
                partition=partition,
            )
        except Exception as exc:
            self._emit_audit(
                RecoveryAuditEvent(
                    document_id=document_id,
                    action=action,
                    dry_run=dry_run,
                    succeeded=False,
                    applied=False,
                    actor=actor,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
            )
            raise
        self._emit_audit(
            RecoveryAuditEvent(
                document_id=document_id,
                action=action,
                dry_run=dry_run,
                succeeded=True,
                applied=result.applied,
                actor=actor,
            )
        )
        return result

    def _apply(
        self,
        document_id: str,
        action: RecoveryAction,
        *,
        storage_key: str | None,
        dry_run: bool,
        partition: DocumentPartition,
    ) -> ReconciliationResult:
        _validate_partition(partition)
        if not isinstance(action, RecoveryAction):
            raise ValidationError("action must be a RecoveryAction")
        inspection = self._inspect_override(document_id, partition=partition)
        if action is RecoveryAction.PURGE_ORPHAN_OBJECT:
            if inspection.metadata_exists:
                raise ValidationError("orphan purge requires absent metadata")
            if storage_key is None or not storage_key.strip():
                raise ValidationError("storage_key is required for orphan purge")
            expected_prefix = f"{partition_storage_prefix(partition)}{document_id}/"
            if not storage_key.startswith(expected_prefix):
                raise ValidationError(
                    "storage_key does not belong to the document partition namespace"
                )
            try:
                exists = self._object_store.object_exists(document_id, storage_key)
            except Exception as exc:
                raise StorageError(
                    f"Failed to inspect orphan object for {document_id}"
                ) from exc
            if not exists:
                raise ValidationError(
                    "orphan purge requires an existing object at the supplied storage_key"
                )
            if not dry_run:
                try:
                    self._object_store.delete_object(document_id, storage_key)
                except Exception as exc:
                    raise StorageError(
                        f"Failed to purge orphan object for {document_id}"
                    ) from exc
            return ReconciliationResult(
                document_id=document_id,
                action=action,
                applied=not dry_run,
                inspection=self._inspect_override(document_id, partition=partition),
            )
        if not inspection.metadata_exists:
            raise DocumentNotFoundError(
                f"Document not found: {document_id}",
                document_id=document_id,
            )
        if action in (
            RecoveryAction.COMPLETE_DELETION_SOFT,
            RecoveryAction.COMPLETE_DELETION_HARD,
        ):
            if (
                inspection.status is not DocumentStatus.DELETING
                or inspection.object_exists is not False
            ):
                raise ValidationError(
                    "completion requires DELETING metadata and an absent object"
                )
            if not dry_run:
                try:
                    if action is RecoveryAction.COMPLETE_DELETION_HARD:
                        self._metadata_store.hard_delete(
                            document_id,
                            partition=partition,
                        )
                    else:
                        self._metadata_store.mark_deleted(
                            document_id,
                            partition=partition,
                        )
                except Exception as exc:
                    raise MetadataStoreError(
                        f"Failed to complete deletion for {document_id}"
                    ) from exc
        elif action is RecoveryAction.MARK_FAILED:
            if inspection.object_exists is not False:
                raise ValidationError(
                    "mark failed requires existing metadata and an absent object"
                )
            if not dry_run:
                self._set_failed(
                    self._get_metadata(document_id, partition=partition),
                    DocumentStatus.FAILED,
                )
        return ReconciliationResult(
            document_id=document_id,
            action=action,
            applied=not dry_run,
            inspection=self._inspect_override(document_id, partition=partition),
        )

    def execute_reconciliation_plan(
        self,
        plan: ReconciliationPlan,
        *,
        partition: DocumentPartition,
        actor: str | None = None,
    ) -> BatchReconciliationResult:
        if not isinstance(plan, ReconciliationPlan):
            raise ValidationError("plan must be a ReconciliationPlan")
        if plan.partition != partition:
            raise ValidationError(
                "reconciliation plan partition does not match request"
            )
        results = [
            self._reconcile_item(
                item.document_id,
                item.action,
                storage_key=item.storage_key,
                actor=actor,
                partition=partition,
            )
            for item in plan.items
        ]
        return BatchReconciliationResult(
            partition=partition,
            status=plan.status,
            action=plan.action,
            dry_run=False,
            offset=0,
            limit=len(plan.items),
            items=results,
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
        partition: DocumentPartition,
        candidates: list[DocumentMetadata] | None = None,
    ) -> BatchReconciliationResult:
        _validate_partition(partition)
        if not isinstance(action, RecoveryAction):
            raise ValidationError("action must be a RecoveryAction")
        selected = candidates
        if selected is None:
            selected = self._list_candidates(
                status=status,
                offset=offset,
                limit=limit,
                partition=partition,
            )
        items = [
            self._reconcile_item(
                item.document_id,
                action,
                dry_run=dry_run,
                actor=actor,
                partition=partition,
            )
            for item in selected
        ]
        return BatchReconciliationResult(
            partition=partition,
            status=status,
            action=action,
            dry_run=dry_run,
            offset=offset,
            limit=limit,
            items=items,
        )

    def _reconcile_item(
        self,
        document_id: str,
        action: RecoveryAction,
        *,
        storage_key: str | None = None,
        dry_run: bool = False,
        actor: str | None = None,
        partition: DocumentPartition,
    ) -> ReconciliationResult:
        try:
            return self._reconcile_override(
                document_id,
                action,
                storage_key=storage_key,
                dry_run=dry_run,
                actor=actor,
                partition=partition,
            )
        except Exception as exc:  # noqa: BLE001 - preserve per-item batch failures
            try:
                inspection = self._inspect_override(document_id, partition=partition)
            except Exception:  # noqa: BLE001 - preserve the original reconciliation error
                inspection = None
            return ReconciliationResult(
                document_id=document_id,
                action=action,
                applied=False,
                inspection=inspection,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )


class AsyncReconciliationCoordinator:
    """Async consistency and recovery operations matching the sync coordinator."""

    def __init__(
        self,
        *,
        metadata_store: AsyncMetadataStore,
        object_store: AsyncObjectStore,
        inspect_override: Callable[[str], Awaitable[DocumentInspection]],
        reconcile_override: Callable[..., Awaitable[ReconciliationResult]],
        list_candidates: Callable[..., Awaitable[list[DocumentMetadata]]],
        get_metadata: Callable[[str], Awaitable[DocumentMetadata]],
        set_failed: Callable[
            [DocumentMetadata, DocumentStatus], Awaitable[DocumentMetadata]
        ],
        emit_audit: Callable[[RecoveryAuditEvent], object],
    ) -> None:
        self._metadata_store = metadata_store
        self._object_store = object_store
        self._inspect_override = inspect_override
        self._reconcile_override = reconcile_override
        self._list_candidates = list_candidates
        self._get_metadata = get_metadata
        self._set_failed = set_failed
        self._emit_audit = emit_audit

    async def inspect_document(
        self,
        document_id: str,
        *,
        partition: DocumentPartition,
    ) -> DocumentInspection:
        _validate_partition(partition)
        try:
            metadata = await self._metadata_store.get_metadata(
                document_id,
                partition=partition,
            )
        except LookupError:
            return DocumentInspection(
                document_id=document_id,
                metadata_exists=False,
                object_exists=None,
                status=None,
                consistent=False,
                issue=RecoveryIssue.METADATA_MISSING,
                storage_key=None,
            )
        except Exception as exc:
            raise MetadataStoreError(
                f"Failed to load metadata for {document_id}"
            ) from exc
        try:
            object_exists = await self._object_store.object_exists(
                document_id,
                metadata.storage_key,
            )
        except Exception as exc:
            raise StorageError(
                f"Failed to inspect document content for {document_id}"
            ) from exc
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
        return DocumentInspection(
            document_id=document_id,
            metadata_exists=True,
            object_exists=object_exists,
            status=metadata.status,
            consistent=consistent,
            issue=issue,
            storage_key=metadata.storage_key,
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
    ) -> ReconciliationResult:
        try:
            result = await self._apply(
                document_id,
                action,
                storage_key=storage_key,
                dry_run=dry_run,
                partition=partition,
            )
        except Exception as exc:
            await self._emit(
                RecoveryAuditEvent(
                    document_id=document_id,
                    action=action,
                    dry_run=dry_run,
                    succeeded=False,
                    applied=False,
                    actor=actor,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
            )
            raise
        await self._emit(
            RecoveryAuditEvent(
                document_id=document_id,
                action=action,
                dry_run=dry_run,
                succeeded=True,
                applied=result.applied,
                actor=actor,
            )
        )
        return result

    async def _apply(
        self,
        document_id: str,
        action: RecoveryAction,
        *,
        storage_key: str | None,
        dry_run: bool,
        partition: DocumentPartition,
    ) -> ReconciliationResult:
        _validate_partition(partition)
        if not isinstance(action, RecoveryAction):
            raise ValidationError("action must be a RecoveryAction")
        inspection = await self._inspect_override(document_id, partition=partition)
        if action is RecoveryAction.PURGE_ORPHAN_OBJECT:
            if inspection.metadata_exists:
                raise ValidationError("orphan purge requires absent metadata")
            if storage_key is None or not storage_key.strip():
                raise ValidationError("storage_key is required for orphan purge")
            expected_prefix = f"{partition_storage_prefix(partition)}{document_id}/"
            if not storage_key.startswith(expected_prefix):
                raise ValidationError(
                    "storage_key does not belong to the document partition namespace"
                )
            try:
                exists = await self._object_store.object_exists(
                    document_id, storage_key
                )
            except Exception as exc:
                raise StorageError(
                    f"Failed to inspect orphan object for {document_id}"
                ) from exc
            if not exists:
                raise ValidationError(
                    "orphan purge requires an existing object at the supplied storage_key"
                )
            if not dry_run:
                try:
                    await self._object_store.delete_object(document_id, storage_key)
                except Exception as exc:
                    raise StorageError(
                        f"Failed to purge orphan object for {document_id}"
                    ) from exc
            return ReconciliationResult(
                document_id=document_id,
                action=action,
                applied=not dry_run,
                inspection=await self._inspect_override(
                    document_id,
                    partition=partition,
                ),
            )
        if not inspection.metadata_exists:
            raise DocumentNotFoundError(
                f"Document not found: {document_id}",
                document_id=document_id,
            )
        if action in (
            RecoveryAction.COMPLETE_DELETION_SOFT,
            RecoveryAction.COMPLETE_DELETION_HARD,
        ):
            if (
                inspection.status is not DocumentStatus.DELETING
                or inspection.object_exists is not False
            ):
                raise ValidationError(
                    "completion requires DELETING metadata and an absent object"
                )
            if not dry_run:
                try:
                    if action is RecoveryAction.COMPLETE_DELETION_HARD:
                        await self._metadata_store.hard_delete(
                            document_id,
                            partition=partition,
                        )
                    else:
                        await self._metadata_store.mark_deleted(
                            document_id,
                            partition=partition,
                        )
                except Exception as exc:
                    raise MetadataStoreError(
                        f"Failed to complete deletion for {document_id}"
                    ) from exc
        elif action is RecoveryAction.MARK_FAILED:
            if inspection.object_exists is not False:
                raise ValidationError(
                    "mark failed requires existing metadata and an absent object"
                )
            if not dry_run:
                await self._set_failed(
                    await self._get_metadata(document_id, partition=partition),
                    DocumentStatus.FAILED,
                )
        return ReconciliationResult(
            document_id=document_id,
            action=action,
            applied=not dry_run,
            inspection=await self._inspect_override(
                document_id,
                partition=partition,
            ),
        )

    async def execute_reconciliation_plan(
        self,
        plan: ReconciliationPlan,
        *,
        partition: DocumentPartition,
        actor: str | None = None,
    ) -> BatchReconciliationResult:
        if not isinstance(plan, ReconciliationPlan):
            raise ValidationError("plan must be a ReconciliationPlan")
        if plan.partition != partition:
            raise ValidationError(
                "reconciliation plan partition does not match request"
            )
        results = [
            await self._reconcile_item(
                item.document_id,
                item.action,
                storage_key=item.storage_key,
                actor=actor,
                partition=partition,
            )
            for item in plan.items
        ]
        return BatchReconciliationResult(
            partition=partition,
            status=plan.status,
            action=plan.action,
            dry_run=False,
            offset=0,
            limit=len(plan.items),
            items=results,
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
        candidates: list[DocumentMetadata] | None = None,
    ) -> BatchReconciliationResult:
        _validate_partition(partition)
        if not isinstance(action, RecoveryAction):
            raise ValidationError("action must be a RecoveryAction")
        selected = candidates
        if selected is None:
            selected = await self._list_candidates(
                status=status,
                offset=offset,
                limit=limit,
                partition=partition,
            )
        items = [
            await self._reconcile_item(
                item.document_id,
                action,
                dry_run=dry_run,
                actor=actor,
                partition=partition,
            )
            for item in selected
        ]
        return BatchReconciliationResult(
            partition=partition,
            status=status,
            action=action,
            dry_run=dry_run,
            offset=offset,
            limit=limit,
            items=items,
        )

    async def _reconcile_item(
        self,
        document_id: str,
        action: RecoveryAction,
        *,
        storage_key: str | None = None,
        dry_run: bool = False,
        actor: str | None = None,
        partition: DocumentPartition,
    ) -> ReconciliationResult:
        try:
            return await self._reconcile_override(
                document_id,
                action,
                storage_key=storage_key,
                dry_run=dry_run,
                actor=actor,
                partition=partition,
            )
        except Exception as exc:  # noqa: BLE001 - each recovery item is isolated
            try:
                inspection = await self._inspect_override(
                    document_id,
                    partition=partition,
                )
            except Exception:  # noqa: BLE001 - preserve the original item failure
                inspection = None
            return ReconciliationResult(
                document_id=document_id,
                action=action,
                applied=False,
                inspection=inspection,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )

    async def _emit(self, event: RecoveryAuditEvent) -> None:
        result = self._emit_audit(event)
        if inspect.isawaitable(result):
            await result
