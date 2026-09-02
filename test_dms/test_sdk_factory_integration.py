from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from contextlib import suppress
from re import sub
from uuid import uuid4

import pytest
import pytest_asyncio
from minio import Minio
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

import dms
from dms.sdk.contracts import partition_storage_prefix
from dms.sdk.factory import (
    AsyncDocumentManagementSDKFactory,
    DocumentManagementSDKFactory,
)
from test_dms.sdk_test_support import DEFAULT_PARTITION

pytestmark = [
    pytest.mark.integration,
]


def _integration_bucket_name() -> str:
    configured_bucket = sub(
        r"[^a-z0-9-]",
        "-",
        "documents".strip().lower(),
    ).strip("-")
    return f"{configured_bucket[:20] or 'dms'}-it-{uuid4().hex}"


def _async_postgres_dsn() -> str:
    return "postgresql+asyncpg://docmesh:postgres@postgres:5432/dms"


def _sync_postgres_dsn() -> str:
    return "postgresql+psycopg://docmesh:postgres@postgres:5432/dms"


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _upload_request(
    document_id: str | None,
    content: bytes,
    *,
    idempotency_key: str | None = None,
    idempotency_scope: str | None = None,
) -> dms.UploadDocumentRequest:
    return dms.UploadDocumentRequest(
        document_id=document_id,
        content=content,
        filename=f"{document_id or 'generated'}.txt",
        content_type="text/plain",
        idempotency_key=idempotency_key,
        idempotency_scope=idempotency_scope,
    )


async def _clear_bucket_async(client: Minio, bucket_name: str) -> None:
    if not await asyncio.to_thread(client.bucket_exists, bucket_name):
        return
    items = await asyncio.to_thread(
        lambda: list(client.list_objects(bucket_name, recursive=True))
    )
    for item in items:
        if item.object_name is not None:
            await asyncio.to_thread(client.remove_object, bucket_name, item.object_name)
    await asyncio.to_thread(client.remove_bucket, bucket_name)


@pytest.fixture()
def integration_factory() -> Iterator[
    tuple[DocumentManagementSDKFactory, Minio, Engine, str]
]:
    schema_name = f"dms_it_{uuid4().hex}"
    admin_engine = create_engine(_sync_postgres_dsn(), pool_pre_ping=True)
    minio_client = Minio(
        endpoint="minio:9000",
        access_key="minioadmin",
        secret_key="minioadmin123",
        secure=False,
    )
    bucket_name = _integration_bucket_name()

    try:
        with admin_engine.connect():
            pass
        minio_client.bucket_exists(bucket_name)
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))
    except Exception as exc:  # noqa: BLE001 - skip when external services are unavailable
        admin_engine.dispose()
        pytest.skip(
            "PostgreSQL and MinIO integration services are unavailable: "
            f"{type(exc).__name__}"
        )

    engine = create_engine(
        _sync_postgres_dsn(),
        connect_args={"options": f"-csearch_path={schema_name}"},
        pool_pre_ping=True,
    )
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
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema_name}" CASCADE'))
        admin_engine.dispose()


