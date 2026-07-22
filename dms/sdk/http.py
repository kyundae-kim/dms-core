from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from dms.sdk.errors import (
    ConfigurationError,
    ConsistencyError,
    DmsError,
    DocumentDeletedError,
    DocumentNotFoundError,
    DuplicateDocumentError,
    HealthCheckFailedError,
    IdempotencyConflictError,
    IdempotencyInProgressError,
    MetadataStoreError,
    PayloadTooLargeError,
    StorageError,
    UploadOperationNotFoundError,
    ValidationError,
)


@dataclass(frozen=True, slots=True)
class RecommendedHttpError:
    status: int
    body: dict[str, object]


_STATUS_BY_ERROR = MappingProxyType({
    PayloadTooLargeError: 413,
    ValidationError: 400,
    DocumentNotFoundError: 404,
    UploadOperationNotFoundError: 404,
    DuplicateDocumentError: 409,
    IdempotencyConflictError: 409,
    DocumentDeletedError: 409,
    IdempotencyInProgressError: 425,
    StorageError: 503,
    MetadataStoreError: 503,
    HealthCheckFailedError: 503,
    ConfigurationError: 500,
    ConsistencyError: 500,
    DmsError: 500,
})


def _public_message(error: DmsError) -> str:
    if isinstance(error, ConfigurationError):
        return "The DMS integration is not configured correctly"
    if isinstance(error, (StorageError, MetadataStoreError)):
        return "A storage dependency failed"
    if isinstance(error, HealthCheckFailedError):
        return "A required dependency is unavailable"
    if isinstance(error, ConsistencyError):
        return "Document storage is inconsistent and requires inspection"
    return str(error)


def recommended_http_error(error: DmsError) -> RecommendedHttpError:
    """Return secret-safe transport guidance without coupling exceptions to HTTP."""
    status = next(
        value for error_type, value in _STATUS_BY_ERROR.items()
        if isinstance(error, error_type)
    )
    return RecommendedHttpError(status=status, body={
        "code": error.code,
        "category": error.category,
        "retryable": error.retryable,
        "message": _public_message(error),
    })
