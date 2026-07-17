from __future__ import annotations

from datetime import UTC, datetime

from io import BytesIO

import pytest

from sqlalchemy import create_engine

from dms.domain.models import DocumentStatus, UploadOperationState

from dms.infrastructure.metadata.operations import SqlAlchemyUploadOperationStore

from dms.sdk import BatchReconciliationResult, RecoveryAction, ReconciliationResult, UploadDocumentUnknownSizeStreamRequest, UploadOperationNotFoundError, UploadOperationResult, ValidationError

from dms.sdk.factory import create_sdk_from_components

from dms.sdk.types import DocumentInspection, RecoveryIssue

from test_dms.sdk_test_support import CursorMemoryStore, StreamMemoryObjectStore

from dms.domain.models import DocumentMetadata, DocumentStatus

from dms.sdk import MetadataSchemaValidationError, MetadataValidationIssue, PublicDocumentMetadata, RecoveryAction, RecoveryAuditEvent, StructuredMetadataValidator, UploadDocumentRequest, public_metadata

def _sdk(*, operation_store=None, metadata_store=None):
    return create_sdk_from_components(metadata_store=metadata_store or CursorMemoryStore(), object_store=StreamMemoryObjectStore(), operation_store=operation_store)

def test_batch_summary_properties_are_stable():
    inspection = DocumentInspection(document_id='a', metadata_exists=True, object_exists=False, status=DocumentStatus.FAILED, consistent=False, issue=RecoveryIssue.OBJECT_MISSING)
    result = BatchReconciliationResult(status=DocumentStatus.FAILED, action=RecoveryAction.MARK_FAILED, dry_run=False, offset=0, limit=10, items=[ReconciliationResult(document_id='a', action=RecoveryAction.MARK_FAILED, applied=True, inspection=inspection), ReconciliationResult(document_id='b', action=RecoveryAction.MARK_FAILED, applied=False, inspection=inspection, error_type='StorageError', error_message='bad')])
    assert (result.scanned, result.eligible, result.applied, result.skipped, result.failed) == (2, 1, 1, 0, 1)

def test_batch_survives_failed_error_path_reinspection(monkeypatch):
    sdk = _sdk()
    now = datetime.now(UTC)
    store = sdk._metadata_store
    from dms.domain.models import DocumentMetadata
    store.save_metadata(DocumentMetadata(document_id='a', original_filename='x', content_type='x', file_size=1, storage_key='missing', status=DocumentStatus.FAILED, created_at=now, updated_at=now))
    calls = 0
    original = sdk.inspect_document

    def inspect(document_id):
        nonlocal calls
        calls += 1
        if calls >= 2:
            raise RuntimeError('inspection backend down')
        return original(document_id)
    monkeypatch.setattr(sdk, 'inspect_document', inspect)
    batch = sdk.reconcile_documents(status=DocumentStatus.FAILED, action=RecoveryAction.COMPLETE_DELETION_SOFT)
    assert batch.scanned == 1 and batch.failed == 1
    assert batch.items[0].error_type == 'ValidationError'

def metadata(document_id: str='d', status: DocumentStatus=DocumentStatus.AVAILABLE) -> DocumentMetadata:
    now = datetime.now(UTC)
    return DocumentMetadata(document_id=document_id, original_filename='x.txt', content_type='text/plain', file_size=1, storage_key='secret/key', status=status, created_at=now, updated_at=now, checksum='sum', created_by='u', extra_metadata={'schema_version': '1', 'title': 'x'})

def test_dry_run_exports_plan_and_execution_revalidates_stale_items_with_best_effort_audit(monkeypatch):
    store, objects = (CursorMemoryStore(), StreamMemoryObjectStore())
    item = metadata(status=DocumentStatus.FAILED)
    store.save_metadata(item)
    events: list[RecoveryAuditEvent] = []

    def audit(event):
        events.append(event)
        raise RuntimeError('audit unavailable')
    sdk = create_sdk_from_components(metadata_store=store, object_store=objects, recovery_audit_hook=audit)
    dry = sdk.reconcile_documents(status=DocumentStatus.FAILED, action=RecoveryAction.MARK_FAILED, dry_run=True)
    plan = dry.to_plan()
    assert len(plan.items) == 1 and plan.items[0].document_id == 'd'
    monkeypatch.setattr(objects, 'object_exists', lambda document_id, storage_key: True)
    executed = sdk.execute_reconciliation_plan(plan)
    assert executed.items[0].error_type == 'ValidationError'
    assert events[-1].document_id == 'd' and (not events[-1].succeeded)

def test_plan_execution_reinspects_each_item_and_applies_current_valid_state():
    store, objects = (CursorMemoryStore(), StreamMemoryObjectStore())
    store.save_metadata(metadata(status=DocumentStatus.FAILED))
    sdk = create_sdk_from_components(metadata_store=store, object_store=objects)
    plan = sdk.reconcile_documents(status=DocumentStatus.FAILED, action=RecoveryAction.MARK_FAILED, dry_run=True).to_plan()
    calls = 0
    original = sdk.inspect_document

    def inspect(document_id):
        nonlocal calls
        calls += 1
        return original(document_id)
    sdk.inspect_document = inspect
    result = sdk.execute_reconciliation_plan(plan)
    assert result.applied == 1 and calls >= 2

def test_recovery_audit_records_actor_and_time_and_plan_requires_dry_run():
    store, objects = (CursorMemoryStore(), StreamMemoryObjectStore())
    store.save_metadata(metadata(status=DocumentStatus.FAILED))
    events: list[RecoveryAuditEvent] = []
    sdk = create_sdk_from_components(metadata_store=store, object_store=objects, recovery_audit_hook=events.append)
    non_preview = sdk.reconcile_documents(status=DocumentStatus.FAILED, action=RecoveryAction.MARK_FAILED)
    with pytest.raises(ValueError, match='dry-run'):
        non_preview.to_plan()
    store.update_metadata(metadata(status=DocumentStatus.FAILED))
    sdk.reconcile_document('d', RecoveryAction.MARK_FAILED, actor='operator-42')
    assert events[-1].actor == 'operator-42'
    assert events[-1].occurred_at.tzinfo is not None
