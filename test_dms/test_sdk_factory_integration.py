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
            )
        )
        metadata = sdk.get_document_metadata(document_id)
        downloaded = sdk.get_document_content(document_id)
        internal = sdk.get_internal_document_metadata(document_id)
        object_stat = minio_client.stat_object(bucket_name, internal.storage_key)

        assert uploaded.document_id == document_id
        assert metadata.original_filename == filename
        assert downloaded.filename == filename
        assert downloaded.content == content
        assert internal.storage_key == f"documents/{document_id}/{filename}"
        assert not any("filename" in key.lower() for key in object_stat.metadata)
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


def test_factory_isolates_multiple_users_across_postgres_and_minio(
    integration_factory: tuple[DocumentManagementSDKFactory, Minio, Engine, str],
) -> None:
    factory, _, _, _ = integration_factory
    sdk = factory.create()
    suffix = uuid4().hex
    alice_user = f"alice-{suffix}"
    bob_user = f"bob-{suffix}"
    shared_scope = f"shared-scope-{suffix}"
    alice_context = dms.AccessContext(user_id=alice_user)
    bob_context = dms.AccessContext(user_id=bob_user)

    try:
        alice_first = sdk.upload_document(
            _upload_request(f"{suffix}-alice-1", b"alice document one"),
            access_context=alice_context,
        )
        alice_second = sdk.upload_document(
            _upload_request(f"{suffix}-alice-2", b"alice document two"),
            access_context=alice_context,
        )
        bob_first = sdk.upload_document(
            _upload_request(f"{suffix}-bob-1", b"bob document one"),
            access_context=bob_context,
        )
        bob_second = sdk.upload_document(
            _upload_request(f"{suffix}-bob-2", b"bob document two"),
            access_context=bob_context,
        )

        alice_idempotent = sdk.upload_document(
            _upload_request(
                None,
                b"alice idempotent document",
                idempotency_key="shared-key",
                idempotency_scope=shared_scope,
            ),
            access_context=alice_context,
        )
        alice_replay = sdk.upload_document(
            _upload_request(
                None,
                b"alice idempotent document",
                idempotency_key="shared-key",
                idempotency_scope=shared_scope,
            ),
            access_context=alice_context,
        )
        bob_idempotent = sdk.upload_document(
            _upload_request(
                None,
                b"bob idempotent document",
                idempotency_key="shared-key",
                idempotency_scope=shared_scope,
            ),
            access_context=bob_context,
        )

        assert alice_replay.created is False
        assert alice_replay.document_id == alice_idempotent.document_id
        assert bob_idempotent.document_id != alice_idempotent.document_id
        assert alice_first.metadata.user_id == alice_user
        assert bob_first.metadata.user_id == bob_user

        alice_document_ids = {
            alice_first.document_id,
            alice_second.document_id,
            alice_idempotent.document_id,
        }
        bob_document_ids = {
            bob_first.document_id,
            bob_second.document_id,
            bob_idempotent.document_id,
        }
        alice_page = sdk.list_documents(limit=2, access_context=alice_context)
        alice_next_page = sdk.list_documents(
            cursor=alice_page.next_cursor,
            limit=2,
            access_context=alice_context,
        )
        bob_page = sdk.list_documents(limit=10, access_context=bob_context)

        assert alice_page.has_more is True
        assert alice_page.next_cursor is not None
        assert alice_next_page.has_more is False
        assert {
            item.document_id
            for item in alice_page.items + alice_next_page.items
        } == alice_document_ids
        assert all(item.user_id == alice_user for item in alice_page.items)
        assert all(item.user_id == alice_user for item in alice_next_page.items)
        assert {item.document_id for item in bob_page.items} == bob_document_ids
        assert all(item.user_id == bob_user for item in bob_page.items)

        with pytest.raises(dms.ValidationError):
            sdk.list_documents(
                cursor=alice_page.next_cursor,
                limit=2,
                access_context=bob_context,
            )
        with pytest.raises(dms.AccessDeniedError):
            sdk.get_document_metadata(
                alice_first.document_id,
                access_context=bob_context,
            )
        with pytest.raises(dms.AccessDeniedError):
            sdk.get_document_content(
                alice_first.document_id,
                access_context=bob_context,
            )
        with pytest.raises(dms.AccessDeniedError):
            sdk.delete_document(
                alice_first.document_id,
                access_context=bob_context,
            )

        alice_operation = sdk.get_upload_operation(
            scope=shared_scope,
            idempotency_key="shared-key",
            access_context=alice_context,
        )
        bob_operation = sdk.get_upload_operation(
            scope=shared_scope,
            idempotency_key="shared-key",
            access_context=bob_context,
        )
        assert alice_operation.document_id == alice_idempotent.document_id
        assert bob_operation.document_id == bob_idempotent.document_id

        reset = sdk.clear_all_data(access_context=alice_context)

        assert reset.metadata_deleted == 3
        assert reset.objects_deleted == 3
        assert reset.upload_operations_deleted == 1
        assert sdk.list_documents(access_context=alice_context).items == []
        assert {
            item.document_id
            for item in sdk.list_documents(limit=10, access_context=bob_context).items
        } == bob_document_ids
        assert sdk.get_document_content(
            bob_first.document_id,
            access_context=bob_context,
        ).content == b"bob document one"
        assert sdk.get_upload_operation(
            scope=shared_scope,
            idempotency_key="shared-key",
            access_context=bob_context,
        ).document_id == bob_idempotent.document_id
        with pytest.raises(dms.UploadOperationNotFoundError):
            sdk.get_upload_operation(
                scope=shared_scope,
                idempotency_key="shared-key",
                access_context=alice_context,
            )
    finally:
        for access_context in (alice_context, bob_context):
            with suppress(Exception):
                sdk.clear_all_data(access_context=access_context)


