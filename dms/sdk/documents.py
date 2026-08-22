from __future__ import annotations

import base64
import json
import logging
from dataclasses import replace
from datetime import UTC, datetime
from time import perf_counter

from dms.domain.interfaces import AsyncMetadataStore, MetadataStore, ObjectStore
from dms.domain.models import DocumentMetadata, DocumentStatus
from dms.sdk.contracts import _LoggingMixin
from dms.sdk.errors import (
    ConsistencyError,
    DocumentDeletedError,
    DocumentNotFoundError,
    MetadataStoreError,
    StorageError,
    ValidationError,
)
from dms.sdk.types import (
    AsyncDocumentContentStream,
    DeleteDocumentResult,
    DocumentContent,
    DocumentContentStream,
    DocumentPage,
    PublicDocumentMetadata,
    public_metadata,
)

_MAX_PAGE_LIMIT = 1000
_PUBLIC_EXCLUDED_STATUSES = (DocumentStatus.DELETING, DocumentStatus.DELETED)
MAX_CURSOR_LENGTH = 4096


def encode_cursor(
    created_at: datetime,
    document_id: str,
    status: DocumentStatus | None,
    page_size: int,
    user_id: str | None = None,
) -> str:
    if (
        created_at.tzinfo is None
        or created_at.utcoffset() is None
        or not document_id.strip()
        or page_size <= 0
    ):
        raise ValidationError("invalid document list cursor state")
    value: dict[str, object] = {
        "v": 3 if user_id is not None else 2,
        "t": created_at.isoformat(),
        "i": document_id,
        "s": status.value if status is not None else None,
        "p": page_size,
    }
    if user_id is not None:
        if not user_id.strip():
            raise ValidationError("invalid document list cursor user scope")
        value["u"] = user_id
    payload = json.dumps(value, separators=(",", ":")).encode()
    encoded = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    if len(encoded) > MAX_CURSOR_LENGTH:
        raise ValidationError("document list cursor exceeds maximum length")
    return encoded


def decode_cursor(cursor: str) -> tuple[datetime, str, str | None, int, str | None]:
    try:
        if not isinstance(cursor, str) or not cursor or len(cursor) > MAX_CURSOR_LENGTH:
            raise ValueError
        payload = base64.b64decode(
            cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True
        )
        value = json.loads(payload)
        if not isinstance(value, dict):
            raise ValueError
        version = value.get("v")
        if type(version) is not int or version not in {2, 3}:
            raise ValueError
        expected_keys = {"v", "t", "i", "s", "p"}
        if version == 3:
            expected_keys.add("u")
        if set(value) != expected_keys:
            raise ValueError
        if (
            not isinstance(value["t"], str)
            or not isinstance(value["i"], str)
            or not value["i"].strip()
        ):
            raise ValueError
        if value["s"] is not None and (
            not isinstance(value["s"], str)
            or value["s"] not in {status.value for status in DocumentStatus}
        ):
            raise ValueError
        if type(value["p"]) is not int or value["p"] <= 0:
            raise ValueError
        user_id = value.get("u")
        if version == 3 and (
            not isinstance(user_id, str) or not user_id.strip()
        ):
            raise ValueError
        created_at = datetime.fromisoformat(value["t"])
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError
        return created_at, value["i"], value["s"], value["p"], user_id
    except Exception as exc:
        raise ValidationError("invalid document list cursor") from exc


def _utcnow() -> datetime:
    return datetime.now(UTC)


