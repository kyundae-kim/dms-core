from __future__ import annotations

from io import BytesIO

import pytest

from dms.domain.interfaces import MetadataConflictError
from dms.sdk import UploadDocumentRequest
from dms.sdk.errors import DuplicateDocumentError
from dms.sdk.implementation import DefaultDocumentManagementSDK
from dms.sdk.types import DocumentContentStream
from test_dms.sdk_test_support import (
    DEFAULT_PARTITION,
    InMemoryMetadataStore,
    InMemoryObjectStore,
)


class DuplicateOnSaveMetadataStore(InMemoryMetadataStore):
    def save_metadata(self, metadata):
        raise MetadataConflictError("duplicate key")


class CountingStream(BytesIO):
    def __init__(self, value: bytes) -> None:
        super().__init__(value)
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1
        super().close()


def test_document_content_stream_context_manager_closes_idempotently() -> None:
    stream = CountingStream(b"payload")
    content = DocumentContentStream(
        document_id="doc",
        stream=stream,
        content_type="text/plain",
        filename="doc.txt",
        size=7,
    )

    with content as entered:
        assert entered is content
    content.close()

    assert stream.close_calls == 1


def test_upload_document_maps_database_conflict_to_duplicate_and_rolls_back_object() -> (
    None
):
    object_store = InMemoryObjectStore()
    sdk = DefaultDocumentManagementSDK(
        metadata_store=DuplicateOnSaveMetadataStore(), object_store=object_store
    )

    with pytest.raises(DuplicateDocumentError):
        sdk.upload_document(
            UploadDocumentRequest(
                document_id="raced-doc",
                content=b"payload",
                filename="race.txt",
                content_type="text/plain",
            ),
            partition=DEFAULT_PARTITION,
        )

    assert object_store._items == {}
