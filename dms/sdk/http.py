from __future__ import annotations

from dataclasses import dataclass, field, replace
from types import MappingProxyType

from dms.sdk.errors import (
    AccessDeniedError,
    ConfigurationError,
    ConsistencyError,
    DataResetError,
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
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ErrorDescriptor:
    """Transport-neutral, public-safe description of one SDK error."""

    code: str
    category: str
    retryable: bool
    message: str
    retry_after_seconds: int | None = None
    external_code: str | None = None

    def __post_init__(self) -> None:
        if self.retry_after_seconds is not None and self.retry_after_seconds < 0:
            raise ValueError("retry_after_seconds must not be negative")
        if self.retry_after_seconds is not None and not self.retryable:
            raise ValueError("retry_after_seconds requires a retryable error")

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "code": self.code,
            "category": self.category,
            "retryable": self.retryable,
            "message": self.message,
        }
        if self.retry_after_seconds is not None:
            value["retry_after_seconds"] = self.retry_after_seconds
        if self.external_code is not None:
            value["external_code"] = self.external_code
        return value


_STATUS_BY_CODE = MappingProxyType({
    AccessDeniedError.code: 403,
    PayloadTooLargeError.code: 413,
    ValidationError.code: 400,
    DocumentNotFoundError.code: 404,
    UploadOperationNotFoundError.code: 404,
    DuplicateDocumentError.code: 409,
    IdempotencyConflictError.code: 409,
    DocumentDeletedError.code: 409,
    IdempotencyInProgressError.code: 425,
    StorageError.code: 503,
    MetadataStoreError.code: 503,
    HealthCheckFailedError.code: 503,
    ConfigurationError.code: 500,
    ConsistencyError.code: 500,
    DataResetError.code: 500,
    DmsError.code: 500,
})


def _public_message(error: DmsError) -> str:
    if isinstance(error, ConfigurationError):
        return "The DMS integration is not configured correctly"
    if isinstance(error, (StorageError, MetadataStoreError)):
        return "A storage dependency failed"
    if isinstance(error, HealthCheckFailedError):
        return "A required dependency is unavailable"
    if isinstance(error, DataResetError):
        return "DMS data reset completed only partially"
    if isinstance(error, ConsistencyError):
        return "Document storage is inconsistent and requires inspection"
    return str(error)


def error_descriptor(
    error: DmsError, *, retry_after_seconds: int | None = None
) -> ErrorDescriptor:
    """Return a stable public description without transport-specific values."""
    return ErrorDescriptor(
        code=error.code,
        category=error.category,
        retryable=error.retryable,
        message=_public_message(error),
        retry_after_seconds=retry_after_seconds,
    )


def merge_error_descriptor(
    descriptor: ErrorDescriptor,
    *,
    message: str | None = None,
    external_code: str | None = None,
    retry_after_seconds: int | None = None,
) -> ErrorDescriptor:
    """Merge host-safe overrides while preserving canonical SDK classification."""
    return replace(
        descriptor,
        message=descriptor.message if message is None else message,
        external_code=descriptor.external_code if external_code is None else external_code,
        retry_after_seconds=(
            descriptor.retry_after_seconds
            if retry_after_seconds is None
            else retry_after_seconds
        ),
    )


def recommended_http_error(error: DmsError | ErrorDescriptor) -> RecommendedHttpError:
    """Return secret-safe transport guidance without coupling exceptions to HTTP."""
    descriptor = error if isinstance(error, ErrorDescriptor) else error_descriptor(error)
    status = _STATUS_BY_CODE.get(descriptor.code, 500)
    body: dict[str, object] = {
        "code": descriptor.code,
        "category": descriptor.category,
        "retryable": descriptor.retryable,
        "message": descriptor.message,
    }
    if descriptor.external_code is not None:
        body["external_code"] = descriptor.external_code
    headers = (
        {"Retry-After": str(descriptor.retry_after_seconds)}
        if descriptor.retry_after_seconds is not None
        else {}
    )
    return RecommendedHttpError(status=status, body=body, headers=headers)
