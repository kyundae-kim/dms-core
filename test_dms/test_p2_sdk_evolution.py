from __future__ import annotations

from datetime import UTC, datetime

import pytest

from dms.domain.models import DocumentMetadata, DocumentStatus
from dms.sdk import (
    MetadataSchemaValidationError, MetadataValidationIssue, PublicDocumentMetadata,
    RecoveryAction, RecoveryAuditEvent, StructuredMetadataValidator,
    UploadDocumentRequest, public_metadata,
)
from dms.sdk.factory import create_sdk_from_components
from test_dms.test_p0_sdk_evolution import CursorMemoryStore, StreamMemoryObjectStore


def metadata(document_id: str = "d", status: DocumentStatus = DocumentStatus.AVAILABLE) -> DocumentMetadata:
    now = datetime.now(UTC)
    return DocumentMetadata(document_id=document_id, original_filename="x.txt", content_type="text/plain",
        file_size=1, storage_key="secret/key", status=status, created_at=now, updated_at=now,
        checksum="sum", created_by="u", extra_metadata={"schema_version": "1", "title": "x"})


def test_public_metadata_projection_accepts_metadata_and_upload_result_without_storage_key():
    store, objects = CursorMemoryStore(), StreamMemoryObjectStore()
    sdk = create_sdk_from_components(metadata_store=store, object_store=objects)
    result = sdk.upload_document(UploadDocumentRequest(content=b"x", filename="x.txt", content_type="text/plain"))
    projected = public_metadata(result)
    assert isinstance(projected, PublicDocumentMetadata)
    assert projected == public_metadata(result.metadata)
    assert not hasattr(projected, "storage_key")
    assert projected.extra_metadata is not result.metadata.extra_metadata


def test_structured_validator_checks_version_and_preserves_field_issues():
    calls = []
    def parser(value):
        calls.append(value)
        if "title" not in value:
            raise MetadataSchemaValidationError([MetadataValidationIssue(path=("title",), code="required", message="required")])
        return {"schema_version": value["schema_version"], "title": str(value["title"]).strip()}
    validator = StructuredMetadataValidator(parser=parser, schema_version="1")
    assert validator({"schema_version": "1", "title": " ok "})["title"] == "ok"
    with pytest.raises(MetadataSchemaValidationError) as mismatch:
        validator({"schema_version": "2", "title": "x"})
    assert mismatch.value.issues[0].path == ("schema_version",)
    with pytest.raises(MetadataSchemaValidationError) as missing:
        validator({"schema_version": "1"})
    assert missing.value.issues[0].code == "required"
    assert calls


def test_existing_metadata_validator_callable_remains_compatible():
    sdk = create_sdk_from_components(metadata_store=CursorMemoryStore(), object_store=StreamMemoryObjectStore(),
        metadata_validator=lambda value: {**value, "normalized": True})
    result = sdk.upload_document(UploadDocumentRequest(content=b"x", filename="x", content_type="x", metadata={}))
    assert result.metadata.extra_metadata == {"normalized": True}


def test_dry_run_exports_plan_and_execution_revalidates_stale_items_with_best_effort_audit(monkeypatch):
    store, objects = CursorMemoryStore(), StreamMemoryObjectStore()
    item = metadata(status=DocumentStatus.FAILED)
    store.save_metadata(item)
    events: list[RecoveryAuditEvent] = []
    def audit(event):
        events.append(event)
        raise RuntimeError("audit unavailable")
    sdk = create_sdk_from_components(metadata_store=store, object_store=objects, recovery_audit_hook=audit)
    dry = sdk.reconcile_documents(status=DocumentStatus.FAILED, action=RecoveryAction.MARK_FAILED, dry_run=True)
    plan = dry.to_plan()
    assert len(plan.items) == 1 and plan.items[0].document_id == "d"
    # Make the exported plan stale. Execution must inspect again, reject it, and continue/report.
    monkeypatch.setattr(objects, "object_exists", lambda document_id, storage_key: True)
    executed = sdk.execute_reconciliation_plan(plan)
    assert executed.items[0].error_type == "ValidationError"
    assert events[-1].document_id == "d" and not events[-1].succeeded


def test_plan_execution_reinspects_each_item_and_applies_current_valid_state():
    store, objects = CursorMemoryStore(), StreamMemoryObjectStore()
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
    store, objects = CursorMemoryStore(), StreamMemoryObjectStore()
    store.save_metadata(metadata(status=DocumentStatus.FAILED))
    events: list[RecoveryAuditEvent] = []
    sdk = create_sdk_from_components(
        metadata_store=store,
        object_store=objects,
        recovery_audit_hook=events.append,
    )

    non_preview = sdk.reconcile_documents(
        status=DocumentStatus.FAILED,
        action=RecoveryAction.MARK_FAILED,
    )
    with pytest.raises(ValueError, match="dry-run"):
        non_preview.to_plan()

    store.update_metadata(metadata(status=DocumentStatus.FAILED))
    sdk.reconcile_document("d", RecoveryAction.MARK_FAILED, actor="operator-42")
    assert events[-1].actor == "operator-42"
    assert events[-1].occurred_at.tzinfo is not None
