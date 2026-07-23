from __future__ import annotations

import os
from collections.abc import Generator
from dataclasses import dataclass
from typing import cast
from uuid import uuid4

import pytest
from docmesh_py_core import load_service_configs
from minio import Minio
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, URL

from dms.domain.interfaces import PutObjectRequest
from dms.domain.models import DocumentStatus
from dms.infrastructure.metadata.postgres import PostgresMetadataStore
from dms.infrastructure.storage.minio import MinioObjectStore
from dms.sdk import UploadDocumentRequest
from dms.sdk.errors import ConsistencyError, DocumentDeletedError, DocumentNotFoundError
from dms.sdk.factory import create_sdk_from_environment, create_sdk_from_service_configs

pytestmark = pytest.mark.integration

_REQUIRED_ENV_KEYS = [
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "MINIO_ENDPOINT",
    "MINIO_ACCESS_KEY",
    "MINIO_SECRET_KEY",
    "MINIO_BUCKET",
]


@dataclass(frozen=True)
class IntegrationServices:
    postgres_engine: Engine
    minio_client: Minio
    bucket_name: str


@pytest.fixture(scope="module")
def integration_services() -> Generator[IntegrationServices, None, None]:
    missing = [key for key in _REQUIRED_ENV_KEYS if not os.environ.get(key)]
    if missing:
        pytest.skip(
            "real integration tests require external services; set "
            + ", ".join(missing)
        )

    postgres_host = cast(str, os.environ["POSTGRES_HOST"])
    postgres_port = int(os.environ["POSTGRES_PORT"])
    postgres_db = cast(str, os.environ["POSTGRES_DB"])
    postgres_user = cast(str, os.environ["POSTGRES_USER"])
    postgres_password = cast(str, os.environ["POSTGRES_PASSWORD"])
    minio_endpoint = cast(str, os.environ["MINIO_ENDPOINT"])
    minio_access_key = cast(str, os.environ["MINIO_ACCESS_KEY"])
    minio_secret_key = cast(str, os.environ["MINIO_SECRET_KEY"])
    bucket_name = cast(str, os.environ["MINIO_BUCKET"])

    pytest.importorskip("psycopg", reason="real PostgreSQL integration tests require psycopg2")

    postgres_engine = create_engine(
        URL.create(
            "postgresql+psycopg",
            username=postgres_user,
            password=postgres_password,
            host=postgres_host,
            port=postgres_port,
            database=postgres_db,
        ),
        future=True,
    )
    minio_client = Minio(
        minio_endpoint,
        access_key=minio_access_key,
        secret_key=minio_secret_key,
        secure=os.environ.get("MINIO_SECURE", "false").lower() == "true",
    )

    if not minio_client.bucket_exists(bucket_name):
        minio_client.make_bucket(bucket_name)

    try:
        yield IntegrationServices(
            postgres_engine=postgres_engine,
            minio_client=minio_client,
            bucket_name=bucket_name,
        )
    finally:
        postgres_engine.dispose()


@pytest.fixture
def metadata_store(integration_services: IntegrationServices) -> PostgresMetadataStore:
    return PostgresMetadataStore(integration_services.postgres_engine)


@pytest.fixture
def object_store(integration_services: IntegrationServices) -> MinioObjectStore:
    return MinioObjectStore(
        client=integration_services.minio_client,
        bucket_name=integration_services.bucket_name,
    )


def _doc_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def _select_postgres_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DMS_METADATA_BACKEND", "postgresql")
    monkeypatch.delenv("DMS_CONFIGURATION_STRICT", raising=False)
    monkeypatch.delenv("SQLITE_PATH", raising=False)
    monkeypatch.delenv("POSTGRES_DSN", raising=False)


def _cleanup_metadata(metadata_store: PostgresMetadataStore, document_id: str) -> None:
    try:
        metadata_store.hard_delete(document_id)
    except Exception:
        pass


def _cleanup_object(object_store: MinioObjectStore, document_id: str, storage_key: str) -> None:
    try:
        object_store.delete_object(document_id, storage_key)
    except Exception:
        pass


def test_postgres_metadata_store_with_real_postgres(metadata_store: PostgresMetadataStore) -> None:
    document_id = _doc_id("real-pg")
    metadata = metadata_store.build_metadata(
        document_id=document_id,
        filename="real.txt",
        content_type="text/plain",
        file_size=5,
        storage_key=f"documents/{document_id}/real.txt",
        checksum="abc123",
        created_by="integration-test",
        extra_metadata={"origin": "pytest"},
    )

    try:
        metadata_store.save_metadata(metadata)
        loaded = metadata_store.get_metadata(document_id)

        assert loaded.document_id == document_id
        assert loaded.extra_metadata == {"origin": "pytest"}
        assert metadata_store.exists(document_id) is True
    finally:
        _cleanup_metadata(metadata_store, document_id)


