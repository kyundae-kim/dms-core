from __future__ import annotations

from sqlalchemy import create_engine, text

from dms import create_sdk_from_clients
from dms.infrastructure.metadata.operations import SqlAlchemyUploadOperationStore
from dms.infrastructure.metadata.sqlite import SqliteMetadataStore
from dms.infrastructure.storage.minio import MinioObjectStore


class StubMinioClient:
    pass


def test_client_factory_builds_sdk_adapters_from_existing_clients() -> None:
    engine = create_engine("sqlite:///:memory:")
    minio_client = StubMinioClient()

    sdk = create_sdk_from_clients(
        engine=engine,
        minio_client=minio_client,
        bucket_name="documents",
    )

    assert isinstance(sdk._metadata_store, SqliteMetadataStore)
    assert isinstance(sdk._operation_store, SqlAlchemyUploadOperationStore)
    assert isinstance(sdk._object_store, MinioObjectStore)
    assert sdk._metadata_store._engine is engine
    assert sdk._object_store._client is minio_client
    assert sdk._object_store._bucket_name == "documents"


def test_client_factory_does_not_own_injected_clients_by_default() -> None:
    engine = create_engine("sqlite:///:memory:")
    sdk = create_sdk_from_clients(
        engine=engine,
        minio_client=StubMinioClient(),
        bucket_name="documents",
    )

    sdk.close()

    with engine.connect() as connection:
        assert connection.execute(text("select 1")).scalar_one() == 1


def test_client_factory_runs_only_explicit_close_callbacks_once() -> None:
    engine = create_engine("sqlite:///:memory:")
    calls: list[str] = []
    sdk = create_sdk_from_clients(
        engine=engine,
        minio_client=StubMinioClient(),
        bucket_name="documents",
        close_callbacks=[lambda: calls.append("host cleanup")],
    )

    sdk.close()
    sdk.close()

    assert calls == ["host cleanup"]
