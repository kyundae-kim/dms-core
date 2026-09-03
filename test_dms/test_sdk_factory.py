from __future__ import annotations

import inspect

import pytest
from sqlalchemy import create_engine
from sqlalchemy import inspect as sqlalchemy_inspect

import dms
from dms import ConfigurationError
from dms.infrastructure.metadata.sqlite import SqliteMetadataStore
from dms.sdk.async_sdk import AsyncDocumentManagementSDK
from dms.sdk.factory import (
    AsyncDocumentManagementSDKFactory,
    DocumentManagementSDKFactory,
)
from dms.sdk.implementation import DefaultDocumentManagementSDK
from test_dms.sdk_test_support import (
    DEFAULT_PARTITION,
    CursorMemoryStore,
    RecordingOperationStore,
    StreamMemoryObjectStore,
)


class StubMinioClient:
    def __init__(self, *, existing_buckets: set[str] | None = None) -> None:
        self.existing_buckets = set(existing_buckets or ())
        self.bucket_exists_calls: list[str] = []
        self.make_bucket_calls: list[str] = []

    def bucket_exists(self, bucket_name: str) -> bool:
        self.bucket_exists_calls.append(bucket_name)
        return bucket_name in self.existing_buckets

    def make_bucket(self, bucket_name: str) -> None:
        self.make_bucket_calls.append(bucket_name)
        self.existing_buckets.add(bucket_name)


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
    assert minio_client.bucket_exists_calls == ["documents"]
    assert minio_client.make_bucket_calls == ["documents"]


def test_factory_reuses_existing_minio_bucket() -> None:
    engine = create_engine("sqlite:///:memory:")
    minio_client = StubMinioClient(existing_buckets={"documents"})

    DocumentManagementSDKFactory(
        engine=engine,
        minio_client=minio_client,
        bucket_name="documents",
    ).create()

    assert minio_client.bucket_exists_calls == ["documents"]
    assert minio_client.make_bucket_calls == []


def test_sync_factory_does_not_expose_async_creation() -> None:
    assert not hasattr(DocumentManagementSDKFactory, "create_async")


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


def test_sdk_accepts_observer_and_access_policy_surface() -> None:
    observer = object()

    class AllowPolicy:
        def allows(self, *, operation, context, metadata) -> bool:
            del operation, context, metadata
            return True

    policy = AllowPolicy()
    sdk = DefaultDocumentManagementSDK(
        metadata_store=CursorMemoryStore(),
        object_store=StreamMemoryObjectStore(),
        operation_observer=observer,  # type: ignore[arg-type]
        access_policy=policy,
    )

    assert sdk._operation_observer is observer
    assert sdk._access_policy is policy
    assert "access_policy" in inspect.signature(DefaultDocumentManagementSDK).parameters


def test_factories_forward_host_access_policy() -> None:
    class AllowPolicy:
        def allows(self, *, operation, context, metadata) -> bool:
            del operation, context, metadata
            return True

    policy = AllowPolicy()
    sdk = DocumentManagementSDKFactory(
        engine=create_engine("sqlite:///:memory:"),
        minio_client=StubMinioClient(),
        bucket_name="documents",
        access_policy=policy,
    ).create()

    assert sdk._access_policy is policy
    assert "access_policy" in inspect.signature(AsyncDocumentManagementSDKFactory).parameters


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
        ),
        partition=DEFAULT_PARTITION,
    )
    second = sdk.upload_document(
        dms.UploadDocumentRequest(
            content=b"second",
            filename="second.txt",
            content_type="text/plain",
        ),
        partition=DEFAULT_PARTITION,
    )

    assert first.document_id == "1"
    assert second.document_id == "2"


def test_sqlite_metadata_store_allocates_ids_with_database_auto_increment() -> None:
    engine = create_engine("sqlite:///:memory:")
    store = SqliteMetadataStore(engine)

    assert store.allocate_document_id() == "1"
    assert store.allocate_document_id() == "2"


def test_id_generator_is_removed_from_sdk_assembly_signatures() -> None:
    assert (
        "id_generator" not in inspect.signature(DefaultDocumentManagementSDK).parameters
    )
    assert (
        "id_generator" not in inspect.signature(DocumentManagementSDKFactory).parameters
    )


def test_operation_store_is_removed_from_factory_signature() -> None:
    assert (
        "operation_store"
        not in inspect.signature(DocumentManagementSDKFactory).parameters
    )
