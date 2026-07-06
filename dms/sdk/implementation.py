from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from time import perf_counter
from typing import TypeAlias
from uuid import uuid4

from dms.domain.interfaces import MetadataStore, ObjectStore, PutObjectRequest
from dms.domain.models import DocumentMetadata, DocumentStatus
from dms.sdk.errors import (
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
    DocumentContentStream,
    HealthStatus,
    ServiceHealth,
    UploadDocumentRequest,
    UploadDocumentResult,
)


DocumentIdGenerator: TypeAlias = Callable[[], str]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _new_document_id() -> str:
    return str(uuid4())


class DefaultDocumentManagementSDK:
    def __init__(
        self,
        *,
        metadata_store: MetadataStore,
        object_store: ObjectStore,
        logger: logging.Logger | None = None,
        id_generator: DocumentIdGenerator | None = None,
        service_checks: Mapping[str, Callable[[], object]] | None = None,
        close_callbacks: Iterable[Callable[[], object]] | None = None,
    ) -> None:
        self._metadata_store = metadata_store
        self._object_store = object_store
        self._logger = logger or logging.getLogger("dms.sdk")
        self._id_generator = id_generator or _new_document_id
        self._service_checks = dict(service_checks or {})
        self._close_callbacks = list(close_callbacks or [])

    def upload_document(self, request: UploadDocumentRequest) -> UploadDocumentResult:
        started = perf_counter()
        self._validate_upload_request(request)
        document_id = request.document_id or self._id_generator()
        if self._metadata_store.exists(document_id):
            self._log_warning("document.upload.duplicate", document_id=document_id, filename=request.filename)
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
            self._log_exception(
                "document.upload.storage_error",
                exc,
                document_id=document_id,
                filename=request.filename,
                duration_ms=(perf_counter() - started) * 1000,
            )
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
                self._log_exception(
                    "document.upload.rollback_failed",
                    cleanup_exc,
                    document_id=document_id,
                    storage_key=stored_key,
                    duration_ms=(perf_counter() - started) * 1000,
                )
                raise ConsistencyError(
                    f"Failed to persist metadata and failed to clean up content for {document_id}"
                ) from cleanup_exc
            self._log_exception(
                "document.upload.metadata_error",
                exc,
                document_id=document_id,
                storage_key=stored_key,
                duration_ms=(perf_counter() - started) * 1000,
            )
            raise ConsistencyError(f"Failed to persist metadata for {document_id}; object storage was rolled back") from exc

        self._log_info(
            "document.upload.succeeded",
            document_id=document_id,
            storage_key=stored_key,
            content_type=request.content_type,
            file_size=len(request.content),
            duration_ms=(perf_counter() - started) * 1000,
        )
        return UploadDocumentResult(
            document_id=document_id,
            storage_key=stored_key,
            metadata=saved_metadata,
            created=True,
        )

    def get_document_metadata(self, document_id: str) -> DocumentMetadata:
        try:
            metadata = self._metadata_store.get_metadata(document_id)
        except LookupError as exc:
            self._log_warning("document.metadata.not_found", document_id=document_id)
            raise DocumentNotFoundError(f"Document not found: {document_id}") from exc
        except Exception as exc:
            self._log_exception("document.metadata.backend_error", exc, document_id=document_id)
            raise MetadataStoreError(f"Failed to load metadata for {document_id}") from exc
        self._log_info(
            "document.metadata.succeeded",
            document_id=document_id,
            status=metadata.status.value,
        )
        return metadata

    def get_document_content(self, document_id: str) -> DocumentContent:
        started = perf_counter()
        metadata = self.get_document_metadata(document_id)
        try:
            stored = self._object_store.get_object(document_id, metadata.storage_key)
        except Exception as exc:
            self._log_exception(
                "document.content.missing_object",
                exc,
                document_id=document_id,
                storage_key=metadata.storage_key,
                duration_ms=(perf_counter() - started) * 1000,
            )
            raise ConsistencyError(
                f"Document metadata exists but object content is missing for {document_id}"
            ) from exc

        self._log_info(
            "document.content.succeeded",
            document_id=document_id,
            storage_key=metadata.storage_key,
            file_size=stored.size,
            duration_ms=(perf_counter() - started) * 1000,
        )
        return DocumentContent(
            document_id=document_id,
            content=stored.content,
            content_type=stored.content_type,
            filename=stored.filename,
            size=stored.size,
            checksum=stored.checksum,
        )

    def get_document_content_stream(
        self,
        document_id: str,
        *,
        chunk_size: int = 65536,
    ) -> DocumentContentStream:
        if chunk_size <= 0:
            raise ValidationError("chunk_size must be positive")

        started = perf_counter()
        metadata = self.get_document_metadata(document_id)
        try:
            stored_stream = self._object_store.get_object_stream(document_id, metadata.storage_key)
        except Exception as exc:
            self._log_exception(
                "document.content_stream.missing_object",
                exc,
                document_id=document_id,
                storage_key=metadata.storage_key,
                duration_ms=(perf_counter() - started) * 1000,
            )
            raise ConsistencyError(
                f"Document metadata exists but object content is missing for {document_id}"
            ) from exc

        def close_stream() -> None:
            if hasattr(stored_stream.stream, "close"):
                stored_stream.stream.close()
            if hasattr(stored_stream.stream, "release_conn"):
                stored_stream.stream.release_conn()

        self._log_info(
            "document.content_stream.succeeded",
            document_id=document_id,
            storage_key=metadata.storage_key,
            file_size=stored_stream.size,
            chunk_size=chunk_size,
            duration_ms=(perf_counter() - started) * 1000,
        )
        return DocumentContentStream(
            document_id=document_id,
            stream=stored_stream.stream,
            content_type=stored_stream.content_type,
            filename=stored_stream.filename,
            size=stored_stream.size,
            checksum=stored_stream.checksum,
            chunk_size=chunk_size,
            _close_callback=close_stream,
        )

    def delete_document(
        self,
        document_id: str,
        *,
        hard_delete: bool = False,
    ) -> DeleteDocumentResult:
        started = perf_counter()
        metadata = self.get_document_metadata(document_id)
        deleting_metadata = self._set_document_status(metadata, DocumentStatus.DELETING)

        try:
            self._object_store.delete_object(document_id, metadata.storage_key)
        except Exception as exc:
            self._set_document_status_best_effort(deleting_metadata, DocumentStatus.FAILED)
            self._log_exception(
                "document.delete.storage_error",
                exc,
                document_id=document_id,
                storage_key=metadata.storage_key,
                hard_delete=hard_delete,
                duration_ms=(perf_counter() - started) * 1000,
            )
            raise StorageError(f"Failed to delete document content for {document_id}") from exc

        if hard_delete:
            try:
                self._metadata_store.hard_delete(document_id)
            except Exception as exc:
                self._log_exception(
                    "document.delete.metadata_error",
                    exc,
                    document_id=document_id,
                    storage_key=metadata.storage_key,
                    hard_delete=True,
                    persisted_status=deleting_metadata.status.value,
                    duration_ms=(perf_counter() - started) * 1000,
                )
                raise ConsistencyError(
                    f"Document content was deleted but metadata could not be hard deleted for {document_id}"
                ) from exc
            self._log_info(
                "document.delete.succeeded",
                document_id=document_id,
                hard_delete=True,
                status=DocumentStatus.DELETED.value,
                duration_ms=(perf_counter() - started) * 1000,
            )
            return DeleteDocumentResult(
                document_id=document_id,
                deleted=True,
                hard_deleted=True,
                status=DocumentStatus.DELETED,
            )

        try:
            deleted_metadata = self._metadata_store.mark_deleted(document_id)
        except Exception as exc:
            self._log_exception(
                "document.delete.metadata_error",
                exc,
                document_id=document_id,
                storage_key=metadata.storage_key,
                hard_delete=False,
                persisted_status=deleting_metadata.status.value,
                duration_ms=(perf_counter() - started) * 1000,
            )
            raise ConsistencyError(
                f"Document content was deleted but metadata could not be marked deleted for {document_id}"
            ) from exc
        self._log_info(
            "document.delete.succeeded",
            document_id=document_id,
            hard_delete=False,
            status=deleted_metadata.status.value,
            duration_ms=(perf_counter() - started) * 1000,
        )
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

        health = HealthStatus(ok=overall_ok, services=services, checked_at=_utcnow())
        self._log_info(
            "sdk.health.checked",
            ok=overall_ok,
            service_count=len(services),
            failed_services=[service.service for service in services if not service.ok],
        )
        return health

    def close(self) -> None:
        errors: list[Exception] = []
        for callback in self._close_callbacks:
            try:
                callback()
            except Exception as exc:  # pragma: no cover - cleanup boundary
                errors.append(exc)
        if errors:
            self._log_exception("sdk.close.failed", errors[0], callback_count=len(self._close_callbacks))
            raise MetadataStoreError("One or more cleanup callbacks failed") from errors[0]
        self._log_info("sdk.close.succeeded", callback_count=len(self._close_callbacks))

    def _set_document_status(
        self,
        metadata: DocumentMetadata,
        status: DocumentStatus,
    ) -> DocumentMetadata:
        updated_metadata = replace(
            metadata,
            status=status,
            updated_at=_utcnow(),
            deleted_at=metadata.deleted_at if status != DocumentStatus.DELETED else _utcnow(),
        )
        try:
            return self._metadata_store.save_metadata(updated_metadata)
        except Exception as exc:
            self._log_exception(
                "document.status_update.failed",
                exc,
                document_id=metadata.document_id,
                storage_key=metadata.storage_key,
                target_status=status.value,
            )
            raise MetadataStoreError(
                f"Failed to persist document status '{status.value}' for {metadata.document_id}"
            ) from exc

    def _set_document_status_best_effort(
        self,
        metadata: DocumentMetadata,
        status: DocumentStatus,
    ) -> None:
        try:
            self._set_document_status(metadata, status)
        except MetadataStoreError:
            return

    def _log_info(self, event: str, **context: object) -> None:
        self._logger.info(event, extra=self._build_log_extra(event, context))

    def _log_warning(self, event: str, **context: object) -> None:
        self._logger.warning(event, extra=self._build_log_extra(event, context))

    def _log_exception(self, event: str, exc: Exception, **context: object) -> None:
        self._logger.exception(
            event,
            extra=self._build_log_extra(event, {**context, "error_type": type(exc).__name__}),
        )

    @staticmethod
    def _build_log_extra(event: str, context: Mapping[str, object]) -> dict[str, object]:
        extra: dict[str, object] = {"dms_event": event}
        for key, value in context.items():
            extra[f"dms_{key}"] = value
        return extra

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
