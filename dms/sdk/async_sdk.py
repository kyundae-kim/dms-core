from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import BinaryIO, TypeVar

from dms.domain.models import DocumentMetadata, DocumentStatus
from dms.sdk.async_support import (
    iterate_document_pages as _iterate_document_pages,
)
from dms.sdk.async_support import (
    iterate_recovery_pages as _iterate_recovery_pages,
)
from dms.sdk.async_support import (
    run_blocking as _run_blocking,
)
from dms.sdk.contracts import AccessContext, DmsOperationContext, DocumentCopyResult
from dms.sdk.implementation import DefaultDocumentManagementSDK
from dms.sdk.types import (
    AsyncDocumentContentStream,
    BatchReconciliationResult,
    DataResetResult,
    DeleteDocumentResult,
    DocumentContent,
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

_ResultT = TypeVar("_ResultT")


class AsyncDocumentManagementSDK:
    """Awaitable facade preserving the default SDK's public contracts."""

    def __init__(self, sdk: DefaultDocumentManagementSDK) -> None:
        self._sdk = sdk

    def scoped(self, context: DmsOperationContext) -> AsyncScopedDocumentManagementSDK:
        return AsyncScopedDocumentManagementSDK(self, context)


    async def _run_sync(
        self,
        operation: Callable[..., _ResultT],
        *args: object,
        **kwargs: object,
    ) -> _ResultT:
        return await _run_blocking(operation, *args, **kwargs)

    async def upload_document(self, request: UploadDocumentRequest) -> UploadDocumentResult:
        return await self._run_sync(self._sdk.upload_document, request)

    async def upload_file(
        self,
        path: str | Path,
        *,
        filename: str | None = None,
        content_type: str | None = None,
        document_id: str | None = None,
        metadata: object = None,
        created_by: str | None = None,
    ) -> UploadDocumentResult:
        return await self._run_sync(
            self._sdk.upload_file,
            path,
            filename=filename,
            content_type=content_type,
            document_id=document_id,
            metadata=metadata,
            created_by=created_by,
        )

    async def upload_document_stream(
        self, request: UploadDocumentStreamRequest,
    ) -> UploadDocumentResult:
        return await self._run_sync(self._sdk.upload_document_stream, request)

    async def get_upload_operation(
        self, *, scope: str, idempotency_key: str,
    ) -> UploadOperationResult:
        return await self._run_sync(
            self._sdk.get_upload_operation,
            scope=scope,
            idempotency_key=idempotency_key,
        )

    async def get_internal_document_metadata(
        self,
        document_id: str,
        *,
        access_context: AccessContext | None = None,
    ) -> DocumentMetadata:
        return await self._run_sync(
            self._sdk.get_internal_document_metadata,
            document_id,
            access_context=access_context,
        )

    async def get_document_metadata(
        self,
        document_id: str,
        *,
        access_context: AccessContext | None = None,
    ) -> PublicDocumentMetadata:
        return await self._run_sync(
            self._sdk.get_document_metadata,
            document_id,
            access_context=access_context,
        )

    async def list_documents(
        self,
        *,
        cursor: str | None = None,
        limit: int = 100,
        status: DocumentStatus | None = None,
        access_context: AccessContext | None = None,
    ) -> DocumentPage:
        return await self._run_sync(
            self._sdk.list_documents,
            cursor=cursor,
            limit=limit,
            status=status,
            access_context=access_context,
        )

    async def list_documents_page(
        self,
        *,
        cursor: str | None = None,
        limit: int = 100,
        status: DocumentStatus | None = None,
        access_context: AccessContext | None = None,
    ) -> DocumentPage:
        return await self._run_sync(
            self._sdk.list_documents_page,
            cursor=cursor,
            limit=limit,
            status=status,
            access_context=access_context,
        )

    async def iter_documents(
        self,
        *,
        status: DocumentStatus | None = None,
        page_size: int = 100,
        access_context: AccessContext | None = None,
    ) -> AsyncIterator[PublicDocumentMetadata]:
        async for item in _iterate_document_pages(
            self.list_documents,
            status=status,
            page_size=page_size,
            access_context=access_context,
        ):
            yield item

    async def inspect_document(
        self,
        document_id: str,
        *,
        access_context: AccessContext | None = None,
    ) -> DocumentInspection:
        return await self._run_sync(
            self._sdk.inspect_document,
            document_id,
            access_context=access_context,
        )

    async def list_recovery_candidates(
        self,
        *,
        status: DocumentStatus,
        offset: int = 0,
        limit: int = 100,
        access_context: AccessContext | None = None,
    ) -> list[DocumentMetadata]:
        return await self._run_sync(
            self._sdk.list_recovery_candidates,
            status=status,
            offset=offset,
            limit=limit,
            access_context=access_context,
        )

    async def iter_recovery_candidates(
        self,
        *,
        status: DocumentStatus,
        page_size: int = 100,
        access_context: AccessContext | None = None,
    ) -> AsyncIterator[DocumentMetadata]:
        async for item in _iterate_recovery_pages(
            self.list_recovery_candidates,
            status=status,
            page_size=page_size,
            access_context=access_context,
        ):
            yield item

    async def reconcile_document(
        self,
        document_id: str,
        action: RecoveryAction,
        *,
        storage_key: str | None = None,
        dry_run: bool = False,
        actor: str | None = None,
        access_context: AccessContext | None = None,
    ) -> ReconciliationResult:
        return await self._run_sync(
            self._sdk.reconcile_document,
            document_id,
            action,
            storage_key=storage_key,
            dry_run=dry_run,
            actor=actor,
            access_context=access_context,
        )

    async def execute_reconciliation_plan(
        self,
        plan: ReconciliationPlan,
        *,
        actor: str | None = None,
        access_context: AccessContext | None = None,
    ) -> BatchReconciliationResult:
        return await self._run_sync(
            self._sdk.execute_reconciliation_plan,
            plan,
            actor=actor,
            access_context=access_context,
        )

    async def reconcile_documents(
        self,
        *,
        status: DocumentStatus,
        action: RecoveryAction,
        offset: int = 0,
        limit: int = 100,
        dry_run: bool = False,
        actor: str | None = None,
        access_context: AccessContext | None = None,
    ) -> BatchReconciliationResult:
        return await self._run_sync(
            self._sdk.reconcile_documents,
            status=status,
            action=action,
            offset=offset,
            limit=limit,
            dry_run=dry_run,
            actor=actor,
            access_context=access_context,
        )

    async def get_document_content(
        self,
        document_id: str,
        *,
        access_context: AccessContext | None = None,
    ) -> DocumentContent:
        return await self._run_sync(
            self._sdk.get_document_content,
            document_id,
            access_context=access_context,
        )

    async def get_document_content_stream(
        self,
        document_id: str,
        *,
        chunk_size: int = 65536,
        access_context: AccessContext | None = None,
    ) -> AsyncDocumentContentStream:
        return await self._sdk.get_document_content_async_stream(
            document_id,
            chunk_size=chunk_size,
            access_context=access_context,
        )

    async def get_document_content_async_stream(
        self,
        document_id: str,
        *,
        chunk_size: int = 65536,
        access_context: AccessContext | None = None,
    ) -> AsyncDocumentContentStream:
        return await self.get_document_content_stream(
            document_id,
            chunk_size=chunk_size,
            access_context=access_context,
        )

    async def iter_document_chunks(
        self,
        document_id: str,
        *,
        chunk_size: int = 65536,
        access_context: AccessContext | None = None,
    ) -> AsyncIterator[bytes]:
        source = await self.get_document_content_stream(
            document_id,
            chunk_size=chunk_size,
            access_context=access_context,
        )
        try:
            async for chunk in source.iter_chunks(chunk_size):
                yield chunk
        finally:
            await source.aclose()

    async def copy_document_to(
        self,
        document_id: str,
        sink: BinaryIO,
        *,
        chunk_size: int = 65536,
        verify_checksum: bool = True,
        access_context: AccessContext | None = None,
    ) -> DocumentCopyResult:
        return await self._run_sync(
            self._sdk.copy_document_to,
            document_id,
            sink,
            chunk_size=chunk_size,
            verify_checksum=verify_checksum,
            access_context=access_context,
        )

    async def delete_document(
        self,
        document_id: str,
        *,
        hard_delete: bool = False,
        access_context: AccessContext | None = None,
    ) -> DeleteDocumentResult:
        return await self._run_sync(
            self._sdk.delete_document,
            document_id,
            hard_delete=hard_delete,
            access_context=access_context,
        )

    async def soft_delete_document(
        self,
        document_id: str,
        *,
        access_context: AccessContext | None = None,
    ) -> DeleteDocumentResult:
        return await self._run_sync(
            self._sdk.soft_delete_document,
            document_id,
            access_context=access_context,
        )

    async def hard_delete_document(
        self,
        document_id: str,
        *,
        access_context: AccessContext | None = None,
    ) -> DeleteDocumentResult:
        return await self._run_sync(
            self._sdk.hard_delete_document,
            document_id,
            access_context=access_context,
        )

    async def clear_all_data(
        self,
        *,
        access_context: AccessContext | None = None,
    ) -> DataResetResult:
        return await self._run_sync(
            self._sdk.clear_all_data,
            access_context=access_context,
        )

    async def initialize_for_data_load(
        self,
        *,
        access_context: AccessContext | None = None,
    ) -> DataResetResult:
        return await self._run_sync(
            self._sdk.initialize_for_data_load,
            access_context=access_context,
        )


from dms.sdk.async_scoped import AsyncScopedDocumentManagementSDK
