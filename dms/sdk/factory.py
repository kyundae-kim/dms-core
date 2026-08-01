from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping

from typing import Any, TypeAlias

from sqlalchemy.engine import Engine

from dms.domain.interfaces import MetadataStore, ObjectStore, UploadOperationStore
from dms.infrastructure.metadata.operations import SqlAlchemyUploadOperationStore
from dms.infrastructure.metadata.postgres import PostgresMetadataStore
from dms.infrastructure.metadata.sqlite import SqliteMetadataStore
from dms.infrastructure.storage.minio import MinioObjectStore
from dms.sdk.errors import ConfigurationError
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
