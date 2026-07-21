from __future__ import annotations

import logging
import os
import warnings
from collections.abc import Callable, Iterable, Mapping

from typing import Any, NoReturn, TypeAlias

from sqlalchemy.engine import Engine

from dms.domain.interfaces import MetadataStore, ObjectStore, UploadOperationStore
from dms.infrastructure.metadata.operations import SqlAlchemyUploadOperationStore
from dms.infrastructure.metadata.postgres import PostgresMetadataStore
from dms.infrastructure.metadata.sqlite import SqliteMetadataStore
from dms.infrastructure.storage.minio import MinioObjectStore
from docmesh_py_core import (
    ConfigError,
    ServiceBundle,
    ServiceConfigs,
    assemble_services,
    close_service_clients,
    create_minio_client,
    create_postgres_client,
    create_sqlite_client,
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
    resolve_assembly_decision,
    truthy as _truthy,
)
from dms.sdk.configuration import validate_dms_service_configs
from dms.sdk.error_translation import translate_assembly_error
from dms.sdk.assembly import create_sdk_from_bundle as assemble_dms_sdk
from dms.sdk.errors import ConfigurationError, HealthCheckFailedError
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

def create_sdk_from_clients(
    *,
    engine: Engine,
    minio_client: Any,
    bucket_name: str,
    logger: logging.Logger | None = None,
    id_generator: DocumentIdGenerator | None = None,
    close_callbacks: Iterable[Callable[[], object]] | None = None,
    max_file_size: int | None = None,
    metadata_validator: MetadataValidator | None = None,
    metadata_max_serialized_bytes: int = 16_384,
    metadata_max_depth: int = 8,
    recovery_audit_hook: Callable[[RecoveryAuditEvent], object] | None = None,
) -> DefaultDocumentManagementSDK:
    """Build an SDK around caller-owned SQLAlchemy and MinIO clients."""
    if not bucket_name.strip():
        raise ConfigurationError("bucket_name is required to build the DMS SDK")

    dialect = engine.dialect.name
    if dialect == "postgresql":
        store_type = PostgresMetadataStore
    elif dialect == "sqlite":
        store_type = SqliteMetadataStore
    else:
        raise ConfigurationError(f"Unsupported SQLAlchemy dialect for DMS: {dialect}")

    return create_sdk_from_components(
        metadata_store=store_type(engine),
        object_store=MinioObjectStore(client=minio_client, bucket_name=bucket_name),
        logger=logger,
        id_generator=id_generator,
        close_callbacks=close_callbacks,
        max_file_size=max_file_size,
        operation_store=SqlAlchemyUploadOperationStore(engine),
        metadata_validator=metadata_validator,
        metadata_max_serialized_bytes=metadata_max_serialized_bytes,
        metadata_max_depth=metadata_max_depth,
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
    decision = resolve_assembly_decision(env)
    diagnosis = decision.diagnosis
    # Preserve legacy auto-mode validation in docmesh core; explicit selection and
    # strict ambiguity are DMS-owned policy and must fail before assembly.
    if decision.should_reject:
        raise ConfigurationError(
            "Invalid DMS environment configuration: " + format_environment_diagnosis(diagnosis),
            diagnosis=diagnosis,
        )
    for message in diagnosis.warnings:
        warnings.warn(message, UserWarning, stacklevel=2)
    services = {service.value for service in decision.plan.selected_services}
    required = {service.value for service in decision.plan.required_services}
    one_of = tuple(
        {service.value for service in group}
        for group in decision.plan.alternative_groups
    )
    try:
        bundle = assemble_services(
            services=services,
            required=required,
            one_of=one_of,
            check_on_startup=diagnosis.healthcheck_enabled,
            parallel_healthchecks=False,
        )
    except Exception as exc:
        translated = translate_assembly_error(exc, diagnosis=diagnosis)
        if translated is not None:
            raise translated from exc
        raise

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
    return validate_dms_service_configs(configs)


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
    return assemble_dms_sdk(
        bundle,
        logger=logger,
        metadata_validator=metadata_validator,
        metadata_max_serialized_bytes=metadata_max_serialized_bytes,
        metadata_max_depth=metadata_max_depth,
        recovery_audit_hook=recovery_audit_hook,
        metadata_store_factory=_create_metadata_stores,
        object_store_factory=_create_object_store,
    )


def _close_after_failure(close: Callable[[], object], exc: Exception, resource: str) -> None:
    try:
        close()
    except Exception as close_exc:
        exc.add_note(f"Failed to close {resource} after DMS assembly failure: {close_exc}")


def _raise_sdk_assembly_error(exc: Exception) -> NoReturn:
    translated = translate_assembly_error(exc)
    if translated is not None:
        raise translated from exc
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
