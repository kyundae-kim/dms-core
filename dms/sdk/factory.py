from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import overload

from dms.domain.interfaces import AuthService, MetadataIdGenerator, MetadataStore, ObjectStore
from dms.infrastructure.metadata.postgres import PostgresMetadataStore
from dms.infrastructure.metadata.sqlite import SqliteMetadataStore
from dms.infrastructure.storage.minio import MinioObjectStore
from dms.sdk.errors import ConfigurationError, HealthCheckFailedError
from dms.sdk.implementation import DefaultDocumentManagementSDK


@overload
def create_sdk(env: Mapping[str, str], /) -> DefaultDocumentManagementSDK: ...


@overload
def create_sdk(
    *,
    metadata_store: MetadataStore,
    object_store: ObjectStore,
    auth_service: AuthService | None = None,
    id_generator: MetadataIdGenerator | None = None,
    service_checks: Mapping[str, Callable[[], object]] | None = None,
    close_callbacks: Iterable[Callable[[], object]] | None = None,
) -> DefaultDocumentManagementSDK: ...


def create_sdk(
    env: Mapping[str, str] | None = None,
    /,
    *,
    metadata_store: MetadataStore | None = None,
    object_store: ObjectStore | None = None,
    auth_service: AuthService | None = None,
    id_generator: MetadataIdGenerator | None = None,
    service_checks: Mapping[str, Callable[[], object]] | None = None,
    close_callbacks: Iterable[Callable[[], object]] | None = None,
) -> DefaultDocumentManagementSDK:
    if env is not None:
        if any(
            value is not None
            for value in (metadata_store, object_store, auth_service, id_generator, service_checks, close_callbacks)
        ):
            raise TypeError(
                "create_sdk accepts either an environment mapping or explicit dependencies, not both"
            )
        return create_sdk_from_environment(env)

    if metadata_store is None or object_store is None:
        raise TypeError("create_sdk requires either env or both metadata_store and object_store")

    return DefaultDocumentManagementSDK(
        metadata_store=metadata_store,
        object_store=object_store,
        auth_service=auth_service,
        id_generator=id_generator,
        service_checks=service_checks,
        close_callbacks=close_callbacks,
    )


def create_sdk_from_environment(env: Mapping[str, str]) -> DefaultDocumentManagementSDK:
    try:
        from docmesh_py_core import (
            ConfigError,
            HealthCheckError,
            ServiceFactoryRegistry,
            check_all_services,
            load_settings,
        )
    except ImportError as exc:  # pragma: no cover - dependency boundary
        raise ConfigurationError("docmesh-py-core must be installed to load environment settings") from exc

    try:
        settings = load_settings(env)
    except ConfigError as exc:
        raise ConfigurationError(str(exc)) from exc

    if getattr(settings, "minio", None) is None:
        raise ConfigurationError("MinIO configuration is required to build the DMS SDK")

    bucket_name = getattr(settings.minio, "bucket", None)
    if not bucket_name:
        raise ConfigurationError("MINIO_BUCKET is required to build the DMS SDK")

    registry = ServiceFactoryRegistry(settings)

    metadata_service_name: str
    metadata_store: MetadataStore
    if getattr(settings, "postgres", None) is not None:
        postgres = registry.create_client("postgres")
        metadata_service_name = "postgres"
        metadata_store = PostgresMetadataStore(postgres.client)
    elif getattr(settings, "sqlite", None) is not None:
        sqlite = registry.create_client("sqlite")
        metadata_service_name = "sqlite"
        metadata_store = SqliteMetadataStore(sqlite.client)
    else:
        raise ConfigurationError("PostgreSQL or SQLite configuration is required to build the DMS SDK")

    minio = registry.create_client("minio")
    object_store = MinioObjectStore(client=minio.client, bucket_name=bucket_name)

    auth_service: AuthService | None = None
    service_checks = {
        metadata_service_name: registry.create_client(metadata_service_name).check,
        "minio": minio.check,
    }

    if _is_truthy(env.get("DMS_AUTH_ENABLED")):
        try:
            keycloak = registry.create_client("keycloak")
        except Exception as exc:
            raise ConfigurationError("DMS_AUTH_ENABLED=true but Keycloak service is unavailable") from exc
        auth_service = keycloak.client
        service_checks["keycloak"] = keycloak.check

    healthcheck_enabled = getattr(getattr(settings, "common", None), "healthcheck_enabled", True)
    if healthcheck_enabled:
        try:
            check_all_services(service_checks, required_services=set(service_checks))
        except HealthCheckError as exc:
            raise HealthCheckFailedError(str(exc)) from exc

    return create_sdk(
        metadata_store=metadata_store,
        object_store=object_store,
        auth_service=auth_service,
        service_checks=service_checks,
        close_callbacks=[registry.close_all],
    )


def _is_truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}
