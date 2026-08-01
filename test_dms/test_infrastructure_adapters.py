from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, inspect

from dms.domain.interfaces import PutObjectRequest
from dms.domain.models import DocumentStatus
from dms.infrastructure.metadata.postgres import PostgresMetadataStore
from dms.infrastructure.storage.minio import MinioObjectStore
from dms.sdk import UploadDocumentRequest, create_sdk_from_clients


class FakeMinioResponse:
    def __init__(self, data: bytes, content_type: str) -> None:
        self.data = data
        self._cursor = 0
        self.headers = {"Content-Type": content_type}
        self.closed = False
        self.released = False

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self.data) - self._cursor
        chunk = self.data[self._cursor : self._cursor + size]
        self._cursor += len(chunk)
        return chunk

    def close(self) -> None:
        self.closed = True

    def release_conn(self) -> None:
        self.released = True


class FakeMinioClient:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], dict[str, object]] = {}

    def put_object(self, bucket_name: str, object_name: str, data, length: int, content_type: str, metadata=None):
        payload = data.read()
        self.objects[(bucket_name, object_name)] = {
            "data": payload,
            "content_type": content_type,
            "length": length,
            "metadata": metadata or {},
        }
        return SimpleNamespace(object_name=object_name)

    def get_object(self, bucket_name: str, object_name: str):
        try:
            item = self.objects[(bucket_name, object_name)]
        except KeyError as exc:
            raise FileNotFoundError(object_name) from exc
        return FakeMinioResponse(item["data"], item["content_type"])

    def stat_object(self, bucket_name: str, object_name: str):
        try:
            item = self.objects[(bucket_name, object_name)]
        except KeyError as exc:
            raise FileNotFoundError(object_name) from exc
        return SimpleNamespace(size=item["length"], metadata=item["metadata"], object_name=object_name)

    def remove_object(self, bucket_name: str, object_name: str) -> None:
        try:
            del self.objects[(bucket_name, object_name)]
        except KeyError as exc:
            raise FileNotFoundError(object_name) from exc

    def list_objects(self, bucket_name: str, *, prefix: str, recursive: bool):
        assert recursive is True
        return [
            SimpleNamespace(object_name=object_name)
            for bucket, object_name in self.objects
            if bucket == bucket_name and object_name.startswith(prefix)
        ]


@pytest.fixture
def metadata_store() -> PostgresMetadataStore:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    return PostgresMetadataStore(engine)


@pytest.fixture
def object_store() -> MinioObjectStore:
    return MinioObjectStore(client=FakeMinioClient(), bucket_name="documents")


def test_postgres_metadata_store_round_trip(metadata_store: PostgresMetadataStore) -> None:
    saved = metadata_store.save_metadata(
        metadata_store.build_metadata(
            document_id="doc-1",
            filename="report.pdf",
            content_type="application/pdf",
            file_size=3,
            storage_key="documents/doc-1/report.pdf",
            checksum="abc",
            created_by="tester",
            extra_metadata={"team": "alpha"},
        )
    )

    loaded = metadata_store.get_metadata("doc-1")
    deleted = metadata_store.mark_deleted("doc-1")

    assert saved.document_id == "doc-1"
    assert loaded.extra_metadata == {"team": "alpha"}
    assert deleted.status == DocumentStatus.DELETED
    assert metadata_store.exists("doc-1") is True

    metadata_store.hard_delete("doc-1")
    assert metadata_store.exists("doc-1") is False


def test_postgres_metadata_store_lists_paginated_metadata_by_status(
    metadata_store: PostgresMetadataStore,
) -> None:
    for document_id, status in (
        ("doc-1", DocumentStatus.AVAILABLE),
        ("doc-2", DocumentStatus.DELETED),
        ("doc-3", DocumentStatus.AVAILABLE),
    ):
        metadata_store.save_metadata(
            metadata_store.build_metadata(
                document_id=document_id,
                filename=f"{document_id}.txt",
                content_type="text/plain",
                file_size=1,
                storage_key=f"documents/{document_id}/{document_id}.txt",
                checksum=None,
                created_by=None,
                status=status,
            )
        )

    page = metadata_store.list_metadata(offset=1, limit=1, status=DocumentStatus.AVAILABLE)

    assert [metadata.document_id for metadata in page] == ["doc-1"]


def test_postgres_metadata_store_creates_lookup_indexes() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    PostgresMetadataStore(engine)

    index_definitions = inspect(engine).get_indexes("document_metadata")
    indexes_by_name = {entry["name"]: tuple(entry["column_names"]) for entry in index_definitions}

    assert indexes_by_name["ix_document_metadata_storage_key"] == ("storage_key",)
    assert indexes_by_name["ix_document_metadata_status"] == ("status",)
    assert indexes_by_name["ix_document_metadata_created_at"] == ("created_at",)


def test_minio_object_store_stream_round_trip(object_store: MinioObjectStore) -> None:
    storage_key = object_store.put_object(
        PutObjectRequest(
            document_id="doc-stream",
            storage_key="documents/doc-stream/report.pdf",
            content=b"stream-payload",
            content_type="application/pdf",
            filename="report.pdf",
            checksum="stream-abc",
            metadata={"team": "alpha"},
        )
    )

    stored = object_store.get_object_stream("doc-stream", storage_key)
    try:
        content = stored.stream.read()
    finally:
        stored.stream.close()
        if hasattr(stored.stream, "release_conn"):
            stored.stream.release_conn()

    assert content == b"stream-payload"
    assert stored.filename == "report.pdf"
    assert stored.checksum == "stream-abc"
    assert stored.size == len(b"stream-payload")


def test_minio_object_store_round_trip(object_store: MinioObjectStore) -> None:
    storage_key = object_store.put_object(
        PutObjectRequest(
            document_id="doc-1",
            storage_key="documents/doc-1/report.pdf",
            content=b"pdf",
            content_type="application/pdf",
            filename="report.pdf",
            checksum="abc",
            metadata={"team": "alpha"},
        )
    )

    stored = object_store.get_object("doc-1", storage_key)

    assert stored.content == b"pdf"
    assert stored.filename == "report.pdf"
    assert stored.checksum == "abc"
    assert object_store.object_exists("doc-1", storage_key) is True

    object_store.delete_object("doc-1", storage_key)
    assert object_store.object_exists("doc-1", storage_key) is False


def test_client_factory_initializes_for_data_load_across_all_stores() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    sdk = create_sdk_from_clients(
        engine=engine,
        minio_client=FakeMinioClient(),
        bucket_name="documents",
    )

    sdk.upload_document(UploadDocumentRequest(
        content=b"payload",
        filename="payload.txt",
        content_type="text/plain",
        idempotency_scope="load",
        idempotency_key="payload-1",
    ))

    result = sdk.initialize_for_data_load()

    assert result.metadata_deleted == 1
    assert result.objects_deleted == 1
    assert result.upload_operations_deleted == 1
    assert sdk.list_documents().items == []
