from __future__ import annotations

from typing import Protocol

from dms.domain.models import DocumentMetadata
from dms.sdk.types import (
    DeleteDocumentResult,
    DocumentContent,
    HealthStatus,
    UploadDocumentRequest,
    UploadDocumentResult,
)


class DocumentManagementSDK(Protocol):
    def upload_document(self, request: UploadDocumentRequest) -> UploadDocumentResult: ...

    def get_document_metadata(self, document_id: str) -> DocumentMetadata: ...

    def get_document_content(self, document_id: str) -> DocumentContent: ...

    def delete_document(
        self,
        document_id: str,
        *,
        hard_delete: bool = False,
    ) -> DeleteDocumentResult: ...

    def check_health(self) -> HealthStatus: ...

    def close(self) -> None: ...
