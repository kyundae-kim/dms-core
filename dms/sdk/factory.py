from __future__ import annotations

import logging
import warnings
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, TypeAlias

from dms.domain.interfaces import MetadataStore, ObjectStore, UploadOperationStore
from dms.infrastructure.metadata.operations import SqlAlchemyUploadOperationStore
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
from dms.sdk.metadata import DefaultMetadataPolicy, MetadataValidator


DocumentIdGenerator: TypeAlias = Callable[[], str]


@dataclass(frozen=True)
class EnvironmentDiagnosis:
    metadata_backend: str | None
    object_backend: str
    healthcheck_enabled: bool
    missing_required_keys: tuple[str, ...]
    warnings: tuple[str, ...]
    valid: bool


@dataclass(frozen=True)
class _MetadataAssembly:
    service_name: str
    store: MetadataStore
    client_wrapper: Any
    operation_store: UploadOperationStore


def create_sdk_from_components(
    *,
    metadata_store: MetadataStore,
    object_store: ObjectStore,
    logger: logging.Logger | None = None,
    id_generator: DocumentIdGenerator | None = None,
    service_checks: Mapping[str, Callable[[], object]] | None = None,
    close_callbacks: Iterable[Callable[[], object]] | None = None,
    max_file_size: int | None = None,
    operation_store: UploadOperationStore | None = None,
    metadata_validator: MetadataValidator | None = None,
    metadata_max_serialized_bytes: int = 16_384,
    metadata_max_depth: int = 8,
) -> DefaultDocumentManagementSDK:
    return DefaultDocumentManagementSDK(
        metadata_store=metadata_store,
        object_store=object_store,
        logger=logger,
        id_generator=id_generator,
        service_checks=service_checks,
        close_callbacks=close_callbacks,
        max_file_size=max_file_size,
        operation_store=operation_store,
        metadata_validator=metadata_validator or DefaultMetadataPolicy(
            max_serialized_bytes=metadata_max_serialized_bytes, max_depth=metadata_max_depth),
    )

def create_sdk_from_environment(
    env: Mapping[str, str],
    *,
    logger: logging.Logger | None = None,
    metadata_validator: MetadataValidator | None = None,
    metadata_max_serialized_bytes: int = 16_384,
    metadata_max_depth: int = 8,
) -> DefaultDocumentManagementSDK:
    diagnosis = diagnose_environment(env)
    explicit = _explicit_backend(env)
    strict_ambiguity = explicit is None and _has_postgres_configuration(env) and _has_sqlite_configuration(env) and _truthy(env, "DMS_CONFIGURATION_STRICT")
    # Preserve legacy auto-mode validation in docmesh core; explicit selection and
    # strict ambiguity are DMS-owned policy and must fail before assembly.
    if (explicit is not None and not diagnosis.valid) or strict_ambiguity:
        details = ", ".join(diagnosis.missing_required_keys) or "; ".join(diagnosis.warnings)
        raise ConfigurationError(f"Invalid DMS environment configuration: {details}")
    for message in diagnosis.warnings:
        warnings.warn(message, UserWarning, stacklevel=2)
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
            operation_store=metadata.operation_store,
            logger=logger,
            service_checks=bundle.checks,
            close_callbacks=[bundle.close],
            metadata_validator=metadata_validator,
            metadata_max_serialized_bytes=metadata_max_serialized_bytes,
            metadata_max_depth=metadata_max_depth,
        )
    except Exception as exc:
        try:
            bundle.close()
        except Exception as close_exc:
            exc.add_note(f"Failed to close service bundle after DMS assembly failure: {close_exc}")
        raise


def _resolve_assembly_policy(env: Mapping[str, str]) -> tuple[set[str], set[str], tuple[set[str], ...]]:
    explicit = _explicit_backend(env)
    if explicit is not None:
        service = "postgres" if explicit == "postgresql" else explicit
        return {"minio", service}, {"minio", service}, ()
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
            operation_store=SqlAlchemyUploadOperationStore(postgres.client),
        )

    if getattr(settings, "sqlite", None) is not None:
        sqlite = clients["sqlite"]
        return _MetadataAssembly(
            service_name="sqlite",
            store=SqliteMetadataStore(sqlite.client),
            client_wrapper=sqlite,
            operation_store=SqlAlchemyUploadOperationStore(sqlite.client),
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


def _value(env: Mapping[str, str], key: str) -> str | None:
    value = env.get(key)
    return value.strip() if value is not None and value.strip() else None


def _explicit_backend(env: Mapping[str, str]) -> str | None:
    value = _value(env, "DMS_METADATA_BACKEND")
    return value.lower() if value is not None else None


def _truthy(env: Mapping[str, str], key: str) -> bool:
    return (_value(env, key) or "false").lower() in {"1", "true", "yes", "on"}


def diagnose_environment(env: Mapping[str, str]) -> EnvironmentDiagnosis:
    """Diagnose supplied configuration without assembling services or connecting."""
    explicit = _explicit_backend(env)
    pg, sqlite = _has_postgres_configuration(env), _has_sqlite_configuration(env)
    notes: list[str] = []
    invalid_selection = explicit is not None and explicit not in {"postgresql", "sqlite"}
    if invalid_selection:
        backend = None
        notes.append("DMS_METADATA_BACKEND must be 'postgresql' or 'sqlite'")
    elif explicit is not None:
        backend = explicit
    elif pg:
        backend = "postgresql"
        if sqlite:
            notes.append("Both PostgreSQL and SQLite are configured; PostgreSQL takes precedence in auto mode")
    elif sqlite:
        backend = "sqlite"
    else:
        backend = None
    missing = [k for k in ("MINIO_ENDPOINT", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY", "MINIO_BUCKET") if _value(env, k) is None]
    if backend == "postgresql" and _value(env, "POSTGRES_DSN") is None:
        missing += [k for k in ("POSTGRES_HOST", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD") if _value(env, k) is None]
    elif backend == "sqlite" and _value(env, "SQLITE_PATH") is None:
        missing.append("SQLITE_PATH")
    elif backend is None and not invalid_selection:
        missing.append("DMS_METADATA_BACKEND or PostgreSQL/SQLite configuration")
    strict = explicit is None and pg and sqlite and _truthy(env, "DMS_CONFIGURATION_STRICT")
    if strict:
        notes.append("Ambiguous metadata backend configuration is forbidden by DMS_CONFIGURATION_STRICT")
    return EnvironmentDiagnosis(backend, "minio", _healthcheck_enabled(env), tuple(dict.fromkeys(missing)), tuple(notes), not missing and not invalid_selection and not strict)
