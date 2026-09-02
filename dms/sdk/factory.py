from __future__ import annotations

import inspect
import logging
from collections.abc import Callable
from dataclasses import dataclass

from minio import Minio
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine

from dms.domain.interfaces import MetadataStore, ObjectStore, UploadOperationStore
from dms.infrastructure.metadata.async_operations import (
    AsyncSqlAlchemyUploadOperationStore,
)
from dms.infrastructure.metadata.async_postgres import AsyncPostgresMetadataStore
from dms.infrastructure.metadata.async_sqlite import AsyncSqliteMetadataStore
from dms.infrastructure.metadata.operations import SqlAlchemyUploadOperationStore
from dms.infrastructure.metadata.postgres import PostgresMetadataStore
from dms.infrastructure.metadata.sqlite import SqliteMetadataStore
from dms.infrastructure.storage.minio import (
    AsyncMinioClient,
    AsyncMinioObjectStore,
    MinioObjectStore,
)
from dms.sdk.async_sdk import AsyncDocumentManagementSDK
from dms.sdk.contracts import OperationObserver
from dms.sdk.errors import ConfigurationError
from dms.sdk.implementation import DefaultDocumentManagementSDK
from dms.sdk.types import RecoveryAuditEvent


def _validate_assembly_options(
    *,
    max_file_size: int | None,
) -> None:
    if max_file_size is not None and max_file_size <= 0:
        raise ValueError("max_file_size must be positive")


def _validate_async_minio_client(client: object) -> None:
    required_coroutines = (
        "bucket_exists",
        "make_bucket",
        "put_object",
        "stat_object",
        "get_object",
        "remove_object",
    )
    if any(
        not inspect.iscoroutinefunction(getattr(client, method_name, None))
        for method_name in required_coroutines
    ) or not callable(getattr(client, "list_objects", None)):
        raise ConfigurationError(
            "AsyncDocumentManagementSDKFactory requires an async MinIO client"
        )


def _build_sdk(
    *,
    metadata_store: MetadataStore,
    object_store: ObjectStore,
    logger: logging.Logger | None = None,
    max_file_size: int | None = None,
    operation_store: UploadOperationStore | None = None,
    recovery_audit_hook: Callable[[RecoveryAuditEvent], object] | None = None,
    operation_observer: OperationObserver | None = None,
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
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class AsyncDocumentManagementSDKFactory:
    """Create a native async SDK from an ``AsyncEngine`` and async MinIO client."""

    engine: AsyncEngine
    minio_client: AsyncMinioClient
    bucket_name: str
    logger: logging.Logger | None = None
    max_file_size: int | None = None
    recovery_audit_hook: Callable[[RecoveryAuditEvent], object] | None = None
    operation_observer: OperationObserver | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.engine, AsyncEngine):
            raise ConfigurationError(
                "AsyncDocumentManagementSDKFactory requires an AsyncEngine"
            )
        _validate_async_minio_client(self.minio_client)
        _validate_assembly_options(max_file_size=self.max_file_size)
        if not self.bucket_name.strip():
            raise ConfigurationError("bucket_name is required to build the DMS SDK")

    def create(self) -> AsyncDocumentManagementSDK:
        """Build a lazy native async SDK; initialization occurs on first await."""
        dialect = self.engine.dialect.name
        if dialect == "postgresql":
            metadata_store = AsyncPostgresMetadataStore(self.engine)
        elif dialect == "sqlite":
            metadata_store = AsyncSqliteMetadataStore(self.engine)
        else:
            raise ConfigurationError(
                f"Unsupported SQLAlchemy dialect for DMS: {dialect}"
            )
        operation_store = AsyncSqlAlchemyUploadOperationStore(self.engine)
        object_store = AsyncMinioObjectStore(
            client=self.minio_client,
            bucket_name=self.bucket_name,
        )

        async def initialize() -> None:
            await object_store.initialize()
            await metadata_store.initialize()
            await operation_store.initialize()

        sdk = AsyncDocumentManagementSDK.from_async_components(
            metadata_store=metadata_store,
            object_store=object_store,
            operation_store=operation_store,
            logger=self.logger,
            max_file_size=self.max_file_size,
            recovery_audit_hook=self.recovery_audit_hook,
            operation_observer=self.operation_observer,
            initialize=initialize,
        )
        return sdk

    async def create_async(self) -> AsyncDocumentManagementSDK:
        """Build and initialize the native async SDK before returning it."""
        return await self.create().ready()
