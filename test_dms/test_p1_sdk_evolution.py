from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO

import pytest
from sqlalchemy import create_engine

from dms.domain.models import DocumentStatus, UploadOperationState
from dms.infrastructure.metadata.operations import SqlAlchemyUploadOperationStore
from dms.sdk import (
    BatchReconciliationResult,
    RecoveryAction,
    ReconciliationResult,
    UploadDocumentUnknownSizeStreamRequest,
    UploadOperationNotFoundError,
    UploadOperationResult,
    ValidationError,
)
from dms.sdk.factory import create_sdk_from_components
from dms.sdk.types import DocumentInspection, RecoveryIssue
from test_dms.test_p0_sdk_evolution import CursorMemoryStore, StreamMemoryObjectStore


def _sdk(*, operation_store=None, metadata_store=None):
    return create_sdk_from_components(
        metadata_store=metadata_store or CursorMemoryStore(),
        object_store=StreamMemoryObjectStore(),
        operation_store=operation_store,
    )


def test_scope_aware_upload_operation_read_and_missing_contract():
    operations = SqlAlchemyUploadOperationStore(create_engine("sqlite+pysqlite:///:memory:"))
    claim = operations.claim(scope="tenant-a", idempotency_key="key", fingerprint="f", document_id="doc")
    sdk = _sdk(operation_store=operations)
    result = sdk.get_upload_operation(scope="tenant-a", idempotency_key="key")
    assert isinstance(result, UploadOperationResult)
    assert result.scope == "tenant-a" and result.idempotency_key == "key"
    assert result.document_id == claim.operation.document_id
    assert result.state is UploadOperationState.PENDING
    assert not hasattr(result, "fingerprint")
    with pytest.raises(UploadOperationNotFoundError):
        sdk.get_upload_operation(scope="other", idempotency_key="key")
    with pytest.raises(ValidationError):
        sdk.get_upload_operation(scope="", idempotency_key="key")


def test_unknown_size_upload_spools_hashes_bounds_and_closes_spool(monkeypatch):
    sdk = _sdk()
    observed = {}
    original = sdk.upload_document_stream

    def recording(request):
        observed["size"] = request.size
        observed["checksum"] = request.checksum
        observed["stream"] = request.stream
        return original(request)

    monkeypatch.setattr(sdk, "upload_document_stream", recording)
    result = sdk.upload_document_unknown_size_stream(UploadDocumentUnknownSizeStreamRequest(
        stream=BytesIO(b"payload"), max_size=7, filename="x.bin", content_type="application/octet-stream",
        document_id="doc", chunk_size=2,
    ))
    assert result.metadata.file_size == 7
    assert observed["size"] == 7
    assert observed["checksum"] == "239f59ed55e737c77147cf55ad0c1b030b6d7ee748a7426952f9b852d5a935e5"
    assert observed["stream"].closed

    with pytest.raises(ValidationError, match="max_size"):
        sdk.upload_document_unknown_size_stream(UploadDocumentUnknownSizeStreamRequest(
            stream=BytesIO(b"x"), max_size=0, filename="x", content_type="x"))
    with pytest.raises(ValidationError, match="exceeds max_size"):
        sdk.upload_document_unknown_size_stream(UploadDocumentUnknownSizeStreamRequest(
            stream=BytesIO(b"too large"), max_size=3, filename="x", content_type="x"))


def test_batch_summary_properties_are_stable():
    inspection = DocumentInspection(document_id="a", metadata_exists=True, object_exists=False,
        status=DocumentStatus.FAILED, consistent=False, issue=RecoveryIssue.OBJECT_MISSING)
    result = BatchReconciliationResult(status=DocumentStatus.FAILED, action=RecoveryAction.MARK_FAILED,
        dry_run=False, offset=0, limit=10, items=[
            ReconciliationResult(document_id="a", action=RecoveryAction.MARK_FAILED, applied=True, inspection=inspection),
            ReconciliationResult(document_id="b", action=RecoveryAction.MARK_FAILED, applied=False,
                inspection=inspection, error_type="StorageError", error_message="bad"),
        ])
    assert (result.scanned, result.eligible, result.applied, result.skipped, result.failed) == (2, 1, 1, 0, 1)


def test_batch_survives_failed_error_path_reinspection(monkeypatch):
    sdk = _sdk()
    now = datetime.now(UTC)
    store = sdk._metadata_store
    from dms.domain.models import DocumentMetadata
    store.save_metadata(DocumentMetadata(document_id="a", original_filename="x", content_type="x", file_size=1,
        storage_key="missing", status=DocumentStatus.FAILED, created_at=now, updated_at=now))
    calls = 0
    original = sdk.inspect_document
    def inspect(document_id):
        nonlocal calls
        calls += 1
        if calls >= 2:
            raise RuntimeError("inspection backend down")
        return original(document_id)
    monkeypatch.setattr(sdk, "inspect_document", inspect)
    batch = sdk.reconcile_documents(status=DocumentStatus.FAILED, action=RecoveryAction.COMPLETE_DELETION_SOFT)
    assert batch.scanned == 1 and batch.failed == 1
    assert batch.items[0].error_type == "ValidationError"