@pytest_asyncio.fixture()
async def async_integration_factory() -> AsyncIterator[
    tuple[AsyncDocumentManagementSDKFactory, Minio, AsyncEngine, str]
]:
    schema_name = f"dms_it_{uuid4().hex}"
    admin_engine = create_async_engine(_async_postgres_dsn(), pool_pre_ping=True)
    minio_client = Minio(
        endpoint="minio:9000",
        access_key="minioadmin",
        secret_key="minioadmin123",
        secure=False,
    )
    bucket_name = _integration_bucket_name()

    try:
        async with admin_engine.connect():
            pass
        await asyncio.to_thread(minio_client.bucket_exists, bucket_name)
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))
    except Exception as exc:  # noqa: BLE001 - skip when external services are unavailable
        await admin_engine.dispose()
        pytest.skip(
            "PostgreSQL and MinIO integration services are unavailable: "
            f"{type(exc).__name__}"
        )

    engine = create_async_engine(
        _async_postgres_dsn(),
        connect_args={"server_settings": {"search_path": schema_name}},
        pool_pre_ping=True,
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
        await _clear_bucket_async(minio_client, bucket_name)
        await engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema_name}" CASCADE'))
        await admin_engine.dispose()


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
            ),
            partition=DEFAULT_PARTITION,
        )

        metadata = sdk.get_document_metadata(document_id, partition=DEFAULT_PARTITION)
        downloaded = sdk.get_document_content(document_id, partition=DEFAULT_PARTITION)
        listed_ids = {
            item.document_id
            for item in sdk.list_documents(limit=100, partition=DEFAULT_PARTITION).items
        }

        assert uploaded.document_id == document_id
        assert metadata.document_id == document_id
        assert metadata.original_filename == "factory.txt"
        assert metadata.extra_metadata == {"test": "factory-integration"}
        assert downloaded.content == content
        assert document_id in listed_ids
    finally:
        with suppress(dms.DocumentNotFoundError):
            sdk.hard_delete_document(document_id, partition=DEFAULT_PARTITION)


def test_factory_round_trips_korean_document_title_through_postgres_and_minio(
    integration_factory: tuple[DocumentManagementSDKFactory, Minio, Engine, str],
) -> None:
    factory, minio_client, _, bucket_name = integration_factory
    sdk = factory.create()
    document_id = f"factory-korean-{uuid4().hex}"
    filename = "2026년 사업계획서 최종본.pdf"
    content = "한글 문서 본문입니다.".encode()

    try:
        uploaded = sdk.upload_document(
            dms.UploadDocumentRequest(
                document_id=document_id,
                content=content,
                filename=filename,
                content_type="application/pdf",
            ),
            partition=DEFAULT_PARTITION,
        )
        metadata = sdk.get_document_metadata(document_id, partition=DEFAULT_PARTITION)
        downloaded = sdk.get_document_content(document_id, partition=DEFAULT_PARTITION)
        internal = sdk.get_internal_document_metadata(
            document_id, partition=DEFAULT_PARTITION
        )
        object_stat = minio_client.stat_object(bucket_name, internal.storage_key)

        assert uploaded.document_id == document_id
        assert metadata.original_filename == filename
        assert downloaded.filename == filename
        assert downloaded.content == content
        assert internal.storage_key == (
            f"{partition_storage_prefix(DEFAULT_PARTITION)}{document_id}/{filename}"
        )
        assert not any("filename" in key.lower() for key in object_stat.metadata)
    finally:
        with suppress(dms.DocumentNotFoundError):
            sdk.hard_delete_document(document_id, partition=DEFAULT_PARTITION)


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
            ),
            partition=DEFAULT_PARTITION,
        )
        metadata = sdk.get_document_metadata(document_id, partition=DEFAULT_PARTITION)
        downloaded = sdk.get_document_content(document_id, partition=DEFAULT_PARTITION)

        assert type(sdk._metadata_store).__name__ == "SqliteMetadataStore"
        assert uploaded.document_id == document_id
        assert metadata.document_id == document_id
        assert downloaded.content == content
    finally:
        with suppress(dms.DocumentNotFoundError):
            sdk.hard_delete_document(document_id, partition=DEFAULT_PARTITION)


@pytest.mark.asyncio
async def test_async_factory_round_trips_document_through_postgres_and_minio(
    async_integration_factory: tuple[
        AsyncDocumentManagementSDKFactory,
        Minio,
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
            ),
            partition=DEFAULT_PARTITION,
        )
        metadata = await sdk.get_document_metadata(
            document_id, partition=DEFAULT_PARTITION
        )
        downloaded = await sdk.get_document_content(
            document_id, partition=DEFAULT_PARTITION
        )
        page = await sdk.list_documents(limit=100, partition=DEFAULT_PARTITION)
        stream = await sdk.get_document_content_stream(
            document_id, chunk_size=5, partition=DEFAULT_PARTITION
        )
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
            await sdk.hard_delete_document(document_id, partition=DEFAULT_PARTITION)


