from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
from docmesh_py_core import HealthCheckError, ServiceClientError, ServiceHealthStatus
from sqlalchemy import create_engine, inspect

from dms.domain.interfaces import PutObjectRequest
from dms.domain.models import DocumentStatus
from dms.infrastructure.metadata.postgres import PostgresMetadataStore
from dms.infrastructure.metadata.sqlite import SqliteMetadataStore
from dms.infrastructure.storage.minio import MinioObjectStore
from dms.sdk import UploadDocumentRequest
from dms.sdk.errors import ConfigurationError, HealthCheckFailedError, MetadataStoreError, StorageError
from dms.sdk.factory import create_sdk_from_components
from dms.sdk.implementation import DefaultDocumentManagementSDK


_ENVIRONMENT_PREFIXES = ("DMS_", "DOCMESH_", "POSTGRES_", "SQLITE_", "MINIO_")
_MINIO_ENV = {
    "MINIO_ENDPOINT": "minio:9000",
    "MINIO_ACCESS_KEY": "access",
    "MINIO_SECRET_KEY": "secret",
    "MINIO_BUCKET": "documents",
}
_POSTGRES_ENV = {
    "DMS_METADATA_BACKEND": "postgresql",
    "POSTGRES_HOST": "postgres",
    "POSTGRES_DB": "dms",
    "POSTGRES_USER": "dms",
    "POSTGRES_PASSWORD": "secret",
    **_MINIO_ENV,
}
_SQLITE_ENV = {
    "DMS_METADATA_BACKEND": "sqlite",
    "SQLITE_PATH": ":memory:",
    **_MINIO_ENV,
}


def _set_process_environment(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    for key in tuple(os.environ):
        if key.startswith(_ENVIRONMENT_PREFIXES):
            monkeypatch.delenv(key)
    for key, value in env.items():
        monkeypatch.setenv(key, value)


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


@dataclass
class FakeWrapper:
    client: object
    checked: bool = False
    closed: bool = False

    def check(self) -> None:
        self.checked = True

    def close(self) -> None:
        self.closed = True

    def unwrap(self) -> object:
        return self.client


class FailingWrapper(FakeWrapper):
    def check(self) -> None:
        self.checked = True
        raise RuntimeError("postgres unavailable")


def fake_service_bundle(
    settings: SimpleNamespace,
    clients: dict[str, FakeWrapper],
    close_calls: list[list[object]],
) -> SimpleNamespace:
    for wrapper in clients.values():
        wrapper.check()
    return SimpleNamespace(
        configs=settings,
        checks={name: wrapper.check for name, wrapper in clients.items()},
        close=lambda: close_calls.append(list(clients.values())),
        get_client=clients.__getitem__,
    )


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
















def test_env_example_contains_required_configuration() -> None:
    content = Path("/workspaces/dms-core/.env.example").read_text(encoding="utf-8")

    for required_key in [
        "DOCMESH_ENV=",
        "DOCMESH_HEALTHCHECK_ENABLED=",
        "POSTGRES_HOST=",
        "POSTGRES_PORT=",
        "POSTGRES_DB=",
        "POSTGRES_USER=",
        "POSTGRES_PASSWORD=",
        "MINIO_ENDPOINT=",
        "MINIO_ACCESS_KEY=",
        "MINIO_SECRET_KEY=",
        "MINIO_BUCKET=",
    ]:
        assert required_key in content

    assert "POSTGRES_DSN=" not in content
