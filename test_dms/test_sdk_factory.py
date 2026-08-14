from __future__ import annotations

import inspect

import pytest
from sqlalchemy import create_engine
from sqlalchemy import inspect as sqlalchemy_inspect

import dms
from dms import ConfigurationError
from dms.infrastructure.metadata.sqlite import SqliteMetadataStore
from dms.sdk.async_sdk import AsyncDocumentManagementSDK
from dms.sdk.factory import DocumentManagementSDKFactory
from dms.sdk.implementation import DefaultDocumentManagementSDK
from test_dms.sdk_test_support import (
    CursorMemoryStore,
    RecordingOperationStore,
    StreamMemoryObjectStore,
)


class StubMinioClient:
    pass


def test_factory_assembles_sdk_from_sqlalchemy_engine_and_minio_client() -> None:
    engine = create_engine("sqlite:///:memory:")
    minio_client = StubMinioClient()

    factory = DocumentManagementSDKFactory(
        engine=engine,
        minio_client=minio_client,
        bucket_name="documents",
    )
    sdk = factory.create()

    assert type(sdk._metadata_store).__name__ == "SqliteMetadataStore"
    assert type(sdk._operation_store).__name__ == "SqlAlchemyUploadOperationStore"
    assert type(sdk._object_store).__name__ == "MinioObjectStore"
    assert sdk._metadata_store._engine is engine
    assert sdk._object_store._client is minio_client
    assert sdk._object_store._bucket_name == "documents"


@pytest.mark.asyncio
async def test_factory_creates_async_facade_from_injected_clients() -> None:
    engine = create_engine("sqlite:///:memory:")
    factory = DocumentManagementSDKFactory(
        engine=engine,
        minio_client=StubMinioClient(),
        bucket_name="documents",
    )

    sdk = factory.create_async()

    assert isinstance(sdk, AsyncDocumentManagementSDK)
    assert sdk._sdk._metadata_store._engine is engine


def test_sdk_can_be_built_with_sync_and_async_facades() -> None:
    sdk = DefaultDocumentManagementSDK(
        metadata_store=CursorMemoryStore(),
        object_store=StreamMemoryObjectStore(),
    )
    async_sdk = AsyncDocumentManagementSDK(
        DefaultDocumentManagementSDK(
            metadata_store=CursorMemoryStore(),
            object_store=StreamMemoryObjectStore(),
        )
    )

    assert sdk._metadata_store.__class__.__name__ == "CursorMemoryStore"
    assert isinstance(async_sdk, AsyncDocumentManagementSDK)


def test_factory_rejects_blank_bucket_before_adapter_assembly() -> None:
    engine = create_engine("sqlite:///:memory:")

    with pytest.raises(ConfigurationError, match="bucket_name"):
        DocumentManagementSDKFactory(
            engine=engine,
            minio_client=StubMinioClient(),
            bucket_name=" ",
        )


def test_factory_rejects_invalid_assembly_options_before_adapter_assembly() -> None:
    engine = create_engine("sqlite:///:memory:")

    with pytest.raises(ValueError, match="max_file_size"):
        DocumentManagementSDKFactory(
            engine=engine,
            minio_client=StubMinioClient(),
            bucket_name="documents",
            max_file_size=0,
        )

    assert sqlalchemy_inspect(engine).get_table_names() == []


def test_factory_rejects_unsupported_sqlalchemy_dialect() -> None:
    class UnsupportedEngine:
        class dialect:
            name = "mysql"

    factory = DocumentManagementSDKFactory(
        engine=UnsupportedEngine(),  # type: ignore[arg-type]
        minio_client=StubMinioClient(),
        bucket_name="documents",
    )

    with pytest.raises(ConfigurationError, match="Unsupported SQLAlchemy dialect"):
        factory.create()


def test_sdk_accepts_injected_storage_ports() -> None:
    sdk = DefaultDocumentManagementSDK(
        metadata_store=CursorMemoryStore(),
        object_store=StreamMemoryObjectStore(),
    )

    assert sdk._metadata_store.__class__.__name__ == "CursorMemoryStore"


def test_sdk_accepts_assembly_policies_without_a_plan_object() -> None:
    policy = object()
    observer = object()
    sdk = DefaultDocumentManagementSDK(
        metadata_store=CursorMemoryStore(),
        object_store=StreamMemoryObjectStore(),
        access_policy=policy,  # type: ignore[arg-type]
        operation_observer=observer,  # type: ignore[arg-type]
    )

    assert sdk._access_policy is policy
    assert sdk._operation_observer is observer


def test_sdk_preserves_falsey_injected_operation_store() -> None:
    class FalseyOperationStore(RecordingOperationStore):
        def __bool__(self) -> bool:
            return False

    operation_store = FalseyOperationStore()
    sdk = DefaultDocumentManagementSDK(
        metadata_store=CursorMemoryStore(),
        object_store=StreamMemoryObjectStore(),
        operation_store=operation_store,  # type: ignore[arg-type]
    )

    assert sdk._operation_store is operation_store


def test_document_ids_are_allocated_by_the_metadata_store() -> None:
    class AutoIncrementMetadataStore(CursorMemoryStore):
        def __init__(self) -> None:
            super().__init__()
            self._next_id = 0

        def allocate_document_id(self) -> str:
            self._next_id += 1
            return str(self._next_id)

    sdk = DefaultDocumentManagementSDK(
        metadata_store=AutoIncrementMetadataStore(),
        object_store=StreamMemoryObjectStore(),
    )

    first = sdk.upload_document(
        dms.UploadDocumentRequest(
            content=b"first",
            filename="first.txt",
            content_type="text/plain",
        )
    )
    second = sdk.upload_document(
        dms.UploadDocumentRequest(
            content=b"second",
            filename="second.txt",
            content_type="text/plain",
        )
    )

    assert first.document_id == "1"
    assert second.document_id == "2"


def test_sqlite_metadata_store_allocates_ids_with_database_auto_increment() -> None:
    engine = create_engine("sqlite:///:memory:")
    store = SqliteMetadataStore(engine)

    assert store.allocate_document_id() == "1"
    assert store.allocate_document_id() == "2"


def test_id_generator_is_removed_from_sdk_assembly_signatures() -> None:
    assert "id_generator" not in inspect.signature(DefaultDocumentManagementSDK).parameters
    assert "id_generator" not in inspect.signature(DocumentManagementSDKFactory).parameters


def test_operation_store_is_removed_from_factory_signature() -> None:
    assert "operation_store" not in inspect.signature(DocumentManagementSDKFactory).parameters