def test_factory_isolates_personal_and_group_partitions_across_postgres_and_minio(
    integration_factory: tuple[DocumentManagementSDKFactory, Minio, Engine, str],
) -> None:
    factory, _, _, _ = integration_factory
    sdk = factory.create()
    suffix = uuid4().hex
    personal_id = f"personal-{suffix}"
    group_id = f"group-{suffix}"
    shared_scope = f"shared-scope-{suffix}"
    personal_partition = dms.DocumentPartition.personal(personal_id)
    group_partition = dms.DocumentPartition.group(group_id)

    try:
        personal_first = sdk.upload_document(
            _upload_request(f"{suffix}-personal-1", b"personal document one"),
            partition=personal_partition,
        )
        personal_second = sdk.upload_document(
            _upload_request(f"{suffix}-personal-2", b"personal document two"),
            partition=personal_partition,
        )
        group_first = sdk.upload_document(
            _upload_request(f"{suffix}-group-1", b"group document one"),
            partition=group_partition,
        )
        group_second = sdk.upload_document(
            _upload_request(f"{suffix}-group-2", b"group document two"),
            partition=group_partition,
        )

        personal_idempotent = sdk.upload_document(
            _upload_request(
                None,
                b"personal idempotent document",
                idempotency_key="shared-key",
                idempotency_scope=shared_scope,
            ),
            partition=personal_partition,
        )
        personal_replay = sdk.upload_document(
            _upload_request(
                None,
                b"personal idempotent document",
                idempotency_key="shared-key",
                idempotency_scope=shared_scope,
            ),
            partition=personal_partition,
        )
        group_idempotent = sdk.upload_document(
            _upload_request(
                None,
                b"group idempotent document",
                idempotency_key="shared-key",
                idempotency_scope=shared_scope,
            ),
            partition=group_partition,
        )

        assert personal_replay.created is False
        assert personal_replay.document_id == personal_idempotent.document_id
        assert group_idempotent.document_id != personal_idempotent.document_id
        assert personal_first.metadata.partition == personal_partition
        assert group_first.metadata.partition == group_partition

        personal_document_ids = {
            personal_first.document_id,
            personal_second.document_id,
            personal_idempotent.document_id,
        }
        group_document_ids = {
            group_first.document_id,
            group_second.document_id,
            group_idempotent.document_id,
        }
        personal_page = sdk.list_documents(limit=2, partition=personal_partition)
        personal_next_page = sdk.list_documents(
            cursor=personal_page.next_cursor,
            limit=2,
            partition=personal_partition,
        )
        group_page = sdk.list_documents(limit=10, partition=group_partition)

        assert personal_page.has_more is True
        assert personal_page.next_cursor is not None
        assert personal_next_page.has_more is False
        assert {
            item.document_id for item in personal_page.items + personal_next_page.items
        } == personal_document_ids
        assert all(item.partition == personal_partition for item in personal_page.items)
        assert all(
            item.partition == personal_partition for item in personal_next_page.items
        )
        assert {item.document_id for item in group_page.items} == group_document_ids
        assert all(item.partition == group_partition for item in group_page.items)

        with pytest.raises(dms.ValidationError):
            sdk.list_documents(
                cursor=personal_page.next_cursor,
                limit=2,
                partition=group_partition,
            )
        with pytest.raises(dms.DocumentNotFoundError):
            sdk.get_document_metadata(
                personal_first.document_id,
                partition=group_partition,
            )
        with pytest.raises(dms.DocumentNotFoundError):
            sdk.get_document_content(
                personal_first.document_id,
                partition=group_partition,
            )
        with pytest.raises(dms.DocumentNotFoundError):
            sdk.delete_document(
                personal_first.document_id,
                partition=group_partition,
            )

        personal_operation = sdk.get_upload_operation(
            scope=shared_scope,
            idempotency_key="shared-key",
            partition=personal_partition,
        )
        group_operation = sdk.get_upload_operation(
            scope=shared_scope,
            idempotency_key="shared-key",
            partition=group_partition,
        )
        assert personal_operation.document_id == personal_idempotent.document_id
        assert group_operation.document_id == group_idempotent.document_id

        reset = sdk.clear_partition_data(partition=personal_partition)

        assert reset.metadata_deleted == 3
        assert reset.objects_deleted == 3
        assert reset.upload_operations_deleted == 1
        assert sdk.list_documents(partition=personal_partition).items == []
        assert {
            item.document_id
            for item in sdk.list_documents(limit=10, partition=group_partition).items
        } == group_document_ids
        assert (
            sdk.get_document_content(
                group_first.document_id,
                partition=group_partition,
            ).content
            == b"group document one"
        )
        assert (
            sdk.get_upload_operation(
                scope=shared_scope,
                idempotency_key="shared-key",
                partition=group_partition,
            ).document_id
            == group_idempotent.document_id
        )
        with pytest.raises(dms.UploadOperationNotFoundError):
            sdk.get_upload_operation(
                scope=shared_scope,
                idempotency_key="shared-key",
                partition=personal_partition,
            )
    finally:
        for partition in (personal_partition, group_partition):
            with suppress(Exception):
                sdk.clear_partition_data(partition=partition)


