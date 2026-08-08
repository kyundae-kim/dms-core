from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeAlias

from sqlalchemy.engine import Engine
from minio import Minio

from dms.domain.interfaces import MetadataStore, ObjectStore, UploadOperationStore
from dms.infrastructure.metadata.operations import SqlAlchemyUploadOperationStore
from dms.infrastructure.metadata.postgres import PostgresMetadataStore
from dms.infrastructure.metadata.sqlite import SqliteMetadataStore
from dms.infrastructure.storage.minio import MinioObjectStore
from dms.sdk.async_sdk import AsyncDocumentManagementSDK
from dms.sdk.contracts import DocumentAccessPolicy, OperationObserver
from dms.sdk.errors import ConfigurationError
from dms.sdk.implementation import DefaultDocumentManagementSDK
from dms.sdk.metadata import DefaultMetadataPolicy, MetadataValidator
from dms.sdk.types import RecoveryAuditEvent


DocumentIdGenerator: TypeAlias = Callable[[], str]


def _validate_assembly_options(
    *,
    max_file_size: int | None,
    metadata_max_serialized_bytes: int,
    metadata_max_depth: int,
) -> None:
    if metadata_max_serialized_bytes <= 0:
        raise ValueError("metadata_max_serialized_bytes must be positive")
    if metadata_max_depth <= 0:
        raise ValueError("metadata_max_depth must be positive")
    if max_file_size is not None and max_file_size <= 0:
        raise ValueError("max_file_size must be positive")


