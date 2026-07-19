from __future__ import annotations

from docmesh_py_core import ConfigError, HealthCheckError, ServiceClientError, ServiceUnavailableError

from dms.sdk.environment import EnvironmentDiagnosis
from dms.sdk.errors import (
    ConfigurationError,
    DmsError,
    HealthCheckFailedError,
    MetadataStoreError,
    StorageError,
)


def translate_assembly_error(
    exc: Exception, *, diagnosis: EnvironmentDiagnosis | None = None
) -> DmsError | None:
    if isinstance(exc, DmsError):
        return exc
    if isinstance(exc, ConfigError):
        return ConfigurationError(str(exc), diagnosis=diagnosis)
    if isinstance(exc, HealthCheckError):
        return HealthCheckFailedError(str(exc), service=exc.service, reason=exc.error)
    if isinstance(exc, (ServiceClientError, ServiceUnavailableError)):
        error_type = StorageError if exc.service == "minio" else MetadataStoreError
        return error_type(str(exc))
    return None
