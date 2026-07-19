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
from dms.sdk.factory import create_sdk_from_components, create_sdk_from_environment, diagnose_environment
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


def test_create_sdk_from_environment_builds_sdk_with_postgres_and_minio(monkeypatch: pytest.MonkeyPatch) -> None:
    import dms.sdk.factory as factory_module

    _set_process_environment(monkeypatch, _POSTGRES_ENV)

    postgres_engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    minio_client = FakeMinioClient()
    postgres_wrapper = FakeWrapper(postgres_engine)
    minio_wrapper = FakeWrapper(minio_client)
    settings = SimpleNamespace(
        minio=SimpleNamespace(bucket="documents"),
        postgres=SimpleNamespace(),
        sqlite=None,
        common=SimpleNamespace(healthcheck_enabled=True),
    )
    close_calls: list[list[object]] = []

    bundle = fake_service_bundle(
        settings,
        {"postgres": postgres_wrapper, "minio": minio_wrapper},
        close_calls,
    )
    monkeypatch.setattr(factory_module, "assemble_services", lambda **options: bundle)

    sdk = create_sdk_from_environment()
    result = sdk.upload_document(
        UploadDocumentRequest(
            document_id="doc-1",
            content=b"payload",
            filename="doc.txt",
            content_type="text/plain",
        )
    )

    assert isinstance(sdk, DefaultDocumentManagementSDK)
    assert result.document_id == "doc-1"
    assert postgres_wrapper.checked is True
    assert minio_wrapper.checked is True
    health = sdk.check_health()
    assert health.ok is True

    sdk.close()
    assert close_calls == [[postgres_wrapper, minio_wrapper]]


def test_create_sdk_from_environment_builds_sdk_with_sqlite_and_minio(monkeypatch: pytest.MonkeyPatch) -> None:
    import dms.sdk.factory as factory_module

    _set_process_environment(monkeypatch, _SQLITE_ENV)

    sqlite_engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    minio_client = FakeMinioClient()
    sqlite_wrapper = FakeWrapper(sqlite_engine)
    minio_wrapper = FakeWrapper(minio_client)
    settings = SimpleNamespace(
        minio=SimpleNamespace(bucket="documents"),
        postgres=None,
        sqlite=SimpleNamespace(path=":memory:"),
        common=SimpleNamespace(healthcheck_enabled=True),
    )
    close_calls: list[list[object]] = []

    bundle = fake_service_bundle(
        settings,
        {"sqlite": sqlite_wrapper, "minio": minio_wrapper},
        close_calls,
    )
    monkeypatch.setattr(factory_module, "assemble_services", lambda **options: bundle)

    sdk = create_sdk_from_environment()
    result = sdk.upload_document(
        UploadDocumentRequest(
            document_id="doc-1",
            content=b"payload",
            filename="doc.txt",
            content_type="text/plain",
        )
    )

    assert isinstance(sdk, DefaultDocumentManagementSDK)
    assert isinstance(sdk._metadata_store, SqliteMetadataStore)
    assert result.document_id == "doc-1"
    assert sqlite_wrapper.checked is True
    assert minio_wrapper.checked is True

    sdk.close()
    assert close_calls == [[sqlite_wrapper, minio_wrapper]]


def test_create_sdk_from_environment_reads_process_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    import dms.sdk.factory as factory_module

    _set_process_environment(monkeypatch, _POSTGRES_ENV)

    postgres_engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    minio_client = FakeMinioClient()
    postgres_wrapper = FakeWrapper(postgres_engine)
    minio_wrapper = FakeWrapper(minio_client)
    settings = SimpleNamespace(
        minio=SimpleNamespace(bucket="documents"),
        postgres=SimpleNamespace(),
        sqlite=None,
        common=SimpleNamespace(healthcheck_enabled=True),
    )
    close_calls: list[list[object]] = []

    bundle = fake_service_bundle(
        settings,
        {"postgres": postgres_wrapper, "minio": minio_wrapper},
        close_calls,
    )
    monkeypatch.setattr(factory_module, "assemble_services", lambda **options: bundle)

    sdk = create_sdk_from_environment()

    assert isinstance(sdk, DefaultDocumentManagementSDK)
    assert postgres_wrapper.checked is True
    assert minio_wrapper.checked is True

    sdk.close()
    assert close_calls == [[postgres_wrapper, minio_wrapper]]


