from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
from docmesh_py_core import AccessTokenResult, AuthenticatedUser
from sqlalchemy import create_engine, inspect

from dms.domain.interfaces import PutObjectRequest
from dms.domain.models import DocumentStatus
from dms.infrastructure.metadata.postgres import PostgresMetadataStore
from dms.infrastructure.metadata.sqlite import SqliteMetadataStore
from dms.infrastructure.storage.minio import MinioObjectStore
from dms.sdk import UploadDocumentRequest
from dms.sdk.errors import HealthCheckFailedError
from dms.sdk.factory import create_sdk, create_sdk_from_environment
from dms.sdk.implementation import DefaultDocumentManagementSDK


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


class FailingWrapper(FakeWrapper):
    def check(self) -> None:
        self.checked = True
        raise RuntimeError("postgres unavailable")


class FakeKeycloakClient:
    def fetch_access_token(self, *, scope: str | None = None) -> AccessTokenResult:
        return AccessTokenResult(access_token="token-123", token_type="Bearer", expires_in=300, scope=scope)

    def extract_user_info(self, token: str) -> AuthenticatedUser:
        return AuthenticatedUser(
            sub="user-1",
            preferred_username="tester",
            email=None,
            given_name=None,
            family_name=None,
            name=None,
            realm_roles=["reader"],
            client_roles={"dms": ["reader"]},
            claims={"sub": "user-1"},
        )


class FakeRegistry:
    def __init__(
        self,
        settings: object,
        postgres_wrapper: FakeWrapper | None,
        minio_wrapper: FakeWrapper,
        sqlite_wrapper: FakeWrapper | None = None,
        keycloak_wrapper: FakeWrapper | None = None,
    ) -> None:
        self.settings = settings
        self.postgres_wrapper = postgres_wrapper
        self.minio_wrapper = minio_wrapper
        self.sqlite_wrapper = sqlite_wrapper
        self.keycloak_wrapper = keycloak_wrapper
        self.closed = False

    def create_client(self, service_name: str) -> FakeWrapper:
        if service_name == "postgres":
            if self.postgres_wrapper is None:
                raise KeyError(service_name)
            return self.postgres_wrapper
        if service_name == "sqlite":
            if self.sqlite_wrapper is None:
                raise KeyError(service_name)
            return self.sqlite_wrapper
        if service_name == "minio":
            return self.minio_wrapper
        if service_name == "keycloak":
            if self.keycloak_wrapper is None:
                raise KeyError(service_name)
            return self.keycloak_wrapper
        raise KeyError(service_name)

    def close_all(self) -> None:
        self.closed = True
        if self.postgres_wrapper is not None:
            self.postgres_wrapper.close()
        if self.sqlite_wrapper is not None:
            self.sqlite_wrapper.close()
        if self.keycloak_wrapper is not None:
            self.keycloak_wrapper.close()
        self.minio_wrapper.close()


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
    import docmesh_py_core

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
    fake_registry = FakeRegistry(settings, postgres_wrapper, minio_wrapper)

    monkeypatch.setattr(docmesh_py_core, "load_settings", lambda env: settings)
    monkeypatch.setattr(docmesh_py_core, "ServiceFactoryRegistry", lambda loaded_settings: fake_registry)

    sdk = create_sdk_from_environment({"MINIO_BUCKET": "documents"})
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
    assert fake_registry.closed is True


def test_create_sdk_from_environment_builds_sdk_with_sqlite_and_minio(monkeypatch: pytest.MonkeyPatch) -> None:
    import docmesh_py_core

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
    fake_registry = FakeRegistry(settings, None, minio_wrapper, sqlite_wrapper=sqlite_wrapper)

    monkeypatch.setattr(docmesh_py_core, "load_settings", lambda env: settings)
    monkeypatch.setattr(docmesh_py_core, "ServiceFactoryRegistry", lambda loaded_settings: fake_registry)

    sdk = create_sdk_from_environment({"SQLITE_PATH": ":memory:", "MINIO_BUCKET": "documents"})
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