@pytest.mark.asyncio
async def test_async_factory_isolates_personal_and_group_partitions_across_postgres_and_minio(
    async_integration_factory: tuple[
        AsyncDocumentManagementSDKFactory,
        Minio,
        AsyncEngine,
        str,
    ],
) -> None:
    factory, _, _, _ = async_integration_factory
    sdk = await factory.create_async()
    suffix = uuid4().hex
    personal_partition = dms.DocumentPartition.personal(f"person-{suffix}")
    group_partition = dms.DocumentPartition.group(f"group-{suffix}")

    try:
        personal_result = await sdk.upload_document(
            _upload_request(f"{suffix}-async-personal", b"async personal document"),
            partition=personal_partition,
        )
        group_result = await sdk.upload_document(
            _upload_request(f"{suffix}-async-group", b"async group document"),
            partition=group_partition,
        )

        assert [
            item.document_id
            async for item in sdk.iter_documents(partition=personal_partition)
        ] == [personal_result.document_id]
        assert [
            item.document_id
            async for item in sdk.iter_documents(partition=group_partition)
        ] == [group_result.document_id]
        assert (
            await sdk.get_document_metadata(
                personal_result.document_id,
                partition=personal_partition,
            )
        ).partition == personal_partition

        with pytest.raises(dms.DocumentNotFoundError):
            await sdk.get_document_content(
                personal_result.document_id,
                partition=group_partition,
            )

        stream = await sdk.get_document_content_async_stream(
            personal_result.document_id,
            chunk_size=5,
            partition=personal_partition,
        )
        try:
            chunks = [chunk async for chunk in stream.aiter_chunks_closing()]
        finally:
            await stream.aclose()
        assert b"".join(chunks) == b"async personal document"

        reset = await sdk.clear_partition_data(partition=personal_partition)

        assert reset.metadata_deleted == 1
        assert reset.objects_deleted == 1
        assert reset.upload_operations_deleted == 0
        assert [
            item.document_id
            async for item in sdk.iter_documents(partition=personal_partition)
        ] == []
        assert [
            item.document_id
            async for item in sdk.iter_documents(partition=group_partition)
        ] == [group_result.document_id]
        assert (
            await sdk.get_document_content(
                group_result.document_id,
                partition=group_partition,
            )
        ).content == b"async group document"
    finally:
        for partition in (personal_partition, group_partition):
            with suppress(Exception):
                await sdk.clear_partition_data(partition=partition)
