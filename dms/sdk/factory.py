from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from minio import Minio
from sqlalchemy.engine import Engine

from dms.domain.interfaces import MetadataStore, ObjectStore, UploadOperationStore
from dms.infrastructure.metadata.operations import SqlAlchemyUploadOperationStore
from dms.infrastructure.metadata.postgres import PostgresMetadataStore
from dms.infrastructure.metadata.sqlite import SqliteMetadataStore
from dms.infrastructure.storage.minio import MinioObjectStore
from dms.sdk.async_sdk import AsyncDocumentManagementSDK
from dms.sdk.contracts import DocumentAccessPolicy, OperationObserver
from dms.sdk.errors import ConfigurationError
from dms.sdk.implementation import DefaultDocumentManagementSDK
from dms.sdk.types import RecoveryAuditEvent


def _validate_assembly_options(
    *,
    max_file_size: int | None,
) -> None:
    if max_file_size is not None and max_file_size <= 0:
        raise ValueError("max_file_size must be positive")


def _build_sdk(
    *,
    metadata_store: MetadataStore,
    object_store: ObjectStore,
    logger: logging.Logger | None = None,
    max_file_size: int | None = None,
    operation_store: UploadOperationStore | None = None,
    recovery_audit_hook: Callable[[RecoveryAuditEvent], object] | None = None,
    operation_observer: OperationObserver | None = None,
    access_policy: DocumentAccessPolicy | None = None,
) -> DefaultDocumentManagementSDK:
    """Build an SDK from already-adapted domain storage ports."""
    _validate_assembly_options(
        max_file_size=max_file_size,
    )
    return DefaultDocumentManagementSDK(
        metadata_store=metadata_store,
        object_store=object_store,
        logger=logger,
        max_file_size=max_file_size,
        operation_store=operation_store,
        recovery_audit_hook=recovery_audit_hook,
        access_policy=access_policy,
        operation_observer=operation_observer,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class DocumentManagementSDKFactory:
    """Create the SDK from caller-owned SQLAlchemy and MinIO clients.

    The factory adapts the supplied clients into the SDK's storage ports. It does
    not create or close either client; their lifecycle remains with the caller.
    Class-level convenience entrypoints cover both client-based and already-adapted
    component-based assembly.
    """

    engine: Engine
    minio_client: Minio
    bucket_name: str
    logger: logging.Logger | None = None
    max_file_size: int | None = None
    recovery_audit_hook: Callable[[RecoveryAuditEvent], object] | None = None
    operation_observer: OperationObserver | None = None
    access_policy: DocumentAccessPolicy | None = None

    def __post_init__(self) -> None:
        _validate_assembly_options(
            max_file_size=self.max_file_size,
        )
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

        return _build_sdk(
            metadata_store=metadata_store,
            object_store=MinioObjectStore(
                client=self.minio_client,
                bucket_name=self.bucket_name,
            ),
            logger=self.logger,
            max_file_size=self.max_file_size,
            operation_store=SqlAlchemyUploadOperationStore(self.engine),
            recovery_audit_hook=self.recovery_audit_hook,
            operation_observer=self.operation_observer,
            access_policy=self.access_policy,
        )

    def create_async(self) -> AsyncDocumentManagementSDK:
        """Create an asynchronous facade over a fresh synchronous SDK."""
        return AsyncDocumentManagementSDK(self.create())
