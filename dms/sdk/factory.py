from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

from typing import Any, TypeAlias

from sqlalchemy.engine import Engine

from dms.domain.interfaces import MetadataStore, ObjectStore, UploadOperationStore
from dms.infrastructure.metadata.operations import SqlAlchemyUploadOperationStore
from dms.infrastructure.metadata.postgres import PostgresMetadataStore
from dms.infrastructure.metadata.sqlite import SqliteMetadataStore
from dms.infrastructure.storage.minio import MinioObjectStore
from dms.sdk.async_sdk import AsyncDocumentManagementSDK
from dms.sdk.contracts import (
    DmsAssemblyPlan,
    ManagedResource,
)
from dms.sdk.errors import ConfigurationError, HealthCheckFailedError
from dms.sdk.implementation import DefaultDocumentManagementSDK
from dms.sdk.lifecycle import LifecycleService
from dms.sdk.metadata import DefaultMetadataPolicy, MetadataValidator
from dms.sdk.types import HealthStatus, RecoveryAuditEvent


DocumentIdGenerator: TypeAlias = Callable[[], str]


def _rollback_assembly_resources(
    close_callbacks: Iterable[Callable[[], object]],
    managed_resources: Iterable[ManagedResource],
    failure: Exception,
) -> None:
    try:
        LifecycleService(
            service_checks={},
            close_callbacks=list(close_callbacks),
            managed_resources=list(managed_resources),
            logger=logging.getLogger("dms.sdk"),
        ).close()
    except Exception as cleanup_error:
        failure.add_note(f"Managed-resource rollback failed: {cleanup_error}")



def create_sdk_from_components(
    *,
    metadata_store: MetadataStore,
    object_store: ObjectStore,
    logger: logging.Logger | None = None,
    id_generator: DocumentIdGenerator | None = None,
    service_checks: Mapping[str, Callable[[], object]] | None = None,
    close_callbacks: Iterable[Callable[[], object]] | None = None,
    managed_resources: Iterable[ManagedResource] | None = None,
    plan: DmsAssemblyPlan | None = None,
    max_file_size: int | None = None,
    operation_store: UploadOperationStore | None = None,
    metadata_validator: MetadataValidator | None = None,
    metadata_max_serialized_bytes: int = 16_384,
    metadata_max_depth: int = 8,
    recovery_audit_hook: Callable[[RecoveryAuditEvent], object] | None = None,
) -> DefaultDocumentManagementSDK:
    materialized_close_callbacks = list(close_callbacks or ())
    materialized_managed_resources = list(managed_resources or ())
    try:
        active_plan = plan or DmsAssemblyPlan(
            logger=logger,
            max_file_size=max_file_size,
            metadata_validator=metadata_validator,
            metadata_max_serialized_bytes=metadata_max_serialized_bytes,
            metadata_max_depth=metadata_max_depth,
            recovery_audit_hook=recovery_audit_hook,
        )
    except Exception as failure:
        _rollback_assembly_resources(
            materialized_close_callbacks,
            materialized_managed_resources,
            failure,
        )
        raise
    sdk = DefaultDocumentManagementSDK(
        metadata_store=metadata_store,
        object_store=object_store,
        logger=active_plan.logger,
        id_generator=id_generator,
        service_checks=service_checks,
        close_callbacks=materialized_close_callbacks,
        managed_resources=materialized_managed_resources,
        max_file_size=active_plan.max_file_size,
        operation_store=operation_store,
        metadata_validator=active_plan.metadata_validator or DefaultMetadataPolicy(
            max_serialized_bytes=active_plan.metadata_max_serialized_bytes,
            max_depth=active_plan.metadata_max_depth,
        ),
        recovery_audit_hook=active_plan.recovery_audit_hook,
        access_policy=active_plan.access_policy,
        operation_observer=active_plan.operation_observer,
    )
    if active_plan.check_on_startup:
        try:
            health = _check_startup_health(
                sdk,
                timeout_seconds=active_plan.startup_timeout_seconds,
            )
            if not health.ok:
                service = next(item for item in health.services if not item.ok)
                raise HealthCheckFailedError(
                    "DMS startup health check failed",
                    service=service.service,
                    reason=service.error,
                )
        except Exception as failure:
            try:
                sdk.close()
            except Exception as cleanup_error:
                failure.add_note(f"Managed-resource rollback failed: {cleanup_error}")
            raise
    return sdk


