from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping
from pathlib import Path
from typing import BinaryIO, TypeVar

from dms.domain.models import DocumentMetadata, DocumentStatus
from dms.sdk.contracts import AccessContext, DocumentCopyResult, DmsOperationContext
from dms.sdk.implementation import DefaultDocumentManagementSDK
from dms.sdk.types import (
    AsyncDocumentContentStream,
    BatchReconciliationResult,
    DataResetResult,
    DeleteDocumentResult,
    DocumentContent,
    DocumentInspection,
    DocumentPage,
    HealthStatus,
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

    async def __aenter__(self) -> AsyncDocumentManagementSDK:
        return self

    async def __aexit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        await self.aclose()

    async def _run_sync(
        self,
        operation: Callable[..., _ResultT],
        *args: object,
        **kwargs: object,
    ) -> _ResultT:
        """Run blocking work off-loop and reach its final state before propagating cancellation."""
        task = asyncio.create_task(asyncio.to_thread(operation, *args, **kwargs))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            try:
                await task
            except Exception:
                raise
            raise

    async def upload_document(self, request: UploadDocumentRequest) -> UploadDocumentResult:
        return await self._run_sync(self._sdk.upload_document, request)

    async def upload_file(
        self,
        path: str | Path,
        *,
        filename: str | None = None,
        content_type: str | None = None,
        document_id: str | None = None,
        metadata: Mapping[str, object] | None = None,
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
        cursor: str | None = None
        while True:
            page = await self.list_documents(
                cursor=cursor,
                limit=page_size,
                status=status,
                access_context=access_context,
            )
            for item in page.items:
                yield item
            if page.next_cursor is None:
                return
            cursor = page.next_cursor

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
        offset = 0
        while True:
            items = await self.list_recovery_candidates(
                status=status,
                offset=offset,
                limit=page_size,
                access_context=access_context,
            )
            if not items:
                return
            for item in items:
                yield item
            if len(items) < page_size:
                return
            offset += len(items)

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

    async def check_health(self) -> HealthStatus:
        return await self._run_sync(self._sdk.check_health)

    async def close(self) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        task = asyncio.create_task(self._sdk.aclose())
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise


class AsyncScopedDocumentManagementSDK:
    """Awaitable adapter for an immutable operation-scoped facade."""

    def __init__(
        self,
        sdk: AsyncDocumentManagementSDK,
        context: DmsOperationContext,
    ) -> None:
        self._async_sdk = sdk
        self._scoped = sdk._sdk.scoped(context)
        self.context = context

    async def _run(
        self,
        operation: Callable[..., _ResultT],
        *args: object,
        **kwargs: object,
    ) -> _ResultT:
        return await self._async_sdk._run_sync(operation, *args, **kwargs)

    async def upload_document(
        self, request: UploadDocumentRequest,
    ) -> UploadDocumentResult:
        return await self._run(self._scoped.upload_document, request)

    async def upload_file(
        self,
        path: str | Path,
        *,
        filename: str | None = None,
        content_type: str | None = None,
        document_id: str | None = None,
        metadata: Mapping[str, object] | None = None,
        created_by: str | None = None,
    ) -> UploadDocumentResult:
        return await self._run(
            self._scoped.upload_file,
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
        return await self._run(self._scoped.upload_document_stream, request)

    async def get_upload_operation(
        self,
        *,
        idempotency_key: str,
        scope: str | None = None,
    ) -> UploadOperationResult:
        return await self._run(
            self._scoped.get_upload_operation,
            idempotency_key=idempotency_key,
            scope=scope,
        )

    async def get_internal_document_metadata(self, document_id: str) -> DocumentMetadata:
        return await self._run(self._scoped.get_internal_document_metadata, document_id)

    async def get_document_metadata(self, document_id: str) -> PublicDocumentMetadata:
        return await self._run(self._scoped.get_document_metadata, document_id)

    async def list_documents(
        self,
        *,
        cursor: str | None = None,
        limit: int = 100,
        status: DocumentStatus | None = None,
    ) -> DocumentPage:
        return await self._run(
            self._scoped.list_documents,
            cursor=cursor,
            limit=limit,
            status=status,
        )

    async def list_documents_page(
        self,
        *,
        cursor: str | None = None,
        limit: int = 100,
        status: DocumentStatus | None = None,
    ) -> DocumentPage:
        return await self._run(
            self._scoped.list_documents_page,
            cursor=cursor,
            limit=limit,
            status=status,
        )

    async def iter_documents(
        self,
        *,
        status: DocumentStatus | None = None,
        page_size: int = 100,
    ) -> AsyncIterator[PublicDocumentMetadata]:
        cursor: str | None = None
        while True:
            page = await self.list_documents(
                cursor=cursor,
                limit=page_size,
                status=status,
            )
            for item in page.items:
                yield item
            if page.next_cursor is None:
                return
            cursor = page.next_cursor

    async def get_document_content(self, document_id: str) -> DocumentContent:
        return await self._run(self._scoped.get_document_content, document_id)

    async def get_document_content_stream(
        self,
        document_id: str,
        *,
        chunk_size: int = 65536,
    ) -> AsyncDocumentContentStream:
        return await self._async_sdk.get_document_content_stream(
            document_id,
            chunk_size=chunk_size,
            access_context=self.context.access,
        )

    async def get_document_content_async_stream(
        self,
        document_id: str,
        *,
        chunk_size: int = 65536,
    ) -> AsyncDocumentContentStream:
        return await self.get_document_content_stream(
            document_id,
            chunk_size=chunk_size,
        )

    async def iter_document_chunks(
        self,
        document_id: str,
        *,
        chunk_size: int = 65536,
    ) -> AsyncIterator[bytes]:
        source = await self.get_document_content_stream(
            document_id,
            chunk_size=chunk_size,
        )
        async for chunk in source.aiter_chunks_closing(chunk_size):
            yield chunk

    async def copy_document_to(
        self,
        document_id: str,
        sink: BinaryIO,
        *,
        chunk_size: int = 65536,
        verify_checksum: bool = True,
    ) -> DocumentCopyResult:
        return await self._run(
            self._scoped.copy_document_to,
            document_id,
            sink,
            chunk_size=chunk_size,
            verify_checksum=verify_checksum,
        )

    async def delete_document(
        self,
        document_id: str,
        *,
        hard_delete: bool = False,
    ) -> DeleteDocumentResult:
        return await self._run(
            self._scoped.delete_document,
            document_id,
            hard_delete=hard_delete,
        )

    async def soft_delete_document(self, document_id: str) -> DeleteDocumentResult:
        return await self._run(self._scoped.soft_delete_document, document_id)

    async def hard_delete_document(self, document_id: str) -> DeleteDocumentResult:
        return await self._run(self._scoped.hard_delete_document, document_id)

    async def clear_all_data(self) -> DataResetResult:
        return await self._run(self._scoped.clear_all_data)

    async def initialize_for_data_load(self) -> DataResetResult:
        return await self._run(self._scoped.initialize_for_data_load)

    async def inspect_document(self, document_id: str) -> DocumentInspection:
        return await self._run(self._scoped.inspect_document, document_id)

    async def list_recovery_candidates(
        self,
        *,
        status: DocumentStatus,
        offset: int = 0,
        limit: int = 100,
    ) -> list[DocumentMetadata]:
        return await self._run(
            self._scoped.list_recovery_candidates,
            status=status,
            offset=offset,
            limit=limit,
        )

    async def iter_recovery_candidates(
        self,
        *,
        status: DocumentStatus,
        page_size: int = 100,
    ) -> AsyncIterator[DocumentMetadata]:
        offset = 0
        while True:
            items = await self.list_recovery_candidates(
                status=status,
                offset=offset,
                limit=page_size,
            )
            for item in items:
                yield item
            if len(items) < page_size:
                return
            offset += len(items)

    async def reconcile_document(
        self,
        document_id: str,
        action: RecoveryAction,
        *,
        storage_key: str | None = None,
        dry_run: bool = False,
        actor: str | None = None,
    ) -> ReconciliationResult:
        return await self._run(
            self._scoped.reconcile_document,
            document_id,
            action,
            storage_key=storage_key,
            dry_run=dry_run,
            actor=actor,
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
    ) -> BatchReconciliationResult:
        return await self._run(
            self._scoped.reconcile_documents,
            status=status,
            action=action,
            offset=offset,
            limit=limit,
            dry_run=dry_run,
            actor=actor,
        )

    async def execute_reconciliation_plan(
        self,
        plan: ReconciliationPlan,
        *,
        actor: str | None = None,
    ) -> BatchReconciliationResult:
        return await self._run(
            self._scoped.execute_reconciliation_plan,
            plan,
            actor=actor,
        )

    async def check_health(self) -> HealthStatus:
        return await self._async_sdk._run_sync(self._scoped.check_health)