@pytest.mark.asyncio
async def test_async_factory_isolates_multiple_users_across_postgres_and_minio(
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
    alice_context = dms.AccessContext(user_id=f"alice-{suffix}")
    bob_context = dms.AccessContext(user_id=f"bob-{suffix}")

    try:
        alice_result = await sdk.upload_document(
            _upload_request(f"{suffix}-async-alice", b"async alice document"),
            access_context=alice_context,
        )
        bob_result = await sdk.upload_document(
            _upload_request(f"{suffix}-async-bob", b"async bob document"),
            access_context=bob_context,
        )

        assert [
            item.document_id
            async for item in sdk.iter_documents(access_context=alice_context)
        ] == [alice_result.document_id]
        assert [
            item.document_id
            async for item in sdk.iter_documents(access_context=bob_context)
        ] == [bob_result.document_id]
        assert (
            await sdk.get_document_metadata(
                alice_result.document_id,
                access_context=alice_context,
            )
        ).user_id == alice_context.user_id

        with pytest.raises(dms.AccessDeniedError):
            await sdk.get_document_content(
                alice_result.document_id,
                access_context=bob_context,
            )

        stream = await sdk.get_document_content_async_stream(
            alice_result.document_id,
            chunk_size=5,
            access_context=alice_context,
        )
        try:
            chunks = [chunk async for chunk in stream.aiter_chunks_closing()]
        finally:
            await stream.aclose()
        assert b"".join(chunks) == b"async alice document"

        reset = await sdk.clear_all_data(access_context=alice_context)

        assert reset.metadata_deleted == 1
        assert reset.objects_deleted == 1
        assert reset.upload_operations_deleted == 0
        assert [
            item.document_id
            async for item in sdk.iter_documents(access_context=alice_context)
        ] == []
        assert [
            item.document_id
            async for item in sdk.iter_documents(access_context=bob_context)
        ] == [bob_result.document_id]
        assert (
            await sdk.get_document_content(
                bob_result.document_id,
                access_context=bob_context,
            )
        ).content == b"async bob document"
    finally:
        for access_context in (alice_context, bob_context):
            with suppress(Exception):
                await sdk.clear_all_data(access_context=access_context)
