from __future__ import annotations

import logging
import os
import warnings
from collections.abc import Callable, Iterable, Mapping

from typing import Any, NoReturn, TypeAlias

from dms.domain.interfaces import MetadataStore, ObjectStore, UploadOperationStore
from dms.infrastructure.metadata.operations import SqlAlchemyUploadOperationStore
from dms.infrastructure.metadata.postgres import PostgresMetadataStore
from dms.infrastructure.metadata.sqlite import SqliteMetadataStore
from dms.infrastructure.storage.minio import MinioObjectStore
from docmesh_py_core import (
    ConfigError,
    HealthCheckError,
    ServiceBundle,
    ServiceClientError,
    ServiceConfigs,
    ServiceUnavailableError,
    assemble_services,
    close_service_clients,
    create_minio_client,
    create_postgres_client,
    create_sqlite_client,
    require_minio_bucket,
    validate_runtime_security,
)
from dms.sdk.environment import (
    EnvironmentDiagnosis,
    diagnose_environment,
    format_environment_diagnosis,
    explicit_backend as _explicit_backend,
    has_postgres_configuration as _has_postgres_configuration,
    has_sqlite_configuration as _has_sqlite_configuration,
    healthcheck_enabled as _healthcheck_enabled,
    resolve_assembly_policy as _resolve_assembly_policy,
    truthy as _truthy,
)
from dms.sdk.errors import ConfigurationError, HealthCheckFailedError, MetadataStoreError, StorageError
from dms.sdk.implementation import DefaultDocumentManagementSDK
from dms.sdk.metadata import DefaultMetadataPolicy, MetadataValidator
from dms.sdk.types import RecoveryAuditEvent


DocumentIdGenerator: TypeAlias = Callable[[], str]



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
    *,
    logger: logging.Logger | None = None,
    metadata_validator: MetadataValidator | None = None,
    metadata_max_serialized_bytes: int = 16_384,
    metadata_max_depth: int = 8,
    recovery_audit_hook: Callable[[RecoveryAuditEvent], object] | None = None,
) -> DefaultDocumentManagementSDK:
    env = dict(os.environ)
    diagnosis = diagnose_environment(env)
    explicit = _explicit_backend(env)
    strict_ambiguity = explicit is None and _has_postgres_configuration(env) and _has_sqlite_configuration(env) and _truthy(env, "DMS_CONFIGURATION_STRICT")
    # Preserve legacy auto-mode validation in docmesh core; explicit selection and
    # strict ambiguity are DMS-owned policy and must fail before assembly.
    if (explicit is not None and not diagnosis.valid) or strict_ambiguity or diagnosis.unsupported_keys:
        raise ConfigurationError(
            "Invalid DMS environment configuration: " + format_environment_diagnosis(diagnosis),
            diagnosis=diagnosis,
        )
    for message in diagnosis.warnings:
        warnings.warn(message, UserWarning, stacklevel=2)
    services, required, one_of = _resolve_assembly_policy(env)
    try:
        bundle = assemble_services(
            services=services,
            required=required,
            one_of=one_of,
            check_on_startup=_healthcheck_enabled(env),
            parallel_healthchecks=False,
        )
    except ConfigError as exc:
        raise ConfigurationError(str(exc), diagnosis=diagnosis) from exc
    except HealthCheckError as exc:
        raise HealthCheckFailedError(
            str(exc), service=exc.service, reason=exc.error) from exc
    except (ServiceClientError, ServiceUnavailableError) as exc:
        error_type = StorageError if exc.service == "minio" else MetadataStoreError
        raise error_type(str(exc)) from exc

    return _create_sdk_from_bundle(
        bundle,
        logger=logger,
        metadata_validator=metadata_validator,
        metadata_max_serialized_bytes=metadata_max_serialized_bytes,
        metadata_max_depth=metadata_max_depth,
        recovery_audit_hook=recovery_audit_hook,
    )


def create_sdk_from_service_configs(
    configs: ServiceConfigs,
    *,
    logger: logging.Logger | None = None,
    metadata_validator: MetadataValidator | None = None,
    metadata_max_serialized_bytes: int = 16_384,
    metadata_max_depth: int = 8,
    recovery_audit_hook: Callable[[RecoveryAuditEvent], object] | None = None,
    check_on_startup: bool = False,
) -> DefaultDocumentManagementSDK:
    bundle: ServiceBundle | None = None
    try:
        bundle = _assemble_bundle_from_service_configs(configs)
        if check_on_startup:
            bundle.check(parallel=False)
        return _create_sdk_from_bundle(
            bundle,
            logger=logger,
            metadata_validator=metadata_validator,
            metadata_max_serialized_bytes=metadata_max_serialized_bytes,
            metadata_max_depth=metadata_max_depth,
            recovery_audit_hook=recovery_audit_hook,
        )
    except Exception as exc:
        if bundle is not None:
            _close_after_failure(bundle.close, exc, "service bundle")
        _raise_sdk_assembly_error(exc)


