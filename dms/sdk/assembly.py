from __future__ import annotations

import logging
from collections.abc import Callable

from docmesh_py_core import ServiceBundle

from dms.domain.interfaces import MetadataStore, ObjectStore, UploadOperationStore
from dms.infrastructure.metadata.operations import SqlAlchemyUploadOperationStore
from dms.infrastructure.metadata.postgres import PostgresMetadataStore
from dms.infrastructure.metadata.sqlite import SqliteMetadataStore
from dms.infrastructure.storage.minio import MinioObjectStore
from dms.sdk.errors import ConfigurationError
from dms.sdk.implementation import DefaultDocumentManagementSDK, DocumentIdGenerator
from dms.sdk.metadata import DefaultMetadataPolicy, MetadataValidator
from dms.sdk.types import RecoveryAuditEvent


def create_metadata_stores(bundle: ServiceBundle) -> tuple[MetadataStore, UploadOperationStore]:
    selected = bundle.selected_services
    if "postgres" in selected:
        service_name, store_type = "postgres", PostgresMetadataStore
    elif "sqlite" in selected:
        service_name, store_type = "sqlite", SqliteMetadataStore
    else:
        raise ConfigurationError("PostgreSQL or SQLite service is required to build the DMS SDK")
    client = bundle.get_client(service_name).unwrap()
    return store_type(client), SqlAlchemyUploadOperationStore(client)


def create_object_store(bundle: ServiceBundle) -> ObjectStore:
    if "minio" not in bundle.selected_services or bundle.configs.minio is None:
        raise ConfigurationError("MinIO service is required to build the DMS SDK")
    bucket_name = bundle.configs.minio.bucket
    if not bucket_name:
        raise ConfigurationError("MINIO_BUCKET is required to build the DMS SDK")
    return MinioObjectStore(client=bundle.get_client("minio").unwrap(), bucket_name=bucket_name)


def create_sdk_from_bundle(
    bundle: ServiceBundle,
    *,
    logger: logging.Logger | None,
    id_generator: DocumentIdGenerator | None = None,
    metadata_validator: MetadataValidator | None,
    metadata_max_serialized_bytes: int,
    metadata_max_depth: int,
    recovery_audit_hook: Callable[[RecoveryAuditEvent], object] | None,
    metadata_store_factory: Callable[[ServiceBundle], tuple[MetadataStore, UploadOperationStore]] = create_metadata_stores,
    object_store_factory: Callable[[ServiceBundle], ObjectStore] = create_object_store,
) -> DefaultDocumentManagementSDK:
    try:
        metadata_store, operation_store = metadata_store_factory(bundle)
        object_store = object_store_factory(bundle)
        return DefaultDocumentManagementSDK(
            metadata_store=metadata_store,
            object_store=object_store,
            operation_store=operation_store,
            logger=logger,
            id_generator=id_generator,
            service_checks=bundle.checks,
            close_callbacks=[bundle.close],
            metadata_validator=metadata_validator or DefaultMetadataPolicy(
                max_serialized_bytes=metadata_max_serialized_bytes,
                max_depth=metadata_max_depth,
            ),
            recovery_audit_hook=recovery_audit_hook,
        )
    except Exception as exc:
        try:
            bundle.close()
        except Exception as close_exc:
            exc.add_note(f"Failed to close service bundle after DMS assembly failure: {close_exc}")
        raise
