from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, TypeAlias, cast

from dms.domain.interfaces import MetadataStore, ObjectStore
from dms.infrastructure.metadata.postgres import PostgresMetadataStore
from dms.infrastructure.metadata.sqlite import SqliteMetadataStore
from dms.infrastructure.storage.minio import MinioObjectStore
from docmesh_py_core import (
    ConfigError,
    HealthCheckError,
    check_all_services,
    close_service_clients,
    create_minio_client,
    create_postgres_client,
    create_sqlite_client,
    load_service_configs,
)
from dms.sdk.errors import ConfigurationError, HealthCheckFailedError
from dms.sdk.implementation import DefaultDocumentManagementSDK


DocumentIdGenerator: TypeAlias = Callable[[], str]


@dataclass(frozen=True)
class _MetadataAssembly:
    service_name: str
    store: MetadataStore
    client_wrapper: Any


def create_sdk_from_components(
    *,
    metadata_store: MetadataStore,
    object_store: ObjectStore,
    logger: logging.Logger | None = None,
    id_generator: DocumentIdGenerator | None = None,
    service_checks: Mapping[str, Callable[[], object]] | None = None,
    close_callbacks: Iterable[Callable[[], object]] | None = None,
) -> DefaultDocumentManagementSDK:
    return DefaultDocumentManagementSDK(
        metadata_store=metadata_store,
        object_store=object_store,
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
    settings = _load_settings_from_environment(env)
    metadata = _create_metadata_assembly(settings)
    minio, object_store = _create_object_store(settings)
    service_checks = _build_service_checks(metadata, minio)
    _run_healthchecks_if_enabled(settings, service_checks)
    close_callbacks = _build_close_callbacks([metadata.client_wrapper, minio])

    return create_sdk_from_components(
        metadata_store=metadata.store,
        object_store=object_store,
        logger=logger,
        service_checks=service_checks,
        close_callbacks=close_callbacks,
    )


def _load_settings_from_environment(env: Mapping[str, str]):
    services = _resolve_requested_services(env)
    try:
        return _load_service_configs_from_environment(env, services=services)
    except ConfigError as exc:
        raise ConfigurationError(str(exc)) from exc


def _resolve_requested_services(env: Mapping[str, str]) -> set[str]:
    services = {"minio"}
    if _has_postgres_configuration(env):
        services.add("postgres")
    elif _has_sqlite_configuration(env):
        services.add("sqlite")
    else:
        services.update({"postgres", "sqlite"})
    return services


def _create_metadata_assembly(settings: Any) -> _MetadataAssembly:
    if getattr(settings, "postgres", None) is not None:
        postgres = create_postgres_client(cast(Any, settings.postgres))
        return _MetadataAssembly(
            service_name="postgres",
            store=PostgresMetadataStore(postgres.client),
            client_wrapper=postgres,
        )

    if getattr(settings, "sqlite", None) is not None:
        sqlite = create_sqlite_client(cast(Any, settings.sqlite))
        return _MetadataAssembly(
            service_name="sqlite",
            store=SqliteMetadataStore(sqlite.client),
            client_wrapper=sqlite,
        )

    raise ConfigurationError("PostgreSQL or SQLite configuration is required to build the DMS SDK")


def _create_object_store(settings: Any) -> tuple[Any, ObjectStore]:
    minio_settings = getattr(settings, "minio", None)
    if minio_settings is None:
        raise ConfigurationError("MinIO configuration is required to build the DMS SDK")

    bucket_name = getattr(minio_settings, "bucket", None)
    if not bucket_name:
        raise ConfigurationError("MINIO_BUCKET is required to build the DMS SDK")

    minio = create_minio_client(cast(Any, minio_settings))
    object_store = MinioObjectStore(client=minio.client, bucket_name=bucket_name)
    return minio, object_store


def _build_service_checks(
    metadata: _MetadataAssembly,
    minio: Any,
) -> dict[str, Callable[[], object]]:
    return {
        metadata.service_name: metadata.client_wrapper.check,
        "minio": minio.check,
    }


def _run_healthchecks_if_enabled(
    settings: Any,
    service_checks: Mapping[str, Callable[[], object]],
) -> None:
    healthcheck_enabled = getattr(getattr(settings, "common", None), "healthcheck_enabled", True)
    if not healthcheck_enabled:
        return

    try:
        check_all_services(service_checks, required_services=set(service_checks))
    except HealthCheckError as exc:
        raise HealthCheckFailedError(str(exc)) from exc


def _build_close_callbacks(clients_to_close: Iterable[Any]) -> list[Callable[[], object]]:
    return [lambda: close_service_clients(clients_to_close)]


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
    with _overlaid_environment(env):
        return load_service_configs(services=services)


def _has_postgres_configuration(env: Mapping[str, str]) -> bool:
    return any(key.startswith("POSTGRES_") for key in env)


def _has_sqlite_configuration(env: Mapping[str, str]) -> bool:
    return "SQLITE_PATH" in env
