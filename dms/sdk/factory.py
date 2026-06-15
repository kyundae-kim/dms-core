from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from dms.domain.interfaces import MetadataIdGenerator, MetadataStore, ObjectStore
from dms.sdk.errors import ConfigurationError
from dms.sdk.implementation import DefaultDocumentManagementSDK


def create_sdk(
    *,
    metadata_store: MetadataStore,
    object_store: ObjectStore,
    id_generator: MetadataIdGenerator | None = None,
    service_checks: Mapping[str, Callable[[], object]] | None = None,
    close_callbacks: Iterable[Callable[[], object]] | None = None,
) -> DefaultDocumentManagementSDK:
    return DefaultDocumentManagementSDK(
        metadata_store=metadata_store,
        object_store=object_store,
        id_generator=id_generator,
        service_checks=service_checks,
        close_callbacks=close_callbacks,
    )


def create_sdk_from_environment(env: Mapping[str, str]) -> DefaultDocumentManagementSDK:
    try:
        from docmesh_py_core import ConfigError, load_settings
    except ImportError as exc:  # pragma: no cover - dependency boundary
        raise ConfigurationError("docmesh-py-core must be installed to load environment settings") from exc

    try:
        load_settings(env)
    except ConfigError as exc:
        raise ConfigurationError(str(exc)) from exc

    raise ConfigurationError(
        "Environment-based SDK assembly requires concrete metadata/object-store adapters and is not configured in this package yet"
    )
