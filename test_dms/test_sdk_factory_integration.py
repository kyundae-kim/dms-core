from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from contextlib import suppress
from re import sub
from uuid import uuid4

import pytest
import pytest_asyncio
from minio import Minio
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

import dms
from dms.sdk.factory import (
    AsyncDocumentManagementSDKFactory,
    DocumentManagementSDKFactory,
)

pytestmark = [
    pytest.mark.integration,
]

def _integration_bucket_name() -> str:
    configured_bucket = sub(
        r"[^a-z0-9-]",
        "-",
        'documents'.strip().lower(),
    ).strip("-")
    return f"{configured_bucket[:20] or 'dms'}-it-{uuid4().hex}"


def _async_postgres_dsn() -> str:
    return "postgresql+asyncpg://docmesh:postgres@postgres:5432/dms"


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@pytest.fixture()
def integration_factory() -> Iterator[
    tuple[DocumentManagementSDKFactory, Minio, Engine, str]
]:
    engine = create_engine('postgresql+psycopg://docmesh:postgres@postgres:5432/dms', pool_pre_ping=True)
    minio_client = Minio(
        endpoint='minio:9000',
        access_key='minioadmin',
        secret_key='minioadmin123',
        secure=False,
    )
    bucket_name = _integration_bucket_name()

    try:
        yield (
            DocumentManagementSDKFactory(
                engine=engine,
                minio_client=minio_client,
                bucket_name=bucket_name,
            ),
            minio_client,
            engine,
            bucket_name,
        )
    finally:
        if minio_client.bucket_exists(bucket_name):
            for item in minio_client.list_objects(bucket_name, recursive=True):
                if item.object_name is not None:
                    minio_client.remove_object(bucket_name, item.object_name)
            minio_client.remove_bucket(bucket_name)
        engine.dispose()


@pytest_asyncio.fixture()
async def async_integration_factory() -> AsyncIterator[
    tuple[AsyncDocumentManagementSDKFactory, Minio, AsyncEngine, str]
]:
    engine = create_async_engine(_async_postgres_dsn(), pool_pre_ping=True)
    minio_client = Minio(
        endpoint="minio:9000",
        access_key="minioadmin",
        secret_key="minioadmin123",
        secure=False,
    )
    bucket_name = _integration_bucket_name()

    try:
        async with engine.connect():
            pass
    except Exception as exc:  # noqa: BLE001 - skip when external services are unavailable
        await engine.dispose()
        pytest.skip(
            "PostgreSQL and MinIO integration services are unavailable: "
            f"{type(exc).__name__}"
        )

    try:
        yield (
            AsyncDocumentManagementSDKFactory(
                engine=engine,
                minio_client=minio_client,
                bucket_name=bucket_name,
            ),
            minio_client,
            engine,
            bucket_name,
        )
    finally:
        if minio_client.bucket_exists(bucket_name):
            for item in minio_client.list_objects(bucket_name, recursive=True):
                if item.object_name is not None:
                    minio_client.remove_object(bucket_name, item.object_name)
            minio_client.remove_bucket(bucket_name)
        await engine.dispose()


@pytest.fixture()
def sqlite_factory() -> Iterator[
    tuple[DocumentManagementSDKFactory, Minio, Engine, str]
]:
    engine = create_engine("sqlite:///:memory:")
    minio_client = Minio(
        endpoint="minio:9000",
        access_key="minioadmin",
        secret_key="minioadmin123",
        secure=False,
    )
    bucket_name = _integration_bucket_name()

    try:
        yield (
            DocumentManagementSDKFactory(
                engine=engine,
                minio_client=minio_client,
                bucket_name=bucket_name,
            ),
            minio_client,
            engine,
            bucket_name,
        )
    finally:
        if minio_client.bucket_exists(bucket_name):
            for item in minio_client.list_objects(bucket_name, recursive=True):
                if item.object_name is not None:
                    minio_client.remove_object(bucket_name, item.object_name)
            minio_client.remove_bucket(bucket_name)
        engine.dispose()


def test_factory_round_trips_document_through_postgres_and_minio(
    integration_factory: tuple[DocumentManagementSDKFactory, Minio, Engine, str],
) -> None:
    factory, _, _, _ = integration_factory
    sdk = factory.create()
    document_id = f"factory-sync-{uuid4().hex}"
    content = b"factory integration payload"

    try:
        uploaded = sdk.upload_document(
            dms.UploadDocumentRequest(
                document_id=document_id,
                content=content,
                filename="factory.txt",
                content_type="text/plain",
                metadata={"test": "factory-integration"},
            )
        )

        metadata = sdk.get_document_metadata(document_id)
        downloaded = sdk.get_document_content(document_id)
        listed_ids = {item.document_id for item in sdk.list_documents(limit=100).items}

        assert uploaded.document_id == document_id
        assert metadata.document_id == document_id
        assert metadata.original_filename == "factory.txt"
        assert metadata.extra_metadata == {"test": "factory-integration"}
        assert downloaded.content == content
        assert document_id in listed_ids
    finally:
        with suppress(dms.DocumentNotFoundError):
            sdk.hard_delete_document(document_id)


def test_sqlite_factory_round_trips_document_through_sqlite_and_minio(
    sqlite_factory: tuple[DocumentManagementSDKFactory, Minio, Engine, str],
) -> None:
    factory, _, _, _ = sqlite_factory
    sdk = factory.create()
    document_id = f"factory-sqlite-{uuid4().hex}"
    content = b"sqlite factory integration payload"

    try:
        uploaded = sdk.upload_document(
            dms.UploadDocumentRequest(
                document_id=document_id,
                content=content,
                filename="factory-sqlite.txt",
                content_type="text/plain",
            )
        )
        metadata = sdk.get_document_metadata(document_id)
        downloaded = sdk.get_document_content(document_id)

        assert type(sdk._metadata_store).__name__ == "SqliteMetadataStore"
        assert uploaded.document_id == document_id
        assert metadata.document_id == document_id
        assert downloaded.content == content
    finally:
        with suppress(dms.DocumentNotFoundError):
            sdk.hard_delete_document(document_id)


@pytest.mark.asyncio
async def test_async_factory_round_trips_document_through_postgres_and_minio(
    async_integration_factory: tuple[
        AsyncDocumentManagementSDKFactory,
        AsyncEngine,
        str,
    ],
) -> None:
    factory, _, _, _ = async_integration_factory
    sdk = await factory.create_async()
    document_id = f"factory-async-{uuid4().hex}"
    content = b"async factory integration payload"

    try:
        uploaded = await sdk.upload_document(
            dms.UploadDocumentRequest(
                document_id=document_id,
                content=content,
                filename="factory-async.txt",
                content_type="text/plain",
                metadata={"test": "async-factory-integration"},
            )
        )
        metadata = await sdk.get_document_metadata(document_id)
        downloaded = await sdk.get_document_content(document_id)
        page = await sdk.list_documents(limit=100)
        stream = await sdk.get_document_content_stream(document_id, chunk_size=5)
        chunks = [chunk async for chunk in stream.aiter_chunks_closing()]

        assert sdk._sdk is None
        assert uploaded.document_id == document_id
        assert metadata.document_id == document_id
        assert metadata.extra_metadata == {"test": "async-factory-integration"}
        assert downloaded.content == content
        assert b"".join(chunks) == content
        assert document_id in {item.document_id for item in page.items}
    finally:
        with suppress(dms.DocumentNotFoundError):
            await sdk.hard_delete_document(document_id)
