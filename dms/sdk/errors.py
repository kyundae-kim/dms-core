from __future__ import annotations

from typing import Any


class DmsError(Exception):
    """Base error for the DMS SDK."""

    code = "dms_error"
    category = "internal"
    retryable = False

    def __init__(self, message: str, *, document_id: str | None = None,
                 diagnosis: Any | None = None) -> None:
        super().__init__(message)
        self.document_id = document_id
        self.diagnosis = diagnosis


class ConfigurationError(DmsError):
    """Raised when SDK configuration is invalid."""

    code = "configuration_invalid"
    category = "configuration"


class ValidationError(DmsError):
    """Raised when a request payload is invalid."""

    code = "validation_invalid"
    category = "validation"


class PayloadTooLargeError(ValidationError):
    """Raised when document content exceeds a configured or requested bound."""

    code = "document_too_large"
    category = "validation"


class DocumentNotFoundError(DmsError):
    """Raised when a requested document does not exist."""

    code = "document_not_found"
    category = "not_found"


class DocumentDeletedError(DmsError):
    """Raised when content is requested for a logically deleted document."""

    code = "document_deleted"
    category = "unavailable"


class DuplicateDocumentError(DmsError):
    """Raised when a document identifier is already present."""

    code = "document_duplicate"
    category = "conflict"


class StorageError(DmsError):
    """Raised when object storage access fails."""

    code = "object_storage_failed"
    category = "storage"
    retryable = True


class MetadataStoreError(DmsError):
    """Raised when metadata persistence fails."""

    code = "metadata_store_failed"
    category = "storage"
    retryable = True


class ConsistencyError(DmsError):
    """Raised when storage and metadata fall out of sync."""

    code = "document_inconsistent"
    category = "consistency"


class HealthCheckFailedError(DmsError):
    """Raised when a required health check fails."""

    code = "startup_health_failed"
    category = "health"
    retryable = True

    def __init__(self, message: str, *, service: str | None = None,
                 reason: str | None = None) -> None:
        super().__init__(message)
        self.service = service
        self.reason = reason


class IdempotencyConflictError(DmsError):
    """The key was previously used for a different upload request."""

    code = "idempotency_conflict"
    category = "conflict"


class IdempotencyInProgressError(DmsError):
    """Retryable: the keyed upload is still pending."""

    code = "idempotency_in_progress"
    category = "conflict"
    retryable = True


class UploadOperationNotFoundError(DmsError):
    """Raised when no upload operation exists for the exact scope and key."""

    code = "upload_operation_not_found"
    category = "not_found"
