from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from docmesh_py_core import ServiceBundle, ServiceRuntime

from dms.domain.interfaces import MetadataStore, ObjectStore, UploadOperationStore
from dms.infrastructure.metadata.operations import SqlAlchemyUploadOperationStore
from dms.infrastructure.metadata.postgres import PostgresMetadataStore
from dms.infrastructure.metadata.sqlite import SqliteMetadataStore
from dms.infrastructure.storage.minio import MinioObjectStore
from dms.sdk.async_bridge import run_coroutine
from dms.sdk.errors import ConfigurationError
from dms.sdk.implementation import DefaultDocumentManagementSDK, DocumentIdGenerator
from dms.sdk.metadata import DefaultMetadataPolicy, MetadataValidator
from dms.sdk.types import RecoveryAuditEvent


def create_metadata_stores(bundle: ServiceBundle | ServiceRuntime) -> tuple[MetadataStore, UploadOperationStore]:
    selected = {_service_name(service) for service in bundle.selected_services}
    if "postgres" in selected:
        service_name, store_type = "postgres", PostgresMetadataStore
    elif "sqlite" in selected:
        service_name, store_type = "sqlite", SqliteMetadataStore
    else:
        raise ConfigurationError("PostgreSQL or SQLite service is required to build the DMS SDK")
    client = _client_value(bundle.get_client(service_name))
    return store_type(client), SqlAlchemyUploadOperationStore(client)


def create_object_store(bundle: ServiceBundle | ServiceRuntime) -> ObjectStore:
    selected = {_service_name(service) for service in bundle.selected_services}
    if "minio" not in selected or bundle.configs.minio is None:
        raise ConfigurationError("MinIO service is required to build the DMS SDK")
    bucket_name = bundle.configs.minio.bucket
    if not bucket_name:
        raise ConfigurationError("MINIO_BUCKET is required to build the DMS SDK")
    return MinioObjectStore(client=_client_value(bundle.get_client("minio")), bucket_name=bucket_name)


def _service_name(service: object) -> str:
    value = getattr(service, "value", service)
    return str(value)


def _client_value(client: object) -> Any:
    unwrap = getattr(client, "unwrap", None)
    return unwrap() if callable(unwrap) else client


def create_sdk_from_bundle(
    bundle: ServiceBundle | ServiceRuntime,
    *,
    logger: logging.Logger | None,
    id_generator: DocumentIdGenerator | None = None,
    metadata_validator: MetadataValidator | None,
    metadata_max_serialized_bytes: int,
    metadata_max_depth: int,
    recovery_audit_hook: Callable[[RecoveryAuditEvent], object] | None,
    metadata_store_factory: Callable[[ServiceBundle | ServiceRuntime], tuple[MetadataStore, UploadOperationStore]] = create_metadata_stores,
    object_store_factory: Callable[[ServiceBundle | ServiceRuntime], ObjectStore] = create_object_store,
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
            service_checks=_sync_checks(bundle),
            close_callbacks=[_sync_close(bundle)],
            metadata_validator=metadata_validator or DefaultMetadataPolicy(
                max_serialized_bytes=metadata_max_serialized_bytes,
                max_depth=metadata_max_depth,
            ),
            recovery_audit_hook=recovery_audit_hook,
        )
    except Exception as exc:
        try:
            _sync_close(bundle)()
        except Exception as close_exc:
            exc.add_note(f"Failed to close service bundle after DMS assembly failure: {close_exc}")
        raise


def _sync_checks(bundle: ServiceBundle | ServiceRuntime) -> dict[str, Callable[[], object]]:
    if isinstance(bundle, ServiceRuntime):
        return {
            service.value: check
            for service, check in bundle.checks.items()
        }
    return bundle.checks


def _sync_close(bundle: ServiceBundle | ServiceRuntime) -> Callable[[], object]:
    if isinstance(bundle, ServiceRuntime):
        return lambda: run_coroutine(bundle.close())
    return bundle.close
