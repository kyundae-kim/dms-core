from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from dms.domain.interfaces import PutObjectRequest, StoredObject
from dms.domain.models import DocumentMetadata, DocumentStatus
from dms.sdk import UploadDocumentRequest
from dms.sdk.errors import (
    ConfigurationError,
    ConsistencyError,
    DocumentNotFoundError,
    DuplicateDocumentError,
    MetadataStoreError,
)
from dms.sdk.factory import create_sdk, create_sdk_from_environment


class InMemoryMetadataStore:
    def __init__(self) -> None:
        self._items: dict[str, DocumentMetadata] = {}

    def save_metadata(self, metadata: DocumentMetadata) -> DocumentMetadata:
        self._items[metadata.document_id] = metadata
        return metadata

    def get_metadata(self, document_id: str) -> DocumentMetadata:
        try:
            return self._items[document_id]
        except KeyError as exc:
            raise LookupError(document_id) from exc

    def mark_deleted(self, document_id: str) -> DocumentMetadata:
        metadata = self.get_metadata(document_id)
        deleted = replace(
            metadata,
            status=DocumentStatus.DELETED,
            deleted_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        self._items[document_id] = deleted
        return deleted

    def hard_delete(self, document_id: str) -> None:
        if document_id not in self._items:
            raise LookupError(document_id)
        del self._items[document_id]

    def exists(self, document_id: str) -> bool:
        return document_id in self._items


class FailingMetadataStore(InMemoryMetadataStore):
    def save_metadata(self, metadata: DocumentMetadata) -> DocumentMetadata:
        raise RuntimeError("db down")


class ExplodingReadMetadataStore(InMemoryMetadataStore):
    def get_metadata(self, document_id: str) -> DocumentMetadata:
        raise RuntimeError("db down")


class InMemoryObjectStore:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str], StoredObject] = {}

    def put_object(self, request: PutObjectRequest) -> str:
        self._items[(request.document_id, request.storage_key)] = StoredObject(
            document_id=request.document_id,
            storage_key=request.storage_key,
            content=request.content,
            content_type=request.content_type,
            filename=request.filename,
            size=len(request.content),
            checksum=request.checksum,
        )
        return request.storage_key

    def get_object(self, document_id: str, storage_key: str) -> StoredObject:
        try:
            return self._items[(document_id, storage_key)]
        except KeyError as exc:
            raise LookupError(document_id) from exc

    def delete_object(self, document_id: str, storage_key: str) -> None:
        try:
            del self._items[(document_id, storage_key)]
        except KeyError as exc:
            raise LookupError(document_id) from exc

    def object_exists(self, document_id: str, storage_key: str) -> bool:
        return (document_id, storage_key) in self._items


class RecordingCloser:
    def __init__(self) -> None:
        self.closed = False

    def __call__(self) -> None:
        self.closed = True


class HealthyCheck:
    def __call__(self) -> None:
        return None


class FailingCheck:
    def __call__(self) -> None:
        raise RuntimeError("dependency unavailable")


@pytest.fixture
def stores() -> tuple[InMemoryMetadataStore, InMemoryObjectStore]:
    return InMemoryMetadataStore(), InMemoryObjectStore()


def test_upload_document_persists_metadata_and_content(stores: tuple[InMemoryMetadataStore, InMemoryObjectStore]) -> None:
    metadata_store, object_store = stores

    sdk = create_sdk(metadata_store=metadata_store, object_store=object_store)

    result = sdk.upload_document(
        UploadDocumentRequest(
            content=b"hello world",
            filename="greeting.txt",
            content_type="text/plain",
            metadata={"category": "sample"},
            created_by="tester",
        )
    )

    assert result.created is True
    assert result.metadata.document_id == result.document_id
    assert result.metadata.status == DocumentStatus.AVAILABLE
    assert result.metadata.file_size == 11
    assert result.metadata.extra_metadata == {"category": "sample"}

    content = sdk.get_document_content(result.document_id)
    assert content.content == b"hello world"
    assert content.filename == "greeting.txt"
    assert content.size == 11


def test_upload_document_rejects_duplicate_document_id(stores: tuple[InMemoryMetadataStore, InMemoryObjectStore]) -> None:
    metadata_store, object_store = stores
    sdk = create_sdk(metadata_store=metadata_store, object_store=object_store)
    request = UploadDocumentRequest(
        document_id="doc-1",
        content=b"v1",
        filename="doc.txt",
        content_type="text/plain",
    )

    sdk.upload_document(request)

    with pytest.raises(DuplicateDocumentError):
        sdk.upload_document(request)


