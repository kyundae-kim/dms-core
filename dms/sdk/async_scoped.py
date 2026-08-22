from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path
from typing import BinaryIO

from dms.domain.models import DocumentMetadata, DocumentStatus
from dms.sdk.async_support import (
    iterate_document_pages as _iterate_document_pages,
)
from dms.sdk.async_support import (
    iterate_recovery_pages as _iterate_recovery_pages,
)
from dms.sdk.contracts import DmsOperationContext, DocumentCopyResult
from dms.sdk.errors import ValidationError
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


class AsyncScopedDocumentManagementSDK:
    """Awaitable operation-scoped facade for both async and legacy SDK cores."""

    def __init__(self, sdk: AsyncDocumentManagementSDK, context: DmsOperationContext) -> None:
        self._async_sdk = sdk
        self._scoped = sdk._sdk.scoped(context) if sdk._sdk is not None else None
        self.context = context

    def _metadata(self, metadata: object) -> object:
        return self.context.default_metadata if metadata is None else metadata

    def _created_by(self, created_by: str | None) -> str | None:
        return created_by if created_by is not None else self.context.created_by

    def _idempotency_scope(self, scope: str | None) -> str | None:
        return scope if scope is not None else self.context.idempotency_scope

    def _user_id(self, user_id: str | None) -> str | None:
        scoped_user_id = self.context.user_id
        if scoped_user_id is None and self.context.access is not None:
            scoped_user_id = self.context.access.user_id
        if scoped_user_id is not None and user_id not in (None, scoped_user_id):
            raise ValidationError("request user_id does not match the operation scope")
        return scoped_user_id if scoped_user_id is not None else user_id

    def _actor(self, actor: str | None) -> str | None:
        return actor if actor is not None else self.context.audit_actor

    async def _run_legacy(self, method_name: str, *args: object, **kwargs: object) -> object:
        assert self._scoped is not None
        return await self._async_sdk._run_sync(
            getattr(self._scoped, method_name),
            *args,
            **kwargs,
        )

    async def _call(self, method_name: str, *args: object, **kwargs: object) -> object:
        if self._scoped is not None:
            return await self._run_legacy(method_name, *args, **kwargs)
        kwargs["access_context"] = self.context.access
        return await getattr(self._async_sdk, method_name)(*args, **kwargs)

    async def upload_document(self, request: UploadDocumentRequest) -> UploadDocumentResult:
        request = replace(
            request,
            metadata=self._metadata(request.metadata),
            created_by=self._created_by(request.created_by),
            user_id=self._user_id(request.user_id),
            idempotency_scope=self._idempotency_scope(request.idempotency_scope),
        )
        if self._scoped is not None:
            return await self._run_legacy("upload_document", request)  # type: ignore[return-value]
        return await self._async_sdk.upload_document(
            request,
            access_context=self.context.access,
        )

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
        kwargs = {
            "filename": filename,
            "content_type": content_type,
            "document_id": document_id,
            "metadata": self._metadata(metadata),
            "created_by": self._created_by(created_by),
        }
        if self._scoped is not None:
            return await self._run_legacy("upload_file", path, **kwargs)  # type: ignore[return-value]
        return await self._async_sdk.upload_file(
            path,
            **kwargs,
            access_context=self.context.access,
        )

    async def upload_document_stream(
        self,
        request: UploadDocumentStreamRequest,
    ) -> UploadDocumentResult:
        request = replace(
            request,
            metadata=self._metadata(request.metadata),
            created_by=self._created_by(request.created_by),
        )
        if self._scoped is not None:
            return await self._run_legacy("upload_document_stream", request)  # type: ignore[return-value]
        return await self._async_sdk.upload_document_stream(
            request,
            access_context=self.context.access,
        )

    async def get_upload_operation(
        self,
        *,
        idempotency_key: str,
        scope: str | None = None,
    ) -> UploadOperationResult:
        resolved_scope = self._idempotency_scope(scope)
        if resolved_scope is None:
            raise ValidationError("idempotency scope is required")
        if self._scoped is not None:
            return await self._run_legacy(
                "get_upload_operation",
                idempotency_key=idempotency_key,
                scope=resolved_scope,
            )  # type: ignore[return-value]
        return await self._async_sdk.get_upload_operation(
            idempotency_key=idempotency_key,
            scope=resolved_scope,
            access_context=self.context.access,
        )

    async def get_internal_document_metadata(self, document_id: str) -> DocumentMetadata:
        return await self._call("get_internal_document_metadata", document_id)  # type: ignore[return-value]

    async def get_document_metadata(self, document_id: str) -> PublicDocumentMetadata:
        return await self._call("get_document_metadata", document_id)  # type: ignore[return-value]

    async def list_documents(
        self,
        *,
        cursor: str | None = None,
        limit: int = 100,
        status: DocumentStatus | None = None,
    ) -> DocumentPage:
        return await self._call(
            "list_documents",
            cursor=cursor,
            limit=limit,
            status=status,
        )  # type: ignore[return-value]

    async def list_documents_page(
        self,
        *,
        cursor: str | None = None,
        limit: int = 100,
        status: DocumentStatus | None = None,
    ) -> DocumentPage:
        return await self._call(
            "list_documents_page",
            cursor=cursor,
            limit=limit,
            status=status,
        )  # type: ignore[return-value]

    async def iter_documents(
        self,
        *,
        status: DocumentStatus | None = None,
        page_size: int = 100,
    ) -> AsyncIterator[PublicDocumentMetadata]:
        async for item in _iterate_document_pages(
            self.list_documents,
            status=status,
            page_size=page_size,
        ):
            yield item

    async def get_document_content(self, document_id: str) -> DocumentContent:
        return await self._call("get_document_content", document_id)  # type: ignore[return-value]

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
        )  # type: ignore[return-value]

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
        try:
            async for chunk in source.aiter_chunks_closing(chunk_size):
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
    ) -> DocumentCopyResult:
        return await self._call(
            "copy_document_to",
            document_id,
            sink,
            chunk_size=chunk_size,
            verify_checksum=verify_checksum,
        )  # type: ignore[return-value]

    async def delete_document(
        self,
        document_id: str,
        *,
        hard_delete: bool = False,
    ) -> DeleteDocumentResult:
        return await self._call(
            "delete_document",
            document_id,
            hard_delete=hard_delete,
        )  # type: ignore[return-value]

    async def soft_delete_document(self, document_id: str) -> DeleteDocumentResult:
        return await self._call("soft_delete_document", document_id)  # type: ignore[return-value]

    async def hard_delete_document(self, document_id: str) -> DeleteDocumentResult:
        return await self._call("hard_delete_document", document_id)  # type: ignore[return-value]

    async def clear_all_data(self) -> DataResetResult:
        return await self._call("clear_all_data")  # type: ignore[return-value]

    async def initialize_for_data_load(self) -> DataResetResult:
        return await self._call("initialize_for_data_load")  # type: ignore[return-value]

    async def inspect_document(self, document_id: str) -> DocumentInspection:
        return await self._call("inspect_document", document_id)  # type: ignore[return-value]

    async def list_recovery_candidates(
        self,
        *,
        status: DocumentStatus,
        offset: int = 0,
        limit: int = 100,
    ) -> list[DocumentMetadata]:
        return await self._call(
            "list_recovery_candidates",
            status=status,
            offset=offset,
            limit=limit,
        )  # type: ignore[return-value]

    async def iter_recovery_candidates(
        self,
        *,
        status: DocumentStatus,
        page_size: int = 100,
    ) -> AsyncIterator[DocumentMetadata]:
        async for item in _iterate_recovery_pages(
            self.list_recovery_candidates,
            status=status,
            page_size=page_size,
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
    ) -> ReconciliationResult:
        return await self._call(
            "reconcile_document",
            document_id,
            action,
            storage_key=storage_key,
            dry_run=dry_run,
            actor=self._actor(actor),
        )  # type: ignore[return-value]

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
        return await self._call(
            "reconcile_documents",
            status=status,
            action=action,
            offset=offset,
            limit=limit,
            dry_run=dry_run,
            actor=self._actor(actor),
        )  # type: ignore[return-value]

    async def execute_reconciliation_plan(
        self,
        plan: ReconciliationPlan,
        *,
        actor: str | None = None,
    ) -> BatchReconciliationResult:
        return await self._call(
            "execute_reconciliation_plan",
            plan,
            actor=self._actor(actor),
        )  # type: ignore[return-value]


from dms.sdk.async_sdk import AsyncDocumentManagementSDK
