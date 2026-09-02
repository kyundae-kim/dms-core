from __future__ import annotations

from dms.sdk import UploadDocumentRequest
from dms.sdk.implementation import DefaultDocumentManagementSDK
from test_dms.sdk_test_support import (
    DEFAULT_PARTITION,
    CursorMemoryStore,
    StreamMemoryObjectStore,
)


def _sdk(metadata_store=None, operation_store=None):
    return DefaultDocumentManagementSDK(
        metadata_store=metadata_store or CursorMemoryStore(),
        object_store=StreamMemoryObjectStore(),
        operation_store=operation_store,
    )


def _request(document_id: str, **kwargs):
    return UploadDocumentRequest(
        document_id=document_id,
        content=b"x",
        filename=f"{document_id}.txt",
        content_type="text/plain",
        **kwargs,
    )


def test_explicit_delete_methods_preserve_legacy_dispatch():
    sdk = _sdk()
    sdk.upload_document(_request("soft"), partition=DEFAULT_PARTITION)
    sdk.upload_document(_request("hard"), partition=DEFAULT_PARTITION)
    sdk.upload_document(_request("legacy"), partition=DEFAULT_PARTITION)
    assert (
        sdk.soft_delete_document("soft", partition=DEFAULT_PARTITION).hard_deleted
        is False
    )
    assert (
        sdk.hard_delete_document("hard", partition=DEFAULT_PARTITION).hard_deleted
        is True
    )
    assert (
        sdk.delete_document(
            "legacy", hard_delete=True, partition=DEFAULT_PARTITION
        ).hard_deleted
        is True
    )
