from __future__ import annotations

from collections.abc import Iterator
from contextlib import suppress
from re import sub
from uuid import uuid4

import pytest
from minio import Minio
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

import dms
from dms.sdk.factory import DocumentManagementSDKFactory

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
async def test_factory_async_facade_round_trips_document_through_real_clients(
    integration_factory: tuple[DocumentManagementSDKFactory, Minio, Engine, str],
) -> None:
    factory, _, _, _ = integration_factory
    sdk = factory.create_async()
    document_id = f"factory-async-{uuid4().hex}"
    content = b"async factory integration payload"

    try:
        uploaded = await sdk.upload_document(
            dms.UploadDocumentRequest(
                document_id=document_id,
                content=content,
                filename="factory-async.txt",
                content_type="text/plain",
            )
        )
        metadata = await sdk.get_document_metadata(document_id)
        downloaded = await sdk.get_document_content(document_id)

        assert uploaded.document_id == document_id
        assert metadata.document_id == document_id
        assert downloaded.content == content
    finally:
        with suppress(dms.DocumentNotFoundError):
            await sdk.hard_delete_document(document_id)
