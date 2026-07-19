from __future__ import annotations

from typing import Literal

from docmesh_py_core import ConfigError, ServiceConfigs, require_minio_bucket, validate_runtime_security

from dms.sdk.errors import ConfigurationError


def validate_dms_service_configs(configs: ServiceConfigs) -> Literal["postgres", "sqlite"]:
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