@dataclass(frozen=True, slots=True, kw_only=True)
class _ComponentSDKFactory:
    """Assemble an SDK from already-adapted domain storage ports."""

    metadata_store: MetadataStore
    object_store: ObjectStore
    logger: logging.Logger | None = None
    id_generator: DocumentIdGenerator | None = None
    max_file_size: int | None = None
    operation_store: UploadOperationStore | None = None
    metadata_validator: MetadataValidator | None = None
    metadata_max_serialized_bytes: int = 16_384
    metadata_max_depth: int = 8
    recovery_audit_hook: Callable[[RecoveryAuditEvent], object] | None = None
    operation_observer: OperationObserver | None = None
    access_policy: DocumentAccessPolicy | None = None

    def __post_init__(self) -> None:
        _validate_assembly_options(
            max_file_size=self.max_file_size,
            metadata_max_serialized_bytes=self.metadata_max_serialized_bytes,
            metadata_max_depth=self.metadata_max_depth,
        )

    def create(self) -> DefaultDocumentManagementSDK:
        return DefaultDocumentManagementSDK(
            metadata_store=self.metadata_store,
            object_store=self.object_store,
            logger=self.logger,
            id_generator=self.id_generator,
            max_file_size=self.max_file_size,
            operation_store=self.operation_store,
            metadata_validator=self.metadata_validator or DefaultMetadataPolicy(
                max_serialized_bytes=self.metadata_max_serialized_bytes,
                max_depth=self.metadata_max_depth,
            ),
            recovery_audit_hook=self.recovery_audit_hook,
            access_policy=self.access_policy,
            operation_observer=self.operation_observer,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class DocumentManagementSDKFactory:
    """Create the SDK from caller-owned SQLAlchemy and MinIO clients.

    The factory adapts the supplied clients into the SDK's storage ports. It does
    not create or close either client; their lifecycle remains with the caller.
    """

    engine: Engine
    minio_client: Minio
    bucket_name: str
    logger: logging.Logger | None = None
    id_generator: DocumentIdGenerator | None = None
    max_file_size: int | None = None
    operation_store: UploadOperationStore | None = None
    metadata_validator: MetadataValidator | None = None
    metadata_max_serialized_bytes: int = 16_384
    metadata_max_depth: int = 8
    recovery_audit_hook: Callable[[RecoveryAuditEvent], object] | None = None
    operation_observer: OperationObserver | None = None
    access_policy: DocumentAccessPolicy | None = None

    def __post_init__(self) -> None:
        if not self.bucket_name.strip():
            raise ConfigurationError("bucket_name is required to build the DMS SDK")

    def create(self) -> DefaultDocumentManagementSDK:
        """Adapt the clients and create a synchronous SDK."""
        dialect = self.engine.dialect.name
        if dialect == "postgresql":
            metadata_store: MetadataStore = PostgresMetadataStore(self.engine)
        elif dialect == "sqlite":
            metadata_store = SqliteMetadataStore(self.engine)
        else:
            raise ConfigurationError(
                f"Unsupported SQLAlchemy dialect for DMS: {dialect}"
            )

        return create_sdk_from_components(
            metadata_store=metadata_store,
            object_store=MinioObjectStore(
                client=self.minio_client,
                bucket_name=self.bucket_name,
            ),
            logger=self.logger,
            id_generator=self.id_generator,
            max_file_size=self.max_file_size,
            operation_store=(
                self.operation_store or SqlAlchemyUploadOperationStore(self.engine)
            ),
            metadata_validator=self.metadata_validator,
            metadata_max_serialized_bytes=self.metadata_max_serialized_bytes,
            metadata_max_depth=self.metadata_max_depth,
            recovery_audit_hook=self.recovery_audit_hook,
            operation_observer=self.operation_observer,
            access_policy=self.access_policy,
        )

    def create_async(self) -> AsyncDocumentManagementSDK:
        """Create an asynchronous facade over a fresh synchronous SDK."""
        return AsyncDocumentManagementSDK(self.create())


def create_sdk_from_components(
    *,
    metadata_store: MetadataStore,
    object_store: ObjectStore,
    logger: logging.Logger | None = None,
    id_generator: DocumentIdGenerator | None = None,
    max_file_size: int | None = None,
    operation_store: UploadOperationStore | None = None,
    metadata_validator: MetadataValidator | None = None,
    metadata_max_serialized_bytes: int = 16_384,
    metadata_max_depth: int = 8,
    recovery_audit_hook: Callable[[RecoveryAuditEvent], object] | None = None,
    operation_observer: OperationObserver | None = None,
    access_policy: DocumentAccessPolicy | None = None,
) -> DefaultDocumentManagementSDK:
    """Build the document service around caller-provided storage ports."""
    return _ComponentSDKFactory(
        metadata_store=metadata_store,
        object_store=object_store,
        logger=logger,
        id_generator=id_generator,
        max_file_size=max_file_size,
        operation_store=operation_store,
        metadata_validator=metadata_validator,
        metadata_max_serialized_bytes=metadata_max_serialized_bytes,
        metadata_max_depth=metadata_max_depth,
        recovery_audit_hook=recovery_audit_hook,
        operation_observer=operation_observer,
        access_policy=access_policy,
    ).create()


def create_async_sdk_from_components(
    *,
    metadata_store: MetadataStore,
    object_store: ObjectStore,
    logger: logging.Logger | None = None,
    id_generator: DocumentIdGenerator | None = None,
    max_file_size: int | None = None,
    operation_store: UploadOperationStore | None = None,
    metadata_validator: MetadataValidator | None = None,
    metadata_max_serialized_bytes: int = 16_384,
    metadata_max_depth: int = 8,
    recovery_audit_hook: Callable[[RecoveryAuditEvent], object] | None = None,
    operation_observer: OperationObserver | None = None,
    access_policy: DocumentAccessPolicy | None = None,
) -> AsyncDocumentManagementSDK:
    """Build the asynchronous document service around caller-provided ports."""
    return AsyncDocumentManagementSDK(create_sdk_from_components(
        metadata_store=metadata_store,
        object_store=object_store,
        logger=logger,
        id_generator=id_generator,
        max_file_size=max_file_size,
        operation_store=operation_store,
        metadata_validator=metadata_validator,
        metadata_max_serialized_bytes=metadata_max_serialized_bytes,
        metadata_max_depth=metadata_max_depth,
        recovery_audit_hook=recovery_audit_hook,
        operation_observer=operation_observer,
        access_policy=access_policy,
    ))


def create_sdk_from_clients(
    *,
    engine: Engine,
    minio_client: Any,
    bucket_name: str,
    logger: logging.Logger | None = None,
    id_generator: DocumentIdGenerator | None = None,
    max_file_size: int | None = None,
    operation_store: UploadOperationStore | None = None,
    metadata_validator: MetadataValidator | None = None,
    metadata_max_serialized_bytes: int = 16_384,
    metadata_max_depth: int = 8,
    recovery_audit_hook: Callable[[RecoveryAuditEvent], object] | None = None,
    operation_observer: OperationObserver | None = None,
    access_policy: DocumentAccessPolicy | None = None,
) -> DefaultDocumentManagementSDK:
    """Build a synchronous SDK around caller-owned infrastructure clients."""
    return DocumentManagementSDKFactory(
        engine=engine,
        minio_client=minio_client,
        bucket_name=bucket_name,
        logger=logger,
        id_generator=id_generator,
        max_file_size=max_file_size,
        operation_store=operation_store,
        metadata_validator=metadata_validator,
        metadata_max_serialized_bytes=metadata_max_serialized_bytes,
        metadata_max_depth=metadata_max_depth,
        recovery_audit_hook=recovery_audit_hook,
        operation_observer=operation_observer,
        access_policy=access_policy,
    ).create()


def create_async_sdk_from_clients(
    *,
    engine: Engine,
    minio_client: Any,
    bucket_name: str,
    logger: logging.Logger | None = None,
    id_generator: DocumentIdGenerator | None = None,
    max_file_size: int | None = None,
    operation_store: UploadOperationStore | None = None,
    metadata_validator: MetadataValidator | None = None,
    metadata_max_serialized_bytes: int = 16_384,
    metadata_max_depth: int = 8,
    recovery_audit_hook: Callable[[RecoveryAuditEvent], object] | None = None,
    operation_observer: OperationObserver | None = None,
    access_policy: DocumentAccessPolicy | None = None,
) -> AsyncDocumentManagementSDK:
    """Build an asynchronous SDK around caller-owned infrastructure clients."""
    return DocumentManagementSDKFactory(
        engine=engine,
        minio_client=minio_client,
        bucket_name=bucket_name,
        logger=logger,
        id_generator=id_generator,
        max_file_size=max_file_size,
        operation_store=operation_store,
        metadata_validator=metadata_validator,
        metadata_max_serialized_bytes=metadata_max_serialized_bytes,
        metadata_max_depth=metadata_max_depth,
        recovery_audit_hook=recovery_audit_hook,
        operation_observer=operation_observer,
        access_policy=access_policy,
    ).create_async()
