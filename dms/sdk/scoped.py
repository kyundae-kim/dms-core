from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from typing import BinaryIO, TypeVar

from dms.domain.models import DocumentMetadata, DocumentStatus
from dms.sdk.contracts import DocumentCopyResult, DmsOperationContext
from dms.sdk.errors import ValidationError
from dms.sdk.types import (
    AsyncDocumentContentStream,
    BatchReconciliationResult,
    DataResetResult,
    DeleteDocumentResult,
    DocumentContent,
    DocumentContentStream,
    DocumentInspection,
    DocumentPage,
    PublicDocumentMetadata,
    ReconciliationPlan,
    ReconciliationResult,
    RecoveryAction,
    UploadDocumentRequest,
    UploadDocumentResult,
    UploadDocumentStreamRequest,
    UploadOperationResult,
)

ObservedResult = TypeVar("ObservedResult")


class ScopedDocumentManagementSDK:
    """An immutable per-operation facade that never mutates the shared SDK."""

    def __init__(
        self,
        sdk: DefaultDocumentManagementSDK,
        context: DmsOperationContext,
    ) -> None:
        self._sdk = sdk
        self.context = context

    def _metadata(self, metadata: object) -> object:
        return self.context.default_metadata if metadata is None else metadata

    def _created_by(self, created_by: str | None) -> str | None:
        return created_by if created_by is not None else self.context.created_by

    def _idempotency_scope(self, scope: str | None) -> str | None:
        return scope if scope is not None else self.context.idempotency_scope

    def _call(
        self,
        method: Callable[..., ObservedResult],
        *args: object,
        **kwargs: object,
    ) -> ObservedResult:
        return method(*args, access_context=self.context.access, **kwargs)

    def upload_document(self, request: UploadDocumentRequest) -> UploadDocumentResult:
        return self._sdk.upload_document(
            replace(
                request,
                metadata=self._metadata(request.metadata),
                created_by=self._created_by(request.created_by),
                idempotency_scope=self._idempotency_scope(request.idempotency_scope),
            )
        )

    def upload_document_stream(
        self,
        request: UploadDocumentStreamRequest,
    ) -> UploadDocumentResult:
        return self._sdk.upload_document_stream(
            replace(
                request,
                metadata=self._metadata(request.metadata),
                created_by=self._created_by(request.created_by),
            )
        )

    def get_upload_operation(
        self,
        *,
        idempotency_key: str,
        scope: str | None = None,
    ) -> UploadOperationResult:
        resolved_scope = self._idempotency_scope(scope)
        if resolved_scope is None:
            raise ValidationError("idempotency scope is required")
        return self._sdk.get_upload_operation(
            scope=resolved_scope,
            idempotency_key=idempotency_key,
        )

    def upload_file(
        self,
        path: str | Path,
        *,
        filename: str | None = None,
        content_type: str | None = None,
        document_id: str | None = None,
        metadata: object = None,
        created_by: str | None = None,
    ) -> UploadDocumentResult:
        return self._sdk.upload_file(
            path,
            filename=filename,
            content_type=content_type,
            document_id=document_id,
            metadata=self._metadata(metadata),
            created_by=self._created_by(created_by),
        )

    def get_document_metadata(self, document_id: str) -> PublicDocumentMetadata:
        return self._call(self._sdk.get_document_metadata, document_id)

    def get_internal_document_metadata(self, document_id: str) -> DocumentMetadata:
        return self._call(self._sdk.get_internal_document_metadata, document_id)

    def list_documents(
        self,
        *,
        cursor: str | None = None,
        limit: int = 100,
        status: DocumentStatus | None = None,
    ) -> DocumentPage:
        return self._call(
            self._sdk.list_documents,
            cursor=cursor,
            limit=limit,
            status=status,
        )

    def list_documents_page(
        self,
        *,
        cursor: str | None = None,
        limit: int = 100,
        status: DocumentStatus | None = None,
    ) -> DocumentPage:
        return self._call(
            self._sdk.list_documents_page,
            cursor=cursor,
            limit=limit,
            status=status,
        )

    def iter_documents(
        self,
        *,
        status: DocumentStatus | None = None,
        page_size: int = 100,
    ) -> Iterator[PublicDocumentMetadata]:
        return self._call(
            self._sdk.iter_documents,
            status=status,
            page_size=page_size,
        )

    def get_document_content(self, document_id: str) -> DocumentContent:
        return self._call(self._sdk.get_document_content, document_id)

    async def get_document_content_async_stream(
        self,
        document_id: str,
        *,
        chunk_size: int = 65536,
    ) -> AsyncDocumentContentStream:
        return await self._sdk.get_document_content_async_stream(
            document_id,
            chunk_size=chunk_size,
            access_context=self.context.access,
        )

    def get_document_content_stream(
        self,
        document_id: str,
        *,
        chunk_size: int = 65536,
    ) -> DocumentContentStream:
        return self._call(
            self._sdk.get_document_content_stream,
            document_id,
            chunk_size=chunk_size,
        )

    def iter_document_chunks(
        self,
        document_id: str,
        *,
        chunk_size: int = 65536,
    ) -> Iterator[bytes]:
        return self._call(
            self._sdk.iter_document_chunks,
            document_id,
            chunk_size=chunk_size,
        )

    def copy_document_to(
        self,
        document_id: str,
        sink: BinaryIO,
        *,
        chunk_size: int = 65536,
        verify_checksum: bool = True,
    ) -> DocumentCopyResult:
        return self._call(
            self._sdk.copy_document_to,
            document_id,
            sink,
            chunk_size=chunk_size,
            verify_checksum=verify_checksum,
        )

    def delete_document(
        self,
        document_id: str,
        *,
        hard_delete: bool = False,
    ) -> DeleteDocumentResult:
        return self._call(
            self._sdk.delete_document,
            document_id,
            hard_delete=hard_delete,
        )

    def soft_delete_document(self, document_id: str) -> DeleteDocumentResult:
        return self._call(self._sdk.soft_delete_document, document_id)

    def hard_delete_document(self, document_id: str) -> DeleteDocumentResult:
        return self._call(self._sdk.hard_delete_document, document_id)

    def clear_all_data(self) -> DataResetResult:
        return self._call(self._sdk.clear_all_data)

    def initialize_for_data_load(self) -> DataResetResult:
        return self._call(self._sdk.initialize_for_data_load)

    def inspect_document(self, document_id: str) -> DocumentInspection:
        return self._call(self._sdk.inspect_document, document_id)

    def list_recovery_candidates(
        self,
        *,
        status: DocumentStatus,
        offset: int = 0,
        limit: int = 100,
    ) -> list[DocumentMetadata]:
        return self._call(
            self._sdk.list_recovery_candidates,
            status=status,
            offset=offset,
            limit=limit,
        )

    def iter_recovery_candidates(
        self,
        *,
        status: DocumentStatus,
        page_size: int = 100,
    ) -> Iterator[DocumentMetadata]:
        return self._call(
            self._sdk.iter_recovery_candidates,
            status=status,
            page_size=page_size,
        )

    def reconcile_document(
        self,
        document_id: str,
        action: RecoveryAction,
        *,
        storage_key: str | None = None,
        dry_run: bool = False,
        actor: str | None = None,
    ) -> ReconciliationResult:
        return self._call(
            self._sdk.reconcile_document,
            document_id,
            action,
            storage_key=storage_key,
            dry_run=dry_run,
            actor=actor if actor is not None else self.context.audit_actor,
        )

    def execute_reconciliation_plan(
        self,
        plan: ReconciliationPlan,
        *,
        actor: str | None = None,
    ) -> BatchReconciliationResult:
        return self._call(
            self._sdk.execute_reconciliation_plan,
            plan,
            actor=actor if actor is not None else self.context.audit_actor,
        )

    def reconcile_documents(
        self,
        *,
        status: DocumentStatus,
        action: RecoveryAction,
        offset: int = 0,
        limit: int = 100,
        dry_run: bool = False,
        actor: str | None = None,
    ) -> BatchReconciliationResult:
        return self._call(
            self._sdk.reconcile_documents,
            status=status,
            action=action,
            offset=offset,
            limit=limit,
            dry_run=dry_run,
            actor=actor if actor is not None else self.context.audit_actor,
        )


from dms.sdk.implementation import DefaultDocumentManagementSDK  # noqa: E402