def test_upload_document_cleans_up_object_when_metadata_save_fails() -> None:
    metadata_store = FailingMetadataStore()
    object_store = InMemoryObjectStore()
    sdk = create_sdk(metadata_store=metadata_store, object_store=object_store)

    with pytest.raises(ConsistencyError):
        sdk.upload_document(
            UploadDocumentRequest(
                document_id="doc-1",
                content=b"payload",
                filename="broken.txt",
                content_type="text/plain",
            )
        )

    assert object_store.object_exists("doc-1", "documents/doc-1/broken.txt") is False


def test_delete_document_soft_delete_marks_metadata_and_removes_content(stores: tuple[InMemoryMetadataStore, InMemoryObjectStore]) -> None:
    metadata_store, object_store = stores
    sdk = create_sdk(metadata_store=metadata_store, object_store=object_store)
    result = sdk.upload_document(
        UploadDocumentRequest(
            document_id="doc-1",
            content=b"payload",
            filename="delete-me.txt",
            content_type="text/plain",
        )
    )

    deleted = sdk.delete_document("doc-1")

    assert deleted.deleted is True
    assert deleted.hard_deleted is False
    assert deleted.status == DocumentStatus.DELETED
    assert object_store.object_exists("doc-1", result.storage_key) is False
    assert metadata_store.get_metadata("doc-1").status == DocumentStatus.DELETED


def test_delete_document_hard_delete_removes_metadata(stores: tuple[InMemoryMetadataStore, InMemoryObjectStore]) -> None:
    metadata_store, object_store = stores
    sdk = create_sdk(metadata_store=metadata_store, object_store=object_store)
    sdk.upload_document(
        UploadDocumentRequest(
            document_id="doc-1",
            content=b"payload",
            filename="delete-me.txt",
            content_type="text/plain",
        )
    )

    deleted = sdk.delete_document("doc-1", hard_delete=True)

    assert deleted.deleted is True
    assert deleted.hard_deleted is True
    with pytest.raises(LookupError):
        metadata_store.get_metadata("doc-1")


def test_get_document_content_raises_consistency_error_when_object_is_missing(stores: tuple[InMemoryMetadataStore, InMemoryObjectStore]) -> None:
    metadata_store, object_store = stores
    sdk = create_sdk(metadata_store=metadata_store, object_store=object_store)
    result = sdk.upload_document(
        UploadDocumentRequest(
            document_id="doc-1",
            content=b"payload",
            filename="ghost.txt",
            content_type="text/plain",
        )
    )
    object_store.delete_object("doc-1", result.storage_key)

    with pytest.raises(ConsistencyError):
        sdk.get_document_content("doc-1")


def test_get_document_metadata_raises_document_not_found_for_missing_id(stores: tuple[InMemoryMetadataStore, InMemoryObjectStore]) -> None:
    metadata_store, object_store = stores
    sdk = create_sdk(metadata_store=metadata_store, object_store=object_store)

    with pytest.raises(DocumentNotFoundError):
        sdk.get_document_metadata("missing")


def test_get_document_metadata_raises_metadata_store_error_for_backend_failure() -> None:
    sdk = create_sdk(metadata_store=ExplodingReadMetadataStore(), object_store=InMemoryObjectStore())

    with pytest.raises(MetadataStoreError):
        sdk.get_document_metadata("doc-1")


def test_check_health_reports_service_failures(stores: tuple[InMemoryMetadataStore, InMemoryObjectStore]) -> None:
    metadata_store, object_store = stores
    sdk = create_sdk(
        metadata_store=metadata_store,
        object_store=object_store,
        service_checks={"metadata": HealthyCheck(), "object": FailingCheck()},
    )

    health = sdk.check_health()

    assert health.ok is False
    assert {service.service: service.ok for service in health.services} == {
        "metadata": True,
        "object": False,
    }
    assert health.services[1].error == "dependency unavailable"


def test_close_invokes_registered_cleanup_callbacks(stores: tuple[InMemoryMetadataStore, InMemoryObjectStore]) -> None:
    metadata_store, object_store = stores
    closer = RecordingCloser()
    sdk = create_sdk(
        metadata_store=metadata_store,
        object_store=object_store,
        close_callbacks=[closer],
    )

    sdk.close()

    assert closer.closed is True


def test_create_sdk_from_environment_wraps_core_config_errors(tmp_path: Path) -> None:
    env = {
        "SQLITE_PATH": str(tmp_path / "metadata.db"),
    }

    with pytest.raises(ConfigurationError):
        create_sdk_from_environment(env)