def test_create_sdk_accepts_environment_mapping_public_entrypoint(monkeypatch: pytest.MonkeyPatch) -> None:
    import docmesh_py_core

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
    fake_registry = FakeRegistry(settings, postgres_wrapper, minio_wrapper)

    monkeypatch.setattr(docmesh_py_core, "load_settings", lambda env: settings)
    monkeypatch.setattr(docmesh_py_core, "ServiceFactoryRegistry", lambda loaded_settings: fake_registry)

    sdk = create_sdk({"MINIO_BUCKET": "documents"})

    assert isinstance(sdk, DefaultDocumentManagementSDK)
    assert postgres_wrapper.checked is True
    assert minio_wrapper.checked is True

    sdk.close()
    assert fake_registry.closed is True


def test_create_sdk_from_environment_enables_keycloak_when_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    import docmesh_py_core

    postgres_engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    minio_client = FakeMinioClient()
    postgres_wrapper = FakeWrapper(postgres_engine)
    minio_wrapper = FakeWrapper(minio_client)
    keycloak_wrapper = FakeWrapper(FakeKeycloakClient())
    settings = SimpleNamespace(
        minio=SimpleNamespace(bucket="documents"),
        postgres=SimpleNamespace(),
        sqlite=None,
        common=SimpleNamespace(healthcheck_enabled=True),
    )
    fake_registry = FakeRegistry(
        settings,
        postgres_wrapper,
        minio_wrapper,
        keycloak_wrapper=keycloak_wrapper,
    )

    monkeypatch.setattr(docmesh_py_core, "load_settings", lambda env: settings)
    monkeypatch.setattr(docmesh_py_core, "ServiceFactoryRegistry", lambda loaded_settings: fake_registry)

    sdk = create_sdk_from_environment({"MINIO_BUCKET": "documents", "DMS_AUTH_ENABLED": "true"})
    user = sdk.get_authenticated_user("Bearer token")
    health = sdk.check_health()

    assert user.sub == "user-1"
    assert keycloak_wrapper.checked is True
    assert {service.service for service in health.services} == {"postgres", "minio", "keycloak"}

    sdk.close()
    assert fake_registry.closed is True


def test_create_sdk_from_environment_raises_when_startup_health_check_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    import docmesh_py_core

    postgres_engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    minio_client = FakeMinioClient()
    postgres_wrapper = FailingWrapper(postgres_engine)
    minio_wrapper = FakeWrapper(minio_client)
    settings = SimpleNamespace(
        minio=SimpleNamespace(bucket="documents"),
        postgres=SimpleNamespace(),
        sqlite=None,
        common=SimpleNamespace(healthcheck_enabled=True),
    )
    fake_registry = FakeRegistry(settings, postgres_wrapper, minio_wrapper)

    monkeypatch.setattr(docmesh_py_core, "load_settings", lambda env: settings)
    monkeypatch.setattr(docmesh_py_core, "ServiceFactoryRegistry", lambda loaded_settings: fake_registry)

    with pytest.raises(HealthCheckFailedError):
        create_sdk_from_environment({"MINIO_BUCKET": "documents"})


def test_env_example_contains_required_configuration() -> None:
    content = Path("/workspaces/dms-core/.env.example").read_text(encoding="utf-8")

    for required_key in [
        "DOCMESH_ENV=",
        "DOCMESH_HEALTHCHECK_ENABLED=",
        "KEYCLOAK_URL=",
        "KEYCLOAK_REALM=",
        "KEYCLOAK_CLIENT_ID=",
        "KEYCLOAK_CLIENT_SECRET=",
        "POSTGRES_DSN=",
        "MINIO_ENDPOINT=",
        "MINIO_ACCESS_KEY=",
        "MINIO_SECRET_KEY=",
        "MINIO_BUCKET=",
    ]:
        assert required_key in content
