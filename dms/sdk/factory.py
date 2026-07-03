from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterable, Mapping
from contextlib import contextmanager
from typing import Any, cast, overload

from dms.domain.interfaces import AuthService, MetadataIdGenerator, MetadataStore, ObjectStore
from dms.infrastructure.metadata.postgres import PostgresMetadataStore
from dms.infrastructure.metadata.sqlite import SqliteMetadataStore
from dms.infrastructure.storage.minio import MinioObjectStore
from dms.sdk.errors import ConfigurationError, HealthCheckFailedError
from dms.sdk.implementation import DefaultDocumentManagementSDK

try:  # pragma: no cover - dependency boundary
    from docmesh_py_core import (
        ConfigError,
        HealthCheckError,
        check_all_services,
        close_service_clients,
        create_keycloak_client,
        create_minio_client,
        create_postgres_client,
        create_sqlite_client,
        load_service_configs,
    )
except ImportError:  # pragma: no cover - dependency boundary
    ConfigError = None
    HealthCheckError = None
    check_all_services = None
    close_service_clients = None
    create_keycloak_client = None
    create_minio_client = None
    create_postgres_client = None
    create_sqlite_client = None
    load_service_configs = None


@overload
def create_sdk(env: Mapping[str, str], /, *, logger: logging.Logger | None = None) -> DefaultDocumentManagementSDK: ...


@overload
def create_sdk(
    *,
    metadata_store: MetadataStore,
    object_store: ObjectStore,
    auth_service: AuthService | None = None,
    logger: logging.Logger | None = None,
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
    logger: logging.Logger | None = None,
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
        return create_sdk_from_environment(env, logger=logger)

    if metadata_store is None or object_store is None:
        raise TypeError("create_sdk requires either env or both metadata_store and object_store")

    return DefaultDocumentManagementSDK(
        metadata_store=metadata_store,
        object_store=object_store,
        auth_service=auth_service,
        logger=logger,
        id_generator=id_generator,
        service_checks=service_checks,
        close_callbacks=close_callbacks,
    )


def create_sdk_from_environment(
    env: Mapping[str, str],
    *,
    logger: logging.Logger | None = None,
) -> DefaultDocumentManagementSDK:
    if any(
        dependency is None
        for dependency in (
            ConfigError,
            HealthCheckError,
            check_all_services,
            close_service_clients,
            create_minio_client,
            create_postgres_client,
            create_sqlite_client,
            load_service_configs,
        )
    ):
        raise ConfigurationError("docmesh-py-core must be installed to load environment settings")

    services = {"minio"}
    if _has_postgres_configuration(env):
        services.add("postgres")
    elif _has_sqlite_configuration(env):
        services.add("sqlite")
    else:
        services.update({"postgres", "sqlite"})

    if _is_truthy(env.get("DMS_AUTH_ENABLED")):
        if create_keycloak_client is None:
            raise ConfigurationError("docmesh-py-core must be installed to load environment settings")
        services.add("keycloak")

    assert ConfigError is not None
    assert HealthCheckError is not None
    assert check_all_services is not None
    assert close_service_clients is not None
    assert create_minio_client is not None
    assert create_postgres_client is not None
    assert create_sqlite_client is not None
    assert load_service_configs is not None

    try:
        settings = _load_service_configs_from_environment(env, services=services)
    except ConfigError as exc:
        raise ConfigurationError(str(exc)) from exc

    if getattr(settings, "minio", None) is None:
        raise ConfigurationError("MinIO configuration is required to build the DMS SDK")

    bucket_name = getattr(settings.minio, "bucket", None)
    if not bucket_name:
        raise ConfigurationError("MINIO_BUCKET is required to build the DMS SDK")

    clients_to_close: list[Any] = []

    metadata_service_name: str
    metadata_store: MetadataStore
    metadata_wrapper: Any
    if getattr(settings, "postgres", None) is not None:
        postgres = create_postgres_client(cast(Any, settings.postgres))
        metadata_service_name = "postgres"
        metadata_wrapper = postgres
        metadata_store = PostgresMetadataStore(postgres.client)
    elif getattr(settings, "sqlite", None) is not None:
        sqlite = create_sqlite_client(cast(Any, settings.sqlite))
        metadata_service_name = "sqlite"
        metadata_wrapper = sqlite
        metadata_store = SqliteMetadataStore(sqlite.client)
    else:
        raise ConfigurationError("PostgreSQL or SQLite configuration is required to build the DMS SDK")
    clients_to_close.append(metadata_wrapper)

    minio = create_minio_client(cast(Any, settings.minio))
    clients_to_close.append(minio)
    object_store = MinioObjectStore(client=minio.client, bucket_name=bucket_name)

    auth_service: AuthService | None = None
    service_checks = {
        metadata_service_name: metadata_wrapper.check,
        "minio": minio.check,
    }

    if _is_truthy(env.get("DMS_AUTH_ENABLED")):
        assert create_keycloak_client is not None
        try:
            keycloak = create_keycloak_client(cast(Any, settings.keycloak))
        except Exception as exc:
            raise ConfigurationError("DMS_AUTH_ENABLED=true but Keycloak service is unavailable") from exc
        auth_service = keycloak.client
        service_checks["keycloak"] = keycloak.check
        clients_to_close.append(keycloak)

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
        logger=logger,
        service_checks=service_checks,
        close_callbacks=[lambda: close_service_clients(clients_to_close)],
    )


@contextmanager
def _overlaid_environment(env: Mapping[str, str]):
    original = os.environ.copy()
    for key in list(os.environ):
        if key.startswith(("DOCMESH_", "POSTGRES_", "SQLITE_", "MINIO_", "KEYCLOAK_", "MILVUS_", "OLLAMA_", "LANGFUSE_", "NATS_")):
            os.environ.pop(key, None)
    os.environ.update(env)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(original)


def _load_service_configs_from_environment(env: Mapping[str, str], *, services: set[str]):
    assert load_service_configs is not None
    with _overlaid_environment(env):
        return load_service_configs(services=services)


def _is_truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _has_postgres_configuration(env: Mapping[str, str]) -> bool:
    return any(key.startswith("POSTGRES_") for key in env)


def _has_sqlite_configuration(env: Mapping[str, str]) -> bool:
    return "SQLITE_PATH" in env
