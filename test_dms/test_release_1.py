from __future__ import annotations

from io import BytesIO

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError

from dms.infrastructure.metadata.postgres import PostgresMetadataStore
from dms.infrastructure.metadata.sqlite import SqliteMetadataStore
from dms.sdk import UploadDocumentRequest
from dms.sdk.errors import DuplicateDocumentError
from dms.sdk.factory import create_sdk_from_components
from test_dms.test_sdk_behavior import InMemoryMetadataStore, InMemoryObjectStore


class CountingCloser:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> None:
        self.calls += 1


class DuplicateOnSaveMetadataStore(InMemoryMetadataStore):
    def save_metadata(self, metadata):
        raise IntegrityError("insert", {}, RuntimeError("duplicate key"))


class CountingStream(BytesIO):
    def __init__(self, value: bytes) -> None:
        super().__init__(value)
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1
        super().close()


def test_sdk_context_manager_returns_sdk_and_closes_idempotently() -> None:
    closer = CountingCloser()
    sdk = create_sdk_from_components(
        metadata_store=InMemoryMetadataStore(), object_store=InMemoryObjectStore(), close_callbacks=[closer]
    )

    with sdk as entered:
        assert entered is sdk
    sdk.close()

    assert closer.calls == 1


def test_document_content_stream_context_manager_closes_idempotently() -> None:
    from dms.sdk.types import DocumentContentStream

    stream = CountingStream(b"payload")
    content = DocumentContentStream(
        document_id="doc", stream=stream, content_type="text/plain", filename="doc.txt", size=7
    )

    with content as entered:
        assert entered is content
    content.close()

    assert stream.close_calls == 1


@pytest.mark.parametrize("store_type", [PostgresMetadataStore, SqliteMetadataStore])
def test_metadata_store_save_is_insert_only_and_preserves_existing_row(store_type) -> None:
    store = store_type(create_engine("sqlite+pysqlite:///:memory:", future=True))
    original = store.build_metadata(
        document_id="doc-conflict", filename="original.txt", content_type="text/plain", file_size=8,
        storage_key="documents/doc-conflict/original.txt", checksum=None, created_by=None,
    )
    replacement = store.build_metadata(
        document_id="doc-conflict", filename="replacement.txt", content_type="text/plain", file_size=11,
        storage_key="documents/doc-conflict/replacement.txt", checksum=None, created_by=None,
    )
    store.save_metadata(original)

    with pytest.raises(IntegrityError):
        store.save_metadata(replacement)

    assert store.get_metadata("doc-conflict").original_filename == "original.txt"


def test_upload_document_maps_database_conflict_to_duplicate_and_rolls_back_object() -> None:
    object_store = InMemoryObjectStore()
    sdk = create_sdk_from_components(metadata_store=DuplicateOnSaveMetadataStore(), object_store=object_store)

    with pytest.raises(DuplicateDocumentError):
        sdk.upload_document(UploadDocumentRequest(
            document_id="raced-doc", content=b"payload", filename="race.txt", content_type="text/plain"
        ))

    assert object_store.object_exists("raced-doc", "documents/raced-doc/race.txt") is False