class DocumentService(_LoggingMixin):
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

    def get_internal_metadata(
        self, document_id: str, *, user_id: str | None = None
    ) -> DocumentMetadata:
        try:
            if user_id is None:
                metadata = self._metadata_store.get_metadata(document_id)
            else:
                metadata = self._metadata_store.get_metadata(document_id, user_id=user_id)
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
        user_id: str | None = None,
        unscoped_only: bool = False,
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
                    user_id=user_id,
                    unscoped_only=unscoped_only,
                )
            else:
                metadata = self._metadata_store.list_metadata(
                    offset=offset,
                    limit=limit,
                    status=status,
                    user_id=user_id,
                    unscoped_only=unscoped_only,
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
        self,
        *,
        offset: int,
        limit: int,
        status: DocumentStatus | None,
        user_id: str | None = None,
        unscoped_only: bool = False,
    ) -> list[PublicDocumentMetadata]:
        self._validate_public_status(status)
        return [
            public_metadata(item)
            for item in self.list_internal(
                offset=offset,
                limit=limit,
                status=status,
                excluded_statuses=_PUBLIC_EXCLUDED_STATUSES,
                user_id=user_id,
                unscoped_only=unscoped_only,
            )
        ]

    def list_page(
        self,
        *,
        cursor: str | None,
        limit: int,
        status: DocumentStatus | None,
        user_id: str | None = None,
        unscoped_only: bool = False,
    ) -> DocumentPage:
        self._validate_public_status(status)
        if limit <= 0 or limit > _MAX_PAGE_LIMIT:
            raise ValidationError("limit must be between 1 and 1000")
        after_created_at: datetime | None = None
        after_document_id: str | None = None
        if cursor is not None:
            (
                after_created_at,
                after_document_id,
                cursor_status,
                cursor_page_size,
                cursor_user_id,
            ) = decode_cursor(cursor)
            requested_status = status.value if status is not None else None
            if cursor_status != requested_status:
                raise ValidationError("cursor status filter does not match the request")
            if cursor_page_size != limit:
                raise ValidationError("cursor page size does not match the request")
            if cursor_user_id != user_id:
                raise ValidationError("cursor user scope does not match the request")
        try:
            metadata = self._metadata_store.list_metadata_page(
                after_created_at=after_created_at,
                after_document_id=after_document_id,
                limit=limit + 1,
                status=status,
                excluded_statuses=_PUBLIC_EXCLUDED_STATUSES,
                user_id=user_id,
                unscoped_only=unscoped_only,
            )
        except Exception as exc:
            raise MetadataStoreError("Failed to list document metadata page") from exc
        has_more = len(metadata) > limit
        items = metadata[:limit]
        next_cursor = None
        if has_more and items:
            last = items[-1]
            next_cursor = encode_cursor(
                last.created_at,
                last.document_id,
                status,
                limit,
                user_id=user_id,
            )
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
        if status is not None and not isinstance(status, DocumentStatus):
            raise ValidationError("status must be a DocumentStatus")
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


