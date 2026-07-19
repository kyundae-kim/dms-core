from __future__ import annotations

from typing import Any

from dms.domain.models import DocumentStatus
from dms.sdk.types import DeleteDocumentResult, DocumentContent, DocumentContentStream, DocumentPage, PublicDocumentMetadata


class DocumentService:
    """Coordinates document reads, listing, and deletion through the SDK's stable internal seams."""

    def __init__(self, host: Any) -> None:
        self._host = host

    def get_metadata(self, document_id: str) -> PublicDocumentMetadata:
        return self._host._get_document_metadata(document_id)

    def list(self, *, offset: int, limit: int, status: DocumentStatus | None) -> list[PublicDocumentMetadata]:
        return self._host._list_documents(offset=offset, limit=limit, status=status)

    def list_page(self, *, cursor: str | None, limit: int, status: DocumentStatus | None) -> DocumentPage:
        return self._host._list_documents_page(cursor=cursor, limit=limit, status=status)

    def get_content(self, document_id: str) -> DocumentContent:
        return self._host._get_document_content(document_id)

    def get_content_stream(self, document_id: str, *, chunk_size: int) -> DocumentContentStream:
        return self._host._get_document_content_stream(document_id, chunk_size=chunk_size)

    def delete(self, document_id: str, *, hard_delete: bool) -> DeleteDocumentResult:
        return self._host._delete_document(document_id, hard_delete=hard_delete)
