from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from time import perf_counter

from dms.domain.interfaces import MetadataStore, ObjectStore
from dms.domain.models import DocumentMetadata, DocumentStatus
from dms.sdk.errors import (
    ConsistencyError,
    DocumentDeletedError,
    DocumentNotFoundError,
    MetadataStoreError,
    StorageError,
    ValidationError,
)
from dms.sdk.pagination import decode_cursor, encode_cursor
from dms.sdk.types import (
    DeleteDocumentResult,
    DocumentContent,
    DocumentContentStream,
    DocumentPage,
    PublicDocumentMetadata,
    public_metadata,
)


_MAX_PAGE_LIMIT = 1000
_PUBLIC_EXCLUDED_STATUSES = (DocumentStatus.DELETING, DocumentStatus.DELETED)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class DocumentService:
    """Own document reads, listing, status transitions, and deletion."""

    def __init__(
        self,
        *,
        metadata_store: MetadataStore,
        object_store: ObjectStore,
        logger: logging.Logger,
    ) -> None:
        self._metadata_store = metadata_store
        self._object_store = object_store
        self._logger = logger

    def get_internal_metadata(self, document_id: str) -> DocumentMetadata:
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

    def get_metadata(self, document_id: str) -> PublicDocumentMetadata:
        metadata = self.get_internal_metadata(document_id)
        if metadata.status in _PUBLIC_EXCLUDED_STATUSES:
            raise DocumentNotFoundError(
                f"Document not found: {document_id}", document_id=document_id
            )
        return public_metadata(metadata)

    def list_internal(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
        status: DocumentStatus | None = None,
        excluded_statuses: tuple[DocumentStatus, ...] = (),
    ) -> list[DocumentMetadata]:
        if offset < 0:
            raise ValidationError("offset must not be negative")
        if limit <= 0:
            raise ValidationError("limit must be positive")
        try:
            if excluded_statuses:
                metadata = self._metadata_store.list_metadata(
                    offset=offset,
                    limit=limit,
                    status=status,
                    excluded_statuses=excluded_statuses,
                )
            else:
                metadata = self._metadata_store.list_metadata(
                    offset=offset, limit=limit, status=status
                )
        except Exception as exc:
            self._log_exception(
                "document.list.backend_error",
                exc,
                offset=offset,
                limit=limit,
                status=status.value if status is not None else None,
            )
            raise MetadataStoreError("Failed to list document metadata") from exc
        self._log_info(
            "document.list.succeeded",
            offset=offset,
            limit=limit,
            status=status.value if status is not None else None,
            result_count=len(metadata),
        )
        return metadata

    def list(
        self, *, offset: int, limit: int, status: DocumentStatus | None
    ) -> list[PublicDocumentMetadata]:
        self._validate_public_status(status)
        return [
            public_metadata(item)
            for item in self.list_internal(
                offset=offset,
                limit=limit,
                status=status,
                excluded_statuses=_PUBLIC_EXCLUDED_STATUSES,
            )
        ]

    def list_page(
        self, *, cursor: str | None, limit: int, status: DocumentStatus | None
    ) -> DocumentPage:
        self._validate_public_status(status)
        if limit <= 0 or limit > _MAX_PAGE_LIMIT:
            raise ValidationError("limit must be between 1 and 1000")
        after_created_at: datetime | None = None
        after_document_id: str | None = None
        if cursor is not None:
            after_created_at, after_document_id, cursor_status, cursor_page_size = decode_cursor(cursor)
            requested_status = status.value if status is not None else None
            if cursor_status != requested_status:
                raise ValidationError("cursor status filter does not match the request")
            if cursor_page_size != limit:
                raise ValidationError("cursor page size does not match the request")
        try:
            metadata = self._metadata_store.list_metadata_page(
                after_created_at=after_created_at,
                after_document_id=after_document_id,
                limit=limit + 1,
                status=status,
                excluded_statuses=_PUBLIC_EXCLUDED_STATUSES,
            )
        except Exception as exc:
            raise MetadataStoreError("Failed to list document metadata page") from exc
        has_more = len(metadata) > limit
        items = metadata[:limit]
        next_cursor = None
        if has_more and items:
            last = items[-1]
            next_cursor = encode_cursor(last.created_at, last.document_id, status, limit)
        return DocumentPage(
            items=[public_metadata(item) for item in items],
            next_cursor=next_cursor,
            has_more=has_more,
        )

    def get_content(self, document_id: str) -> DocumentContent:
        started = perf_counter()
        metadata = self.get_internal_metadata(document_id)
        self._ensure_content_readable(metadata)
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

    def get_content_stream(
        self, document_id: str, *, chunk_size: int
    ) -> DocumentContentStream:
        if chunk_size <= 0:
            raise ValidationError("chunk_size must be positive")
        started = perf_counter()
        metadata = self.get_internal_metadata(document_id)
        self._ensure_content_readable(metadata)
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
            release_conn = getattr(stored_stream.stream, "release_conn", None)
            if release_conn is not None:
                release_conn()

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

    def delete(self, document_id: str, *, hard_delete: bool) -> DeleteDocumentResult:
        started = perf_counter()
        metadata = self.get_internal_metadata(document_id)
        deleting_metadata = self.set_status(metadata, DocumentStatus.DELETING)
        try:
            self._object_store.delete_object(document_id, metadata.storage_key)
        except Exception as exc:
            self.set_status_best_effort(deleting_metadata, DocumentStatus.FAILED)
            self._log_exception(
                "document.delete.storage_error",
                exc,
                document_id=document_id,
                storage_key=metadata.storage_key,
                hard_delete=hard_delete,
                duration_ms=(perf_counter() - started) * 1000,
            )
            raise StorageError(f"Failed to delete document content for {document_id}") from exc
        try:
            if hard_delete:
                self._metadata_store.hard_delete(document_id)
                status = DocumentStatus.DELETED
            else:
                status = self._metadata_store.mark_deleted(document_id).status
        except Exception as exc:
            self._log_exception(
                "document.delete.metadata_error",
                exc,
                document_id=document_id,
                storage_key=metadata.storage_key,
                hard_delete=hard_delete,
                persisted_status=deleting_metadata.status.value,
                duration_ms=(perf_counter() - started) * 1000,
            )
            operation = "hard deleted" if hard_delete else "marked deleted"
            raise ConsistencyError(
                f"Document content was deleted but metadata could not be {operation} for {document_id}"
            ) from exc
        self._log_info(
            "document.delete.succeeded",
            document_id=document_id,
            hard_delete=hard_delete,
            status=status.value,
            duration_ms=(perf_counter() - started) * 1000,
        )
        return DeleteDocumentResult(
            document_id=document_id,
            deleted=True,
            hard_deleted=hard_delete,
            status=status,
        )

    def set_status(
        self, metadata: DocumentMetadata, status: DocumentStatus
    ) -> DocumentMetadata:
        updated_metadata = replace(
            metadata,
            status=status,
            updated_at=_utcnow(),
            deleted_at=metadata.deleted_at if status != DocumentStatus.DELETED else _utcnow(),
        )
        try:
            return self._metadata_store.update_metadata(updated_metadata)
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

    def set_status_best_effort(
        self, metadata: DocumentMetadata, status: DocumentStatus
    ) -> None:
        try:
            self.set_status(metadata, status)
        except MetadataStoreError:
            return

    @staticmethod
    def _validate_public_status(status: DocumentStatus | None) -> None:
        if status in _PUBLIC_EXCLUDED_STATUSES:
            raise ValidationError(
                "deleted statuses are not available through public document queries"
            )

    @staticmethod
    def _ensure_content_readable(metadata: DocumentMetadata) -> None:
        if metadata.status in _PUBLIC_EXCLUDED_STATUSES:
            raise DocumentDeletedError(
                f"Document content is unavailable after deletion: {metadata.document_id}",
                document_id=metadata.document_id,
            )

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