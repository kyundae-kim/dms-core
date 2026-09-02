from __future__ import annotations

from dataclasses import replace

import pytest

from dms import (
    DefaultDocumentManagementSDK,
    DocumentStatus,
    RecoveryAction,
    RecoveryIssue,
    StorageError,
    UploadDocumentRequest,
    ValidationError,
)
from test_dms.sdk_test_support import (
    DEFAULT_PARTITION,
    InMemoryMetadataStore,
    InMemoryObjectStore,
)


def _sdk(metadata=None, objects=None):
    return DefaultDocumentManagementSDK(
        metadata_store=metadata or InMemoryMetadataStore(),
        object_store=objects or InMemoryObjectStore(),
    )


def _upload(sdk, document_id: str = "doc-1"):
    result = sdk.upload_document(
        UploadDocumentRequest(
            document_id=document_id,
            content=b"body",
            filename="a.txt",
            content_type="text/plain",
        ),
        partition=DEFAULT_PARTITION,
    )
    return sdk.get_internal_document_metadata(
        result.document_id, partition=DEFAULT_PARTITION
    )


def test_inspect_missing_metadata_is_a_typed_result_not_not_found():
    inspection = _sdk().inspect_document("missing", partition=DEFAULT_PARTITION)
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
    healthy = sdk.inspect_document("doc-1", partition=DEFAULT_PARTITION)
    assert (
        healthy.metadata_exists,
        healthy.object_exists,
        healthy.status,
        healthy.consistent,
        healthy.issue,
    ) == (True, True, DocumentStatus.AVAILABLE, True, RecoveryIssue.NONE)
    objects.delete_object("doc-1", uploaded.storage_key)
    broken = sdk.inspect_document("doc-1", partition=DEFAULT_PARTITION)
    assert broken.object_exists is False
    assert broken.consistent is False
    assert broken.issue is RecoveryIssue.OBJECT_MISSING


def test_complete_deletion_requires_deleting_and_absent_object_then_soft_or_hard():
    metadata, objects = InMemoryMetadataStore(), InMemoryObjectStore()
    sdk = _sdk(metadata, objects)
    uploaded = _upload(sdk)
    metadata.update_metadata(replace(uploaded, status=DocumentStatus.DELETING))
    objects.delete_object("doc-1", uploaded.storage_key)

    dry = sdk.reconcile_document(
        "doc-1",
        RecoveryAction.COMPLETE_DELETION_SOFT,
        dry_run=True,
        partition=DEFAULT_PARTITION,
    )
    assert dry.applied is False
    assert (
        metadata.get_metadata("doc-1", partition=DEFAULT_PARTITION).status
        is DocumentStatus.DELETING
    )
    done = sdk.reconcile_document(
        "doc-1", RecoveryAction.COMPLETE_DELETION_SOFT, partition=DEFAULT_PARTITION
    )
    assert done.applied is True
    assert done.inspection.status is DocumentStatus.DELETED

    uploaded2 = _upload(sdk, "doc-2")
    metadata.update_metadata(replace(uploaded2, status=DocumentStatus.DELETING))
    objects.delete_object("doc-2", uploaded2.storage_key)
    sdk.reconcile_document(
        "doc-2", RecoveryAction.COMPLETE_DELETION_HARD, partition=DEFAULT_PARTITION
    )
    assert metadata.exists("doc-2") is False


def test_mark_failed_only_when_metadata_exists_and_object_absent():
    metadata, objects = InMemoryMetadataStore(), InMemoryObjectStore()
    sdk = _sdk(metadata, objects)
    uploaded = _upload(sdk)
    with pytest.raises(ValidationError):
        sdk.reconcile_document(
            "doc-1", RecoveryAction.MARK_FAILED, partition=DEFAULT_PARTITION
        )
    objects.delete_object("doc-1", uploaded.storage_key)
    result = sdk.reconcile_document(
        "doc-1", RecoveryAction.MARK_FAILED, partition=DEFAULT_PARTITION
    )
    assert result.inspection.status is DocumentStatus.FAILED


def test_purge_orphan_requires_known_key_and_absent_metadata():
    objects = InMemoryObjectStore()
    # Seed an orphan through the normal upload then remove only metadata.
    metadata = InMemoryMetadataStore()
    sdk = _sdk(metadata, objects)
    uploaded = _upload(sdk)
    metadata.hard_delete("doc-1", partition=DEFAULT_PARTITION)
    with pytest.raises(ValidationError):
        sdk.reconcile_document(
            "doc-1", RecoveryAction.PURGE_ORPHAN_OBJECT, partition=DEFAULT_PARTITION
        )
    result = sdk.reconcile_document(
        "doc-1",
        RecoveryAction.PURGE_ORPHAN_OBJECT,
        storage_key=uploaded.storage_key,
        partition=DEFAULT_PARTITION,
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
        sdk.list_recovery_candidates(
            status=DocumentStatus.AVAILABLE, partition=DEFAULT_PARTITION
        )
    with pytest.raises(ValidationError):
        sdk.list_recovery_candidates(
            status=DocumentStatus.FAILED, limit=1001, partition=DEFAULT_PARTITION
        )
    page = sdk.list_recovery_candidates(
        status=DocumentStatus.DELETING, offset=1, limit=1, partition=DEFAULT_PARTITION
    )
    assert len(page) == 1
    batch = sdk.reconcile_documents(
        status=DocumentStatus.DELETING,
        action=RecoveryAction.COMPLETE_DELETION_SOFT,
        dry_run=True,
        limit=10,
        partition=DEFAULT_PARTITION,
    )
    assert batch.dry_run is True and len(batch.items) == 2
    assert all(
        item.applied is False and item.error_type is None for item in batch.items
    )

    class OneDeleteFails(InMemoryMetadataStore):
        def mark_deleted(self, document_id, *, partition):
            if document_id == "b":
                raise RuntimeError("db failed")
            return super().mark_deleted(document_id, partition=partition)

    failing = OneDeleteFails()
    failing._items.update(metadata._items)
    result = _sdk(failing, objects).reconcile_documents(
        status=DocumentStatus.DELETING,
        action=RecoveryAction.COMPLETE_DELETION_SOFT,
        limit=10,
        partition=DEFAULT_PARTITION,
    )
    assert len(result.items) == 2
    assert {item.error_type for item in result.items} == {None, "MetadataStoreError"}


def test_inspection_and_purge_backend_errors_map_to_existing_sdk_errors():
    class BrokenExists(InMemoryObjectStore):
        def object_exists(self, document_id, storage_key):
            raise RuntimeError("storage down")

    metadata = InMemoryMetadataStore()
    sdk = _sdk(metadata, BrokenExists())
    _upload(sdk)
    with pytest.raises(StorageError):
        sdk.inspect_document("doc-1", partition=DEFAULT_PARTITION)