def test_minio_object_store_with_real_minio(object_store: MinioObjectStore) -> None:
    document_id = _doc_id("real-minio")
    storage_key = f"documents/{document_id}/blob.txt"

    try:
        stored_key = object_store.put_object(
            PutObjectRequest(
                document_id=document_id,
                storage_key=storage_key,
                content=b"hello integration",
                content_type="text/plain",
                filename="blob.txt",
                checksum="sum-1",
                metadata={"origin": "pytest"},
            )
        )

        stored = object_store.get_object(document_id, stored_key)

        assert stored.content == b"hello integration"
        assert stored.filename == "blob.txt"
        assert stored.size == len(b"hello integration")
        assert object_store.object_exists(document_id, stored_key) is True
    finally:
        _cleanup_object(object_store, document_id, storage_key)


def test_create_sdk_from_environment_with_real_services(
    integration_services: IntegrationServices,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _select_postgres_environment(monkeypatch)
    document_id = _doc_id("real-sdk")
    with create_sdk_from_environment() as sdk:
        uploaded = False
        try:
            result = sdk.upload_document(
                UploadDocumentRequest(
                    document_id=document_id,
                    content=b"sdk integration",
                    filename="sdk.txt",
                    content_type="text/plain",
                    metadata={"kind": "integration"},
                    created_by="pytest",
                )
            )
            uploaded = True

            metadata = sdk.get_document_metadata(document_id)
            content = sdk.get_document_content(document_id)
            health = sdk.check_health()

            assert result.document_id == document_id
            assert metadata.extra_metadata == {"kind": "integration"}
            assert content.content == b"sdk integration"
            assert health.ok is True
        finally:
            if uploaded:
                sdk.hard_delete_document(document_id)


def test_create_sdk_from_service_configs_with_real_services(
    integration_services: IntegrationServices,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configs = load_service_configs(services={"postgres", "minio"})
    document_id = _doc_id("real-config-sdk")

    with create_sdk_from_service_configs(configs, check_on_startup=True) as sdk:
        uploaded = False
        try:
            result = sdk.upload_document(
                UploadDocumentRequest(
                    document_id=document_id,
                    content=b"service configs integration",
                    filename="service-configs.txt",
                    content_type="text/plain",
                    metadata={"factory": "service-configs"},
                    created_by="pytest",
                )
            )
            uploaded = True

            metadata = sdk.get_document_metadata(document_id)
            content = sdk.get_document_content(document_id)
            health = sdk.check_health()

            assert result.document_id == document_id
            assert metadata.extra_metadata == {"factory": "service-configs"}
            assert content.content == b"service configs integration"
            assert health.ok is True
            assert {service.service for service in health.services} == {"postgres", "minio"}
        finally:
            if uploaded:
                sdk.hard_delete_document(document_id)


def test_sdk_soft_delete_with_real_services(
    integration_services: IntegrationServices,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _select_postgres_environment(monkeypatch)
    document_id = _doc_id("real-soft-delete")
    with create_sdk_from_environment() as sdk:
        uploaded = False
        try:
            sdk.upload_document(
                UploadDocumentRequest(
                    document_id=document_id,
                    content=b"soft delete content",
                    filename="soft-delete.txt",
                    content_type="text/plain",
                )
            )
            uploaded = True

            deleted = sdk.soft_delete_document(document_id)
            with pytest.raises(DocumentNotFoundError):
                sdk.get_document_metadata(document_id)
            metadata = sdk.get_internal_document_metadata(document_id)

            assert deleted.document_id == document_id
            assert deleted.hard_deleted is False
            assert deleted.status == DocumentStatus.DELETED
            assert metadata.status == DocumentStatus.DELETED

            with pytest.raises(DocumentDeletedError):
                sdk.get_document_content(document_id)
        finally:
            if uploaded:
                sdk.hard_delete_document(document_id)


def test_sdk_hard_delete_with_real_services(
    integration_services: IntegrationServices,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _select_postgres_environment(monkeypatch)
    document_id = _doc_id("real-hard-delete")
    with create_sdk_from_environment() as sdk:
        result = sdk.upload_document(
            UploadDocumentRequest(
                document_id=document_id,
                content=b"hard delete content",
                filename="hard-delete.txt",
                content_type="text/plain",
            )
        )

        assert result.document_id == document_id
        deleted = sdk.hard_delete_document(document_id)

        assert deleted.document_id == document_id
        assert deleted.hard_deleted is True
        assert deleted.status == DocumentStatus.DELETED

        with pytest.raises(DocumentNotFoundError):
            sdk.get_document_metadata(document_id)
