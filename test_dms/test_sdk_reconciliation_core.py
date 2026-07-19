from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy import create_engine

from dms import (
    DocumentStatus,
    RecoveryAction,
    RecoveryIssue,
    StorageError,
    UploadDocumentRequest,
    ValidationError,
    create_sdk_from_components,
)
from dms.infrastructure.metadata.sqlite import SqliteMetadataStore
from test_dms.sdk_test_support import InMemoryMetadataStore, InMemoryObjectStore


def _sdk(metadata=None, objects=None):
    return create_sdk_from_components(
        metadata_store=metadata or InMemoryMetadataStore(),
        object_store=objects or InMemoryObjectStore(),
    )


def _upload(sdk, document_id: str = "doc-1"):
    result = sdk.upload_document(UploadDocumentRequest(
        document_id=document_id, content=b"body", filename="a.txt", content_type="text/plain"
    ))
    return sdk.get_internal_document_metadata(result.document_id)


def test_inspect_missing_metadata_is_a_typed_result_not_not_found():
    inspection = _sdk().inspect_document("missing")
    assert inspection.document_id == "missing"
    assert inspection.metadata_exists is False
    assert inspection.object_exists is None
    assert inspection.status is None
    assert inspection.consistent is False
    assert inspection.issue is RecoveryIssue.METADATA_MISSING


def test_inspect_consistent_and_missing_object():
    metadata, objects = InMemoryMetadataStore(), InMemoryObjectStore()
    sdk = _sdk(metadata, objects)
    uploaded = _upload(sdk)
    healthy = sdk.inspect_document("doc-1")
    assert (healthy.metadata_exists, healthy.object_exists, healthy.status,
            healthy.consistent, healthy.issue) == (
        True, True, DocumentStatus.AVAILABLE, True, RecoveryIssue.NONE
    )
    objects.delete_object("doc-1", uploaded.storage_key)
    broken = sdk.inspect_document("doc-1")
    assert broken.object_exists is False
    assert broken.consistent is False
    assert broken.issue is RecoveryIssue.OBJECT_MISSING


def test_complete_deletion_requires_deleting_and_absent_object_then_soft_or_hard():
    metadata, objects = InMemoryMetadataStore(), InMemoryObjectStore()
    sdk = _sdk(metadata, objects)
    uploaded = _upload(sdk)
    metadata.update_metadata(replace(uploaded, status=DocumentStatus.DELETING))
    objects.delete_object("doc-1", uploaded.storage_key)

    dry = sdk.reconcile_document("doc-1", RecoveryAction.COMPLETE_DELETION_SOFT, dry_run=True)
    assert dry.applied is False
    assert metadata.get_metadata("doc-1").status is DocumentStatus.DELETING
    done = sdk.reconcile_document("doc-1", RecoveryAction.COMPLETE_DELETION_SOFT)
    assert done.applied is True
    assert done.inspection.status is DocumentStatus.DELETED

    uploaded2 = _upload(sdk, "doc-2")
    metadata.update_metadata(replace(uploaded2, status=DocumentStatus.DELETING))
    objects.delete_object("doc-2", uploaded2.storage_key)
    sdk.reconcile_document("doc-2", RecoveryAction.COMPLETE_DELETION_HARD)
    assert metadata.exists("doc-2") is False


def test_mark_failed_only_when_metadata_exists_and_object_absent():
    metadata, objects = InMemoryMetadataStore(), InMemoryObjectStore()
    sdk = _sdk(metadata, objects)
    uploaded = _upload(sdk)
    with pytest.raises(ValidationError):
        sdk.reconcile_document("doc-1", RecoveryAction.MARK_FAILED)
    objects.delete_object("doc-1", uploaded.storage_key)
    result = sdk.reconcile_document("doc-1", RecoveryAction.MARK_FAILED)
    assert result.inspection.status is DocumentStatus.FAILED


def test_purge_orphan_requires_known_key_and_absent_metadata():
    objects = InMemoryObjectStore()
    # Seed an orphan through the normal upload then remove only metadata.
    metadata = InMemoryMetadataStore()
    sdk = _sdk(metadata, objects)
    uploaded = _upload(sdk)
    metadata.hard_delete("doc-1")
    with pytest.raises(ValidationError):
        sdk.reconcile_document("doc-1", RecoveryAction.PURGE_ORPHAN_OBJECT)
    result = sdk.reconcile_document(
        "doc-1", RecoveryAction.PURGE_ORPHAN_OBJECT, storage_key=uploaded.storage_key
    )
    assert result.applied is True
    assert objects.object_exists("doc-1", uploaded.storage_key) is False


def test_batch_is_bounded_status_restricted_dry_run_and_preserves_item_errors():
    metadata, objects = InMemoryMetadataStore(), InMemoryObjectStore()
    sdk = _sdk(metadata, objects)
    for document_id in ("a", "b"):
        uploaded = _upload(sdk, document_id)
        metadata.update_metadata(replace(uploaded, status=DocumentStatus.DELETING))
        objects.delete_object(document_id, uploaded.storage_key)
    with pytest.raises(ValidationError):
        sdk.list_recovery_candidates(status=DocumentStatus.AVAILABLE)
    with pytest.raises(ValidationError):
        sdk.list_recovery_candidates(status=DocumentStatus.FAILED, limit=1001)
    page = sdk.list_recovery_candidates(status=DocumentStatus.DELETING, offset=1, limit=1)
    assert len(page) == 1
    batch = sdk.reconcile_documents(
        status=DocumentStatus.DELETING,
        action=RecoveryAction.COMPLETE_DELETION_SOFT,
        dry_run=True,
        limit=10,
    )
    assert batch.dry_run is True and len(batch.items) == 2
    assert all(item.applied is False and item.error_type is None for item in batch.items)

    class OneDeleteFails(InMemoryMetadataStore):
        def mark_deleted(self, document_id):
            if document_id == "b":
                raise RuntimeError("db failed")
            return super().mark_deleted(document_id)

    failing = OneDeleteFails()
    failing._items.update(metadata._items)
    result = _sdk(failing, objects).reconcile_documents(
        status=DocumentStatus.DELETING,
        action=RecoveryAction.COMPLETE_DELETION_SOFT,
        limit=10,
    )
    assert len(result.items) == 2
    assert {item.error_type for item in result.items} == {None, "MetadataStoreError"}


def test_real_sqlite_recovery_persists_status(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'recovery.db'}")
    metadata = SqliteMetadataStore(engine)
    objects = InMemoryObjectStore()
    sdk = _sdk(metadata, objects)
    uploaded = _upload(sdk, "sqlite-doc")
    objects.delete_object("sqlite-doc", uploaded.storage_key)
    result = sdk.reconcile_document("sqlite-doc", RecoveryAction.MARK_FAILED)
    assert result.inspection.status is DocumentStatus.FAILED
    assert SqliteMetadataStore(engine).get_metadata("sqlite-doc").status is DocumentStatus.FAILED


def test_inspection_and_purge_backend_errors_map_to_existing_sdk_errors():
    class BrokenExists(InMemoryObjectStore):
        def object_exists(self, document_id, storage_key):
            raise RuntimeError("storage down")
    metadata = InMemoryMetadataStore()
    sdk = _sdk(metadata, BrokenExists())
    _upload(sdk)
    with pytest.raises(StorageError):
        sdk.inspect_document("doc-1")
