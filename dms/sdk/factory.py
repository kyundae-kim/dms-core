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
    ServiceUnavailableError,
    assemble_services,
)
from dms.sdk.environment import (
    EnvironmentDiagnosis,
    diagnose_environment,
    explicit_backend as _explicit_backend,
    has_postgres_configuration as _has_postgres_configuration,
    has_sqlite_configuration as _has_sqlite_configuration,
    healthcheck_enabled as _healthcheck_enabled,
    resolve_assembly_policy as _resolve_assembly_policy,
    truthy as _truthy,
    value as _value,
)
from dms.sdk.errors import ConfigurationError, HealthCheckFailedError, MetadataStoreError, StorageError
from dms.sdk.implementation import DefaultDocumentManagementSDK
from dms.sdk.metadata import DefaultMetadataPolicy, MetadataValidator
from dms.sdk.types import RecoveryAuditEvent


DocumentIdGenerator: TypeAlias = Callable[[], str]


@dataclass(frozen=True)
class _MetadataAssembly:
    store: MetadataStore
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
    recovery_audit_hook: Callable[[RecoveryAuditEvent], object] | None = None,
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
        recovery_audit_hook=recovery_audit_hook,
    )

def create_sdk_from_environment(
    env: Mapping[str, str],
    *,
    logger: logging.Logger | None = None,
    metadata_validator: MetadataValidator | None = None,
    metadata_max_serialized_bytes: int = 16_384,
    metadata_max_depth: int = 8,
    recovery_audit_hook: Callable[[RecoveryAuditEvent], object] | None = None,
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
    except ServiceUnavailableError as exc:
        error_type = StorageError if exc.service == "minio" else MetadataStoreError
        raise error_type(str(exc)) from exc

    try:
        metadata = _create_metadata_assembly(bundle)
        object_store = _create_object_store(bundle)
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
            recovery_audit_hook=recovery_audit_hook,
        )
    except Exception as exc:
        try:
            bundle.close()
        except Exception as close_exc:
            exc.add_note(f"Failed to close service bundle after DMS assembly failure: {close_exc}")
        raise


def _create_metadata_assembly(bundle: Any) -> _MetadataAssembly:
    settings = bundle.configs
    if getattr(settings, "postgres", None) is not None:
        service_name, store_type = "postgres", PostgresMetadataStore
    elif getattr(settings, "sqlite", None) is not None:
        service_name, store_type = "sqlite", SqliteMetadataStore
    else:
        raise ConfigurationError("PostgreSQL or SQLite configuration is required to build the DMS SDK")
    client = bundle.get_client(service_name).unwrap()
    return _MetadataAssembly(
        store=store_type(client),
        operation_store=SqlAlchemyUploadOperationStore(client),
    )


def _create_object_store(bundle: Any) -> ObjectStore:
    settings = bundle.configs
    minio_settings = getattr(settings, "minio", None)
    if minio_settings is None:
        raise ConfigurationError("MinIO configuration is required to build the DMS SDK")

    bucket_name = getattr(minio_settings, "bucket", None)
    if not bucket_name:
        raise ConfigurationError("MINIO_BUCKET is required to build the DMS SDK")

    minio = bundle.get_client("minio").unwrap()
    return MinioObjectStore(client=minio, bucket_name=bucket_name)