def test_create_sdk_from_environment_uses_v04_keyword_only_assembly_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import dms.sdk.factory as factory_module

    _set_process_environment(monkeypatch, _SQLITE_ENV)

    sqlite_wrapper = FakeWrapper(create_engine("sqlite+pysqlite:///:memory:", future=True))
    minio_wrapper = FakeWrapper(FakeMinioClient())
    bundle = SimpleNamespace(
        configs=SimpleNamespace(
            minio=SimpleNamespace(bucket="documents"),
            postgres=None,
            sqlite=SimpleNamespace(path=":memory:"),
        ),
        checks={"sqlite": sqlite_wrapper.check, "minio": minio_wrapper.check},
        close=lambda: None,
        get_client={"sqlite": sqlite_wrapper, "minio": minio_wrapper}.__getitem__,
    )
    calls: list[dict[str, object]] = []

    def assemble_services(*, services, required, one_of, check_on_startup, parallel_healthchecks=False):
        calls.append(
            {
                "services": services,
                "required": required,
                "one_of": one_of,
                "check_on_startup": check_on_startup,
                "parallel_healthchecks": parallel_healthchecks,
            }
        )
        return bundle

    monkeypatch.setattr(factory_module, "assemble_services", assemble_services)

    sdk = create_sdk_from_environment()
    sdk.close()

    assert calls == [
        {
            "services": {"sqlite", "minio"},
            "required": {"sqlite", "minio"},
            "one_of": (),
            "check_on_startup": True,
            "parallel_healthchecks": False,
        }
    ]


def test_create_sdk_from_environment_raises_when_startup_health_check_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    import dms.sdk.factory as factory_module

    _set_process_environment(monkeypatch, _POSTGRES_ENV)

    postgres_engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    minio_client = FakeMinioClient()
    postgres_wrapper = FailingWrapper(postgres_engine)
    minio_wrapper = FakeWrapper(minio_client)
    close_calls: list[list[object]] = []

    def failing_assemble_services(**options):
        assert options["check_on_startup"] is True
        close_calls.append([postgres_wrapper, minio_wrapper])
        raise HealthCheckError(
            ServiceHealthStatus(
                service="postgres",
                ok=False,
                latency_ms=0,
                required=True,
                error="postgres unavailable",
            )
        )

    monkeypatch.setattr(factory_module, "assemble_services", failing_assemble_services)

    with pytest.raises(HealthCheckFailedError):
        create_sdk_from_environment()

    assert close_calls == [[postgres_wrapper, minio_wrapper]]


@pytest.mark.parametrize(
    ("service", "expected_error"),
    [("minio", StorageError), ("postgres", MetadataStoreError)],
)
def test_create_sdk_from_environment_maps_service_client_errors(
    monkeypatch: pytest.MonkeyPatch,
    service: str,
    expected_error: type[Exception],
) -> None:
    import dms.sdk.factory as factory_module

    _set_process_environment(monkeypatch, _SQLITE_ENV)

    def failing_assemble_services(**options):
        raise ServiceClientError(
            service=service,
            operation="create",
            error_type="RuntimeError",
            error="dependency unavailable",
        )

    monkeypatch.setattr(factory_module, "assemble_services", failing_assemble_services)

    with pytest.raises(expected_error):
        create_sdk_from_environment()


def test_create_sdk_from_environment_closes_bundle_when_dms_adapter_assembly_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    import dms.sdk.factory as factory_module

    _set_process_environment(monkeypatch, _POSTGRES_ENV)

    postgres_wrapper = FakeWrapper(create_engine("sqlite+pysqlite:///:memory:", future=True))
    minio_wrapper = FakeWrapper(FakeMinioClient())
    settings = SimpleNamespace(
        minio=SimpleNamespace(bucket=None),
        postgres=SimpleNamespace(),
        sqlite=None,
    )
    close_calls: list[list[object]] = []
    bundle = fake_service_bundle(
        settings,
        {"postgres": postgres_wrapper, "minio": minio_wrapper},
        close_calls,
    )
    monkeypatch.setattr(factory_module, "assemble_services", lambda **options: bundle)

    with pytest.raises(ConfigurationError):
        create_sdk_from_environment()

    assert close_calls == [[postgres_wrapper, minio_wrapper]]


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


def test_diagnose_environment_rejects_deprecated_postgres_dsn() -> None:
    diagnosis = diagnose_environment(
        {
            "POSTGRES_DSN": "postgresql://user:***@localhost/dms",
            "MINIO_ENDPOINT": "localhost:9000",
            "MINIO_ACCESS_KEY": "access",
            "MINIO_SECRET_KEY": "secret",
            "MINIO_BUCKET": "documents",
        }
    )

    assert diagnosis.valid is False
    assert "POSTGRES_HOST" in diagnosis.missing_required_keys
    assert "postgresql://user:***@localhost/dms" not in repr(diagnosis)


def test_diagnose_environment_uses_core_production_security_diagnosis() -> None:
    diagnosis = diagnose_environment(
        {
            "DOCMESH_ENV": "production",
            "POSTGRES_HOST": "localhost",
            "POSTGRES_PORT": "5432",
            "POSTGRES_DB": "dms",
            "POSTGRES_USER": "dms",
            "POSTGRES_PASSWORD": "replace-me",
            "MINIO_ENDPOINT": "minio.example.com:9000",
            "MINIO_ACCESS_KEY": "access",
            "MINIO_SECRET_KEY": "replace-me",
            "MINIO_BUCKET": "documents",
            "MINIO_SECURE": "true",
        }
    )

    assert diagnosis.valid is False
    assert diagnosis.missing_required_keys == ()
    assert diagnosis.warnings
