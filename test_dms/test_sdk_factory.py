from __future__ import annotations

import pytest
from sqlalchemy import create_engine

from dms import ConfigurationError
from dms.sdk.async_sdk import AsyncDocumentManagementSDK
from dms.sdk.factory import DocumentManagementSDKFactory
from test_dms.sdk_test_support import CursorMemoryStore, StreamMemoryObjectStore


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


def test_factory_rejects_blank_bucket_before_adapter_assembly() -> None:
    engine = create_engine("sqlite:///:memory:")

    with pytest.raises(ConfigurationError, match="bucket_name"):
        DocumentManagementSDKFactory(
            engine=engine,
            minio_client=StubMinioClient(),
            bucket_name=" ",
        )


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


def test_component_factory_remains_available_for_port_injection() -> None:
    from dms.sdk.factory import create_sdk_from_components

    sdk = create_sdk_from_components(
        metadata_store=CursorMemoryStore(),
        object_store=StreamMemoryObjectStore(),
    )

    assert sdk._metadata_store.__class__.__name__ == "CursorMemoryStore"


def test_component_factory_accepts_assembly_policies_without_a_plan_object() -> None:
    from dms.sdk.factory import create_sdk_from_components

    policy = object()
    observer = object()
    sdk = create_sdk_from_components(
        metadata_store=CursorMemoryStore(),
        object_store=StreamMemoryObjectStore(),
        access_policy=policy,  # type: ignore[arg-type]
        operation_observer=observer,  # type: ignore[arg-type]
    )

    assert sdk._access_policy is policy
    assert sdk._operation_observer is observer
