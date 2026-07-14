from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, TypeAlias

from dms.domain.interfaces import MetadataStore, ObjectStore
from dms.infrastructure.metadata.postgres import PostgresMetadataStore
from dms.infrastructure.metadata.sqlite import SqliteMetadataStore
from dms.infrastructure.storage.minio import MinioObjectStore
from docmesh_py_core import (
    ConfigError,
    HealthCheckError,
    assemble_services,
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
    services, required, one_of = _resolve_assembly_policy(env)
    try:
        bundle = assemble_services(
            env,
            services=services,
            required=required,
            one_of=one_of,
            check_on_startup=_healthcheck_enabled(env),
        )
    except ConfigError as exc:
        raise ConfigurationError(str(exc)) from exc
    except HealthCheckError as exc:
        raise HealthCheckFailedError(str(exc)) from exc

    try:
        metadata = _create_metadata_assembly(bundle.configs, bundle.clients)
        object_store = _create_object_store(bundle.configs, bundle.clients)
        return create_sdk_from_components(
            metadata_store=metadata.store,
            object_store=object_store,
            logger=logger,
            service_checks=bundle.checks,
            close_callbacks=[bundle.close],
        )
    except Exception as exc:
        try:
            bundle.close()
        except Exception as close_exc:
            exc.add_note(f"Failed to close service bundle after DMS assembly failure: {close_exc}")
        raise


def _resolve_assembly_policy(env: Mapping[str, str]) -> tuple[set[str], set[str], tuple[set[str], ...]]:
    if _has_postgres_configuration(env):
        return {"minio", "postgres"}, {"minio", "postgres"}, ()
    if _has_sqlite_configuration(env):
        return {"minio", "sqlite"}, {"minio", "sqlite"}, ()
    return {"minio", "postgres", "sqlite"}, {"minio"}, ({"postgres", "sqlite"},)


def _create_metadata_assembly(settings: Any, clients: Mapping[str, Any]) -> _MetadataAssembly:
    if getattr(settings, "postgres", None) is not None:
        postgres = clients["postgres"]
        return _MetadataAssembly(
            service_name="postgres",
            store=PostgresMetadataStore(postgres.client),
            client_wrapper=postgres,
        )

    if getattr(settings, "sqlite", None) is not None:
        sqlite = clients["sqlite"]
        return _MetadataAssembly(
            service_name="sqlite",
            store=SqliteMetadataStore(sqlite.client),
            client_wrapper=sqlite,
        )

    raise ConfigurationError("PostgreSQL or SQLite configuration is required to build the DMS SDK")


def _create_object_store(settings: Any, clients: Mapping[str, Any]) -> ObjectStore:
    minio_settings = getattr(settings, "minio", None)
    if minio_settings is None:
        raise ConfigurationError("MinIO configuration is required to build the DMS SDK")

    bucket_name = getattr(minio_settings, "bucket", None)
    if not bucket_name:
        raise ConfigurationError("MINIO_BUCKET is required to build the DMS SDK")

    minio = clients["minio"]
    return MinioObjectStore(client=minio.client, bucket_name=bucket_name)


def _healthcheck_enabled(env: Mapping[str, str]) -> bool:
    value = env.get("DOCMESH_HEALTHCHECK_ENABLED")
    return value is None or value.strip().lower() not in {"0", "false", "no", "off"}


def _has_postgres_configuration(env: Mapping[str, str]) -> bool:
    return any(key.startswith("POSTGRES_") for key in env)


def _has_sqlite_configuration(env: Mapping[str, str]) -> bool:
    return "SQLITE_PATH" in env