def create_async_sdk_from_components(
    *,
    metadata_store: MetadataStore,
    object_store: ObjectStore,
    logger: logging.Logger | None = None,
    id_generator: DocumentIdGenerator | None = None,
    service_checks: Mapping[str, Callable[[], object]] | None = None,
    close_callbacks: Iterable[Callable[[], object]] | None = None,
    managed_resources: Iterable[ManagedResource] | None = None,
    plan: DmsAssemblyPlan | None = None,
    max_file_size: int | None = None,
    operation_store: UploadOperationStore | None = None,
    metadata_validator: MetadataValidator | None = None,
    metadata_max_serialized_bytes: int = 16_384,
    metadata_max_depth: int = 8,
    recovery_audit_hook: Callable[[RecoveryAuditEvent], object] | None = None,
) -> AsyncDocumentManagementSDK:
    return AsyncDocumentManagementSDK(create_sdk_from_components(
        metadata_store=metadata_store,
        object_store=object_store,
        logger=logger,
        id_generator=id_generator,
        service_checks=service_checks,
        close_callbacks=close_callbacks,
        managed_resources=managed_resources,
        plan=plan,
        max_file_size=max_file_size,
        operation_store=operation_store,
        metadata_validator=metadata_validator,
        metadata_max_serialized_bytes=metadata_max_serialized_bytes,
        metadata_max_depth=metadata_max_depth,
        recovery_audit_hook=recovery_audit_hook,
    ))

def create_sdk_from_clients(
    *,
    engine: Engine,
    minio_client: Any,
    bucket_name: str,
    logger: logging.Logger | None = None,
    id_generator: DocumentIdGenerator | None = None,
    close_callbacks: Iterable[Callable[[], object]] | None = None,
    managed_resources: Iterable[ManagedResource] | None = None,
    plan: DmsAssemblyPlan | None = None,
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
        managed_resources=managed_resources,
        plan=plan,
        max_file_size=max_file_size,
        operation_store=SqlAlchemyUploadOperationStore(engine),
        metadata_validator=metadata_validator,
        metadata_max_serialized_bytes=metadata_max_serialized_bytes,
        metadata_max_depth=metadata_max_depth,
        recovery_audit_hook=recovery_audit_hook,
    )


def create_async_sdk_from_clients(
    *,
    engine: Engine,
    minio_client: Any,
    bucket_name: str,
    logger: logging.Logger | None = None,
    id_generator: DocumentIdGenerator | None = None,
    close_callbacks: Iterable[Callable[[], object]] | None = None,
    managed_resources: Iterable[ManagedResource] | None = None,
    plan: DmsAssemblyPlan | None = None,
    max_file_size: int | None = None,
    metadata_validator: MetadataValidator | None = None,
    metadata_max_serialized_bytes: int = 16_384,
    metadata_max_depth: int = 8,
    recovery_audit_hook: Callable[[RecoveryAuditEvent], object] | None = None,
) -> AsyncDocumentManagementSDK:
    return AsyncDocumentManagementSDK(create_sdk_from_clients(
        engine=engine,
        minio_client=minio_client,
        bucket_name=bucket_name,
        logger=logger,
        id_generator=id_generator,
        close_callbacks=close_callbacks,
        managed_resources=managed_resources,
        plan=plan,
        max_file_size=max_file_size,
        metadata_validator=metadata_validator,
        metadata_max_serialized_bytes=metadata_max_serialized_bytes,
        metadata_max_depth=metadata_max_depth,
        recovery_audit_hook=recovery_audit_hook,
    ))


def _check_startup_health(
    sdk: DefaultDocumentManagementSDK,
    *,
    timeout_seconds: float | None,
) -> HealthStatus:
    if timeout_seconds is None:
        return sdk.check_health()
    executor = ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix="dms-startup-health",
    )
    future = executor.submit(sdk.check_health)
    try:
        return future.result(timeout=timeout_seconds)
    except FutureTimeoutError as exc:
        future.cancel()
        raise HealthCheckFailedError(
            "DMS startup health check timed out",
            reason=f"timeout after {timeout_seconds:g} seconds",
        ) from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
