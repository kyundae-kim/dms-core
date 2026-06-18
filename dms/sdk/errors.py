from __future__ import annotations


class DmsError(Exception):
    """Base error for the DMS SDK."""


class ConfigurationError(DmsError):
    """Raised when SDK configuration is invalid."""


class ValidationError(DmsError):
    """Raised when a request payload is invalid."""


class AuthenticationError(DmsError):
    """Raised when token acquisition or validation fails."""


class DocumentNotFoundError(DmsError):
    """Raised when a requested document does not exist."""


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
