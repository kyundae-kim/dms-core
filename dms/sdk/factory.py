from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping

from dms.domain.interfaces import MetadataIdGenerator, MetadataStore, ObjectStore
from dms.infrastructure.metadata.postgres import PostgresMetadataStore
from dms.infrastructure.storage.minio import MinioObjectStore
from dms.sdk.errors import ConfigurationError
from dms.sdk.implementation import DefaultDocumentManagementSDK


def create_sdk(
    *,
    metadata_store: MetadataStore,
    object_store: ObjectStore,
    id_generator: MetadataIdGenerator | None = None,
    service_checks: Mapping[str, Callable[[], object]] | None = None,
    close_callbacks: Iterable[Callable[[], object]] | None = None,
) -> DefaultDocumentManagementSDK:
    return DefaultDocumentManagementSDK(
        metadata_store=metadata_store,
        object_store=object_store,
        id_generator=id_generator,
        service_checks=service_checks,
        close_callbacks=close_callbacks,
    )


def create_sdk_from_environment(env: Mapping[str, str]) -> DefaultDocumentManagementSDK:
    try:
        from docmesh_py_core import ConfigError, ServiceFactoryRegistry, load_settings
    except ImportError as exc:  # pragma: no cover - dependency boundary
        raise ConfigurationError("docmesh-py-core must be installed to load environment settings") from exc

    try:
        settings = load_settings(env)
    except ConfigError as exc:
        raise ConfigurationError(str(exc)) from exc

    if getattr(settings, "postgres", None) is None:
        raise ConfigurationError("PostgreSQL configuration is required to build the DMS SDK")
    if getattr(settings, "minio", None) is None:
        raise ConfigurationError("MinIO configuration is required to build the DMS SDK")

    bucket_name = getattr(settings.minio, "bucket", None)
    if not bucket_name:
        raise ConfigurationError("MINIO_BUCKET is required to build the DMS SDK")

    registry = ServiceFactoryRegistry(settings)
    postgres = registry.create_client("postgres")
    minio = registry.create_client("minio")

    metadata_store = PostgresMetadataStore(postgres.client)
    object_store = MinioObjectStore(client=minio.client, bucket_name=bucket_name)

    return create_sdk(
        metadata_store=metadata_store,
        object_store=object_store,
        service_checks={
            "postgres": postgres.check,
            "minio": minio.check,
        },
        close_callbacks=[registry.close_all],
    )
