from __future__ import annotations

import pytest

from dms import (
    DefaultDocumentManagementSDK,
    DocumentDeletedError,
    PublicDocumentMetadata,
    UploadDocumentRequest,
)
from test_dms.sdk_test_support import CursorMemoryStore, StreamMemoryObjectStore


def _sdk():
    return DefaultDocumentManagementSDK(
        metadata_store=CursorMemoryStore(),
        object_store=StreamMemoryObjectStore(),
    )


def test_deleted_document_content_and_stream_raise_deleted_error() -> None:
    sdk = _sdk()
    result = sdk.upload_document(
        UploadDocumentRequest(
            document_id="deleted",
            content=b"content",
            filename="deleted.txt",
            content_type="text/plain",
        )
    )
    sdk.soft_delete_document(result.document_id)

    with pytest.raises(DocumentDeletedError) as content_error:
        sdk.get_document_content(result.document_id)
    with pytest.raises(DocumentDeletedError):
        sdk.get_document_content_stream(result.document_id)

    assert content_error.value.code == "document_deleted"
    assert content_error.value.retryable is False
    assert content_error.value.document_id == result.document_id


def test_default_metadata_and_upload_results_hide_storage_key() -> None:
    sdk = _sdk()
    result = sdk.upload_document(
        UploadDocumentRequest(
            document_id="public",
            content=b"content",
            filename="public.txt",
            content_type="text/plain",
        )
    )

    metadata = sdk.get_document_metadata(result.document_id)
    listed = sdk.list_documents()
    page = sdk.list_documents_page()

    assert isinstance(result.metadata, PublicDocumentMetadata)
    assert isinstance(metadata, PublicDocumentMetadata)
    assert all(isinstance(item, PublicDocumentMetadata) for item in listed)
    assert all(isinstance(item, PublicDocumentMetadata) for item in page.items)
    assert not hasattr(result, "storage_key")
    assert not hasattr(metadata, "storage_key")


def test_privileged_metadata_access_is_explicit() -> None:
    sdk = _sdk()
    result = sdk.upload_document(
        UploadDocumentRequest(content=b"x", filename="x.txt", content_type="text/plain")
    )

    internal = sdk.get_internal_document_metadata(result.document_id)

    assert internal.storage_key.startswith("documents/")