class AsyncDocumentService(_LoggingMixin):
    """Async document operations with the same policy as ``DocumentService``."""

    def __init__(
        self,
        *,
        metadata_store: AsyncMetadataStore,
        object_store: ObjectStore,
        logger: logging.Logger,
    ) -> None:
        self._metadata_store = metadata_store
        self._object_store = object_store
        self._logger = logger

    async def get_internal_metadata(
        self, document_id: str, *, user_id: str | None = None
    ) -> DocumentMetadata:
        try:
            if user_id is None:
                metadata = await self._metadata_store.get_metadata(document_id)
            else:
                metadata = await self._metadata_store.get_metadata(
                    document_id,
                    user_id=user_id,
                )
        except LookupError as exc:
            self._log_warning("document.metadata.not_found", document_id=document_id)
            raise DocumentNotFoundError(f"Document not found: {document_id}") from exc
        except Exception as exc:
            self._log_exception(
                "document.metadata.backend_error",
                exc,
                document_id=document_id,
            )
            raise MetadataStoreError(f"Failed to load metadata for {document_id}") from exc
        self._log_info(
            "document.metadata.succeeded",
            document_id=document_id,
            status=metadata.status.value,
        )
        return metadata

    async def get_metadata(self, document_id: str) -> PublicDocumentMetadata:
        metadata = await self.get_internal_metadata(document_id)
        if metadata.status in _PUBLIC_EXCLUDED_STATUSES:
            raise DocumentNotFoundError(
                f"Document not found: {document_id}",
                document_id=document_id,
            )
        return public_metadata(metadata)

    async def list_internal(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
        status: DocumentStatus | None = None,
        excluded_statuses: tuple[DocumentStatus, ...] = (),
        user_id: str | None = None,
        unscoped_only: bool = False,
    ) -> list[DocumentMetadata]:
        if offset < 0:
            raise ValidationError("offset must not be negative")
        if limit <= 0:
            raise ValidationError("limit must be positive")
        try:
            if excluded_statuses:
                metadata = await self._metadata_store.list_metadata(
                    offset=offset,
                    limit=limit,
                    status=status,
                    excluded_statuses=excluded_statuses,
                    user_id=user_id,
                    unscoped_only=unscoped_only,
                )
            else:
                metadata = await self._metadata_store.list_metadata(
                    offset=offset,
                    limit=limit,
                    status=status,
                    user_id=user_id,
                    unscoped_only=unscoped_only,
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

    async def list_page(
        self,
        *,
        cursor: str | None,
        limit: int,
        status: DocumentStatus | None,
        user_id: str | None = None,
        unscoped_only: bool = False,
    ) -> DocumentPage:
        self._validate_public_status(status)
        if limit <= 0 or limit > _MAX_PAGE_LIMIT:
            raise ValidationError("limit must be between 1 and 1000")
        after_created_at: datetime | None = None
        after_document_id: str | None = None
        if cursor is not None:
            (
                after_created_at,
                after_document_id,
                cursor_status,
                cursor_page_size,
                cursor_user_id,
            ) = decode_cursor(cursor)
            requested_status = status.value if status is not None else None
            if cursor_status != requested_status:
                raise ValidationError("cursor status filter does not match the request")
            if cursor_page_size != limit:
                raise ValidationError("cursor page size does not match the request")
            if cursor_user_id != user_id:
                raise ValidationError("cursor user scope does not match the request")
        try:
            metadata = await self._metadata_store.list_metadata_page(
                after_created_at=after_created_at,
                after_document_id=after_document_id,
                limit=limit + 1,
                status=status,
                excluded_statuses=_PUBLIC_EXCLUDED_STATUSES,
                user_id=user_id,
                unscoped_only=unscoped_only,
            )
        except Exception as exc:
            raise MetadataStoreError("Failed to list document metadata page") from exc
        has_more = len(metadata) > limit
        items = metadata[:limit]
        next_cursor = None
        if has_more and items:
            last = items[-1]
            next_cursor = encode_cursor(
                last.created_at,
                last.document_id,
                status,
                limit,
                user_id=user_id,
            )
        return DocumentPage(
            items=[public_metadata(item) for item in items],
            next_cursor=next_cursor,
            has_more=has_more,
        )

    async def get_content(self, document_id: str) -> DocumentContent:
        started = perf_counter()
        metadata = await self.get_internal_metadata(document_id)
        DocumentService._ensure_content_readable(metadata)
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

    async def get_content_stream(
        self,
        document_id: str,
        *,
        chunk_size: int,
    ) -> AsyncDocumentContentStream:
        if chunk_size <= 0:
            raise ValidationError("chunk_size must be positive")
        started = perf_counter()
        metadata = await self.get_internal_metadata(document_id)
        DocumentService._ensure_content_readable(metadata)
        try:
            stored_stream = self._object_store.get_object_stream(
                document_id,
                metadata.storage_key,
            )
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
        self._log_info(
            "document.content_stream.succeeded",
            document_id=document_id,
            storage_key=metadata.storage_key,
            file_size=stored_stream.size,
            chunk_size=chunk_size,
            duration_ms=(perf_counter() - started) * 1000,
        )
        return AsyncDocumentContentStream(
            document_id=document_id,
            _async_stream=stored_stream.stream,
            _content_type=stored_stream.content_type,
            _filename=stored_stream.filename,
            _size=stored_stream.size,
            _checksum=stored_stream.checksum,
            _async_close_callback=None,
            chunk_size=chunk_size,
        )

    async def delete(
        self,
        document_id: str,
        *,
        hard_delete: bool,
    ) -> DeleteDocumentResult:
        started = perf_counter()
        metadata = await self.get_internal_metadata(document_id)
        deleting_metadata = await self.set_status(metadata, DocumentStatus.DELETING)
        try:
            self._object_store.delete_object(document_id, metadata.storage_key)
        except Exception as exc:
            await self.set_status_best_effort(deleting_metadata, DocumentStatus.FAILED)
            self._log_exception(
                "document.delete.storage_error",
                exc,
                document_id=document_id,
                storage_key=metadata.storage_key,
                hard_delete=hard_delete,
                duration_ms=(perf_counter() - started) * 1000,
            )
            raise StorageError(
                f"Failed to delete document content for {document_id}"
            ) from exc
        try:
            if hard_delete:
                await self._metadata_store.hard_delete(document_id)
                status = DocumentStatus.DELETED
            else:
                status = (await self._metadata_store.mark_deleted(document_id)).status
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

    async def set_status(
        self,
        metadata: DocumentMetadata,
        status: DocumentStatus,
    ) -> DocumentMetadata:
        updated_metadata = replace(
            metadata,
            status=status,
            updated_at=datetime.now(UTC),
            deleted_at=(
                metadata.deleted_at
                if status != DocumentStatus.DELETED
                else datetime.now(UTC)
            ),
        )
        try:
            return await self._metadata_store.update_metadata(updated_metadata)
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

    async def set_status_best_effort(
        self,
        metadata: DocumentMetadata,
        status: DocumentStatus,
    ) -> None:
        try:
            await self.set_status(metadata, status)
        except MetadataStoreError:
            return

    @staticmethod
    def _validate_public_status(status: DocumentStatus | None) -> None:
        DocumentService._validate_public_status(status)
