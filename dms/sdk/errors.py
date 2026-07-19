from __future__ import annotations

from typing import Any


class DmsError(Exception):
    """Base error for the DMS SDK."""

    code = "dms_error"
    retryable = False

    def __init__(self, message: str, *, document_id: str | None = None,
                 diagnosis: Any | None = None) -> None:
        super().__init__(message)
        self.document_id = document_id
        self.diagnosis = diagnosis


class ConfigurationError(DmsError):
    """Raised when SDK configuration is invalid."""

    code = "configuration_invalid"


class ValidationError(DmsError):
    """Raised when a request payload is invalid."""


class DocumentNotFoundError(DmsError):
    """Raised when a requested document does not exist."""

    code = "document_not_found"


class DocumentDeletedError(DmsError):
    """Raised when content is requested for a logically deleted document."""

    code = "document_deleted"


class DuplicateDocumentError(DmsError):
    """Raised when a document identifier is already present."""


class StorageError(DmsError):
    """Raised when object storage access fails."""


class MetadataStoreError(DmsError):
    """Raised when metadata persistence fails."""


class ConsistencyError(DmsError):
    """Raised when storage and metadata fall out of sync."""


class HealthCheckFailedError(DmsError):
    """Raised when a required health check fails."""

    code = "startup_health_failed"
    retryable = True

    def __init__(self, message: str, *, service: str | None = None,
                 reason: str | None = None) -> None:
        super().__init__(message)
        self.service = service
        self.reason = reason


class IdempotencyConflictError(DmsError):
    """The key was previously used for a different upload request."""


class IdempotencyInProgressError(DmsError):
    """Retryable: the keyed upload is still pending."""


class UploadOperationNotFoundError(DmsError):
    """Raised when no upload operation exists for the exact scope and key."""
