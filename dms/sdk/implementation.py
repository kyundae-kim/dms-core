from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from hashlib import sha256
from time import perf_counter
from uuid import uuid4

from docmesh_py_core import (
    AccessTokenResult,
    AuthenticatedUser,
    KeycloakTokenAuthenticationError,
    KeycloakTokenConfigurationError,
    KeycloakTokenError,
    TokenValidationError,
)

from dms.domain.interfaces import AuthService, MetadataIdGenerator, MetadataStore, ObjectStore, PutObjectRequest
from dms.domain.models import DocumentMetadata, DocumentStatus
from dms.sdk.client import DocumentManagementSDK
from dms.sdk.errors import (
    AuthenticationError,
    ConfigurationError,
    ConsistencyError,
    DocumentNotFoundError,
    DuplicateDocumentError,
    MetadataStoreError,
    StorageError,
    ValidationError,
)
from dms.sdk.types import (
    DeleteDocumentResult,
    DocumentContent,
    HealthStatus,
    ServiceHealth,
    UploadDocumentRequest,
    UploadDocumentResult,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class UuidDocumentIdGenerator(MetadataIdGenerator):
    def new_document_id(self) -> str:
        return str(uuid4())


class DefaultDocumentManagementSDK(DocumentManagementSDK):
    def __init__(
        self,
        *,
        metadata_store: MetadataStore,
        object_store: ObjectStore,
        auth_service: AuthService | None = None,
        id_generator: MetadataIdGenerator | None = None,
        service_checks: Mapping[str, Callable[[], object]] | None = None,
        close_callbacks: Iterable[Callable[[], object]] | None = None,
    ) -> None:
        self._metadata_store = metadata_store
        self._object_store = object_store
        self._auth_service = auth_service
        self._id_generator = id_generator or UuidDocumentIdGenerator()
        self._service_checks = dict(service_checks or {})
        self._close_callbacks = list(close_callbacks or [])

    def fetch_access_token(self, *, scope: str | None = None) -> AccessTokenResult:
        auth_service = self._require_auth_service()
        try:
            return auth_service.fetch_access_token(scope=scope)
        except KeycloakTokenConfigurationError as exc:
            raise ConfigurationError(str(exc)) from exc
        except (KeycloakTokenAuthenticationError, KeycloakTokenError) as exc:
            raise AuthenticationError(str(exc)) from exc

    def get_authenticated_user(self, token: str) -> AuthenticatedUser:
        if not token.strip():
            raise ValidationError("token must not be empty")

        auth_service = self._require_auth_service()
        try:
            return auth_service.extract_user_info(token)
        except TokenValidationError as exc:
            raise AuthenticationError(str(exc)) from exc

    def upload_document(self, request: UploadDocumentRequest) -> UploadDocumentResult:
        self._validate_upload_request(request)
        document_id = request.document_id or self._id_generator.new_document_id()
        if self._metadata_store.exists(document_id):
            raise DuplicateDocumentError(f"Document already exists: {document_id}")

        checksum = request.checksum or sha256(request.content).hexdigest()
        storage_key = self._build_storage_key(document_id=document_id, filename=request.filename)
        put_request = PutObjectRequest(
            document_id=document_id,
            storage_key=storage_key,
            content=request.content,
            content_type=request.content_type,
            filename=request.filename,
            checksum=checksum,
            metadata=dict(request.metadata),
        )

        try:
            stored_key = self._object_store.put_object(put_request)
        except Exception as exc:  # pragma: no cover - protocol adapter boundary
            raise StorageError(f"Failed to store document content for {document_id}") from exc

        now = _utcnow()
        metadata = DocumentMetadata(
            document_id=document_id,
            original_filename=request.filename,
            content_type=request.content_type,
            file_size=len(request.content),
            storage_key=stored_key,
            checksum=checksum,
            status=DocumentStatus.AVAILABLE,
            created_at=now,
            updated_at=now,
            created_by=request.created_by,
            extra_metadata=dict(request.metadata),
        )

        try:
            saved_metadata = self._metadata_store.save_metadata(metadata)
        except Exception as exc:
            try:
                self._object_store.delete_object(document_id, stored_key)
            except Exception as cleanup_exc:  # pragma: no cover - rare double-failure boundary
                raise ConsistencyError(
                    f"Failed to persist metadata and failed to clean up content for {document_id}"
                ) from cleanup_exc
            raise ConsistencyError(f"Failed to persist metadata for {document_id}; object storage was rolled back") from exc

        return UploadDocumentResult(
            document_id=document_id,
            storage_key=stored_key,
            metadata=saved_metadata,
            created=True,
        )

    def get_document_metadata(self, document_id: str) -> DocumentMetadata:
        try:
            return self._metadata_store.get_metadata(document_id)
        except LookupError as exc:
            raise DocumentNotFoundError(f"Document not found: {document_id}") from exc
        except Exception as exc:
            raise MetadataStoreError(f"Failed to load metadata for {document_id}") from exc

    def get_document_content(self, document_id: str) -> DocumentContent:
        metadata = self.get_document_metadata(document_id)
        try:
            stored = self._object_store.get_object(document_id, metadata.storage_key)
        except Exception as exc:
            raise ConsistencyError(
                f"Document metadata exists but object content is missing for {document_id}"
            ) from exc

        return DocumentContent(
            document_id=document_id,
            content=stored.content,
            content_type=stored.content_type,
            filename=stored.filename,
            size=stored.size,
            checksum=stored.checksum,
        )

    def delete_document(
        self,
        document_id: str,
        *,
        hard_delete: bool = False,
    ) -> DeleteDocumentResult:
        metadata = self.get_document_metadata(document_id)
        try:
            self._object_store.delete_object(document_id, metadata.storage_key)
        except Exception as exc:
            raise StorageError(f"Failed to delete document content for {document_id}") from exc

        if hard_delete:
            try:
                self._metadata_store.hard_delete(document_id)
            except Exception as exc:
                raise ConsistencyError(
                    f"Document content was deleted but metadata could not be hard deleted for {document_id}"
                ) from exc
            return DeleteDocumentResult(
                document_id=document_id,
                deleted=True,
                hard_deleted=True,
                status=DocumentStatus.DELETED,
            )

        try:
            deleted_metadata = self._metadata_store.mark_deleted(document_id)
        except Exception as exc:
            raise ConsistencyError(
                f"Document content was deleted but metadata could not be marked deleted for {document_id}"
            ) from exc
        return DeleteDocumentResult(
            document_id=document_id,
            deleted=True,
            hard_deleted=False,
            status=deleted_metadata.status,
        )

    def check_health(self) -> HealthStatus:
        services: list[ServiceHealth] = []
        overall_ok = True
        for name, check in self._service_checks.items():
            started = perf_counter()
            try:
                check()
            except Exception as exc:
                overall_ok = False
                services.append(
                    ServiceHealth(
                        service=name,
                        ok=False,
                        latency_ms=(perf_counter() - started) * 1000,
                        error=str(exc),
                    )
                )
            else:
                services.append(
                    ServiceHealth(
                        service=name,
                        ok=True,
                        latency_ms=(perf_counter() - started) * 1000,
                        error=None,
                    )
                )

        return HealthStatus(ok=overall_ok, services=services, checked_at=_utcnow())

    def close(self) -> None:
        errors: list[Exception] = []
        for callback in self._close_callbacks:
            try:
                callback()
            except Exception as exc:  # pragma: no cover - cleanup boundary
                errors.append(exc)
        if errors:
            raise MetadataStoreError("One or more cleanup callbacks failed") from errors[0]

    def _require_auth_service(self) -> AuthService:
        if self._auth_service is None:
            raise ConfigurationError("Authentication support is not configured for this SDK instance")
        return self._auth_service

    @classmethod
    def _validate_upload_request(cls, request: UploadDocumentRequest) -> None:
        if not request.content:
            raise ValidationError("Document content must not be empty")
        if not request.filename.strip():
            raise ValidationError("filename must not be empty")
        if not request.content_type.strip():
            raise ValidationError("content_type must not be empty")
        if cls._sanitize_filename(request.filename) in {".", ""}:
            raise ValidationError("filename must not normalize to '.' or empty")

    @classmethod
    def _build_storage_key(cls, *, document_id: str, filename: str) -> str:
        safe_filename = cls._sanitize_filename(filename)
        return f"documents/{document_id}/{safe_filename}"

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        return filename.strip().replace('..', '.').replace('/', '-').replace('\\', '-')