def _validate_dms_service_configs(configs: ServiceConfigs) -> str:
    has_postgres = configs.postgres is not None
    has_sqlite = configs.sqlite is not None
    if has_postgres == has_sqlite:
        raise ConfigurationError(
            "Exactly one of PostgreSQL or SQLite configuration is required to build the DMS SDK"
        )
    if configs.minio is None:
        raise ConfigurationError("MinIO configuration is required to build the DMS SDK")
    try:
        validate_runtime_security(configs.common, minio=configs.minio)
        bucket = require_minio_bucket(configs.minio)
        if not bucket.strip():
            raise ConfigError("MINIO_BUCKET is required to build the DMS SDK")
    except ConfigError as exc:
        raise ConfigurationError(str(exc)) from exc
    return "postgres" if has_postgres else "sqlite"


def _assemble_bundle_from_service_configs(configs: ServiceConfigs) -> ServiceBundle:
    metadata_service = _validate_dms_service_configs(configs)
    clients: dict[str, Any] = {}
    try:
        if metadata_service == "postgres":
            clients["postgres"] = create_postgres_client(configs.require_postgres())
        else:
            clients["sqlite"] = create_sqlite_client(configs.require_sqlite())
        clients["minio"] = create_minio_client(configs.require_minio())
    except Exception as exc:
        _close_after_failure(lambda: close_service_clients(clients.values()), exc, "service clients")
        raise
    selected = frozenset({metadata_service, "minio"})
    return ServiceBundle(
        configs=configs,
        clients=clients,
        selected_services=selected,
        required_services=selected,
    )


def _create_sdk_from_bundle(
    bundle: ServiceBundle,
    *,
    logger: logging.Logger | None,
    metadata_validator: MetadataValidator | None,
    metadata_max_serialized_bytes: int,
    metadata_max_depth: int,
    recovery_audit_hook: Callable[[RecoveryAuditEvent], object] | None,
) -> DefaultDocumentManagementSDK:
    try:
        metadata_store, operation_store = _create_metadata_stores(bundle)
        object_store = _create_object_store(bundle)
        return create_sdk_from_components(
            metadata_store=metadata_store,
            object_store=object_store,
            operation_store=operation_store,
            logger=logger,
            service_checks=bundle.checks,
            close_callbacks=[bundle.close],
            metadata_validator=metadata_validator,
            metadata_max_serialized_bytes=metadata_max_serialized_bytes,
            metadata_max_depth=metadata_max_depth,
            recovery_audit_hook=recovery_audit_hook,
        )
    except Exception as exc:
        _close_after_failure(bundle.close, exc, "service bundle")
        raise


def _close_after_failure(close: Callable[[], object], exc: Exception, resource: str) -> None:
    try:
        close()
    except Exception as close_exc:
        exc.add_note(f"Failed to close {resource} after DMS assembly failure: {close_exc}")


def _raise_sdk_assembly_error(exc: Exception) -> NoReturn:
    if isinstance(exc, ConfigurationError):
        raise exc
    if isinstance(exc, ConfigError):
        raise ConfigurationError(str(exc)) from exc
    if isinstance(exc, HealthCheckError):
        raise HealthCheckFailedError(str(exc), service=exc.service, reason=exc.error) from exc
    if isinstance(exc, (ServiceClientError, ServiceUnavailableError)):
        error_type = StorageError if exc.service == "minio" else MetadataStoreError
        raise error_type(str(exc)) from exc
    raise exc


def _create_metadata_stores(bundle: Any) -> tuple[MetadataStore, UploadOperationStore]:
    settings = bundle.configs
    store_type: Any
    if getattr(settings, "postgres", None) is not None:
        service_name, store_type = "postgres", PostgresMetadataStore
    elif getattr(settings, "sqlite", None) is not None:
        service_name, store_type = "sqlite", SqliteMetadataStore
    else:
        raise ConfigurationError("PostgreSQL or SQLite configuration is required to build the DMS SDK")
    client = bundle.get_client(service_name).unwrap()
    return store_type(client), SqlAlchemyUploadOperationStore(client)


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
