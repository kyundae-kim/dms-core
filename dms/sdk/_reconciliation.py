from __future__ import annotations

from typing import Protocol

from dms.domain.models import DocumentMetadata, DocumentStatus
from dms.sdk.errors import ValidationError
from dms.sdk.types import (
    BatchReconciliationResult,
    DocumentInspection,
    ReconciliationPlan,
    ReconciliationResult,
    RecoveryAction,
    RecoveryAuditEvent,
)


class _ReconciliationHost(Protocol):
    def _reconcile_document(self, document_id: str, action: RecoveryAction, *, storage_key: str | None = None, dry_run: bool = False) -> ReconciliationResult: ...
    def _emit_recovery_audit(self, event: RecoveryAuditEvent) -> None: ...
    def reconcile_document(self, document_id: str, action: RecoveryAction, *, storage_key: str | None = None, dry_run: bool = False, actor: str | None = None) -> ReconciliationResult: ...
    def inspect_document(self, document_id: str) -> DocumentInspection: ...
    def list_recovery_candidates(self, *, status: DocumentStatus, offset: int = 0, limit: int = 100) -> list[DocumentMetadata]: ...


class ReconciliationCoordinator:
    """Coordinates audited single and batch reconciliation operations."""

    def __init__(self, host: _ReconciliationHost) -> None:
        self._host = host

    def reconcile_document(self, document_id: str, action: RecoveryAction, *,
                           storage_key: str | None = None, dry_run: bool = False,
                           actor: str | None = None) -> ReconciliationResult:
        try:
            result = self._host._reconcile_document(document_id, action, storage_key=storage_key, dry_run=dry_run)
        except Exception as exc:
            self._host._emit_recovery_audit(RecoveryAuditEvent(document_id=document_id,
                action=action, dry_run=dry_run, succeeded=False, applied=False, actor=actor,
                error_type=type(exc).__name__, error_message=str(exc)))
            raise
        self._host._emit_recovery_audit(RecoveryAuditEvent(document_id=document_id,
            action=action, dry_run=dry_run, succeeded=True, applied=result.applied, actor=actor))
        return result

    def execute_reconciliation_plan(self, plan: ReconciliationPlan, *, actor: str | None = None) -> BatchReconciliationResult:
        if not isinstance(plan, ReconciliationPlan):
            raise ValidationError("plan must be a ReconciliationPlan")
        results: list[ReconciliationResult] = []
        for item in plan.items:
            try:
                results.append(self._host.reconcile_document(item.document_id, item.action,
                    storage_key=item.storage_key, actor=actor))
            except Exception as exc:
                try:
                    inspection = self._host.inspect_document(item.document_id)
                except Exception:
                    inspection = None
                results.append(ReconciliationResult(document_id=item.document_id,
                    action=item.action, applied=False, inspection=inspection,
                    error_type=type(exc).__name__, error_message=str(exc)))
        return BatchReconciliationResult(status=plan.status, action=plan.action,
            dry_run=False, offset=0, limit=len(plan.items), items=results)

    def reconcile_documents(self, *, status: DocumentStatus, action: RecoveryAction,
                            offset: int = 0, limit: int = 100, dry_run: bool = False,
                            actor: str | None = None) -> BatchReconciliationResult:
        candidates = self._host.list_recovery_candidates(status=status, offset=offset, limit=limit)
        items: list[ReconciliationResult] = []
        for metadata in candidates:
            try:
                items.append(self._host.reconcile_document(metadata.document_id, action,
                    dry_run=dry_run, actor=actor))
            except Exception as exc:
                try:
                    inspection = self._host.inspect_document(metadata.document_id)
                except Exception:
                    inspection = None
                items.append(ReconciliationResult(document_id=metadata.document_id,
                    action=action, applied=False, inspection=inspection,
                    error_type=type(exc).__name__, error_message=str(exc)))
        return BatchReconciliationResult(status=status, action=action, dry_run=dry_run,
            offset=offset, limit=limit, items=items)
