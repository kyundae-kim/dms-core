from __future__ import annotations

import asyncio
import inspect
import json
import threading
from datetime import UTC, datetime
from io import BytesIO

import pytest

from dms.domain.interfaces import PutObjectRequest
from dms import (
    AsyncDocumentContentStream,
    AsyncDocumentManagementSDK,
    DeleteDocumentResult,
    DocumentContentStream,
    DocumentPage,
    DocumentStatus,

    PublicDocumentMetadata,

    UploadDocumentRequest,
    UploadDocumentResult,
    DefaultDocumentManagementSDK,
)
from test_dms.sdk_test_support import CursorMemoryStore, StreamMemoryObjectStore


def _content_stream(
    content: bytes = b"abcdef",
    *,
    close_callback=None,
) -> DocumentContentStream:
    return DocumentContentStream(
        document_id="doc",
        stream=BytesIO(content),
        content_type="application/octet-stream",
        filename="doc.bin",
        size=len(content),
        chunk_size=2,
        _close_callback=close_callback,
    )


def test_sync_closing_iterator_closes_on_exhaustion_and_explicit_early_stop() -> None:
    exhausted_closes: list[str] = []
    exhausted = _content_stream(close_callback=lambda: exhausted_closes.append("closed"))

    assert b"".join(exhausted.iter_chunks_closing()) == b"abcdef"
    assert exhausted_closes == ["closed"]

    partial_closes: list[str] = []
    partial = _content_stream(close_callback=lambda: partial_closes.append("closed"))
    iterator = partial.iter_chunks_closing()
    assert next(iterator) == b"ab"
    iterator.close()
    iterator.close()
    assert partial_closes == ["closed"]


def test_sync_closing_iterator_preserves_read_error_when_close_also_fails() -> None:
    class FailingReader:
        def read(self, size: int = -1) -> bytes:
            del size
            raise RuntimeError("read failed")

        def close(self) -> None:
            raise ValueError("close failed")

    stream = DocumentContentStream(
        document_id="doc",
        stream=FailingReader(),
        content_type="application/octet-stream",
        filename="doc.bin",
        size=1,
    )

    with pytest.raises(RuntimeError, match="read failed"):
        list(stream.iter_chunks_closing())


@pytest.mark.asyncio
async def test_async_closing_iterator_closes_on_exhaustion_and_explicit_early_stop() -> None:
    exhausted = AsyncDocumentContentStream(document_id="doc", _source=_content_stream())
    assert b"".join([chunk async for chunk in exhausted.aiter_chunks_closing()]) == b"abcdef"
    assert exhausted.closed is True

    partial = AsyncDocumentContentStream(
        document_id="doc", _source=_content_stream(), chunk_size=2
    )
    iterator = partial.aiter_chunks_closing()
    assert await anext(iterator) == b"ab"
    await iterator.aclose()
    await iterator.aclose()
    assert partial.closed is True


def test_canonical_public_dtos_dump_with_external_metadata_alias() -> None:
    now = datetime(2026, 8, 1, 10, 30, tzinfo=UTC)
    metadata = PublicDocumentMetadata(
        document_id="doc",
        original_filename="doc.txt",
        content_type="text/plain",
        file_size=3,
        status=DocumentStatus.AVAILABLE,
        created_at=now,
        updated_at=now,
        extra_metadata={"nested": [1, True]},
    )
    upload = UploadDocumentResult(document_id="doc", metadata=metadata)
    page = DocumentPage(items=[metadata], next_cursor=None, has_more=False)
    deleted = DeleteDocumentResult(
        document_id="doc",
        deleted=True,
        hard_deleted=False,
        status=DocumentStatus.DELETED,
    )

    metadata_dump = metadata.to_public_dict()
    assert metadata_dump["metadata"] == {"nested": [1, True]}
    assert "extra_metadata" not in metadata_dump
    assert upload.to_dict() == {
        "document_id": "doc",
        "metadata": metadata_dump,
        "created": True,
    }
    assert page.to_dict() == {
        "items": [metadata_dump],
        "next_cursor": None,
        "has_more": False,
    }
    assert deleted.to_dict()["status"] == "deleted"
    json.dumps(upload.to_dict())
    json.dumps(page.to_dict())


@pytest.mark.parametrize(
    "model_type",
    [PublicDocumentMetadata, UploadDocumentResult, DocumentPage, DeleteDocumentResult],
)
def test_canonical_public_dtos_export_matching_json_schema(model_type: type[object]) -> None:
    schema = model_type.json_schema()

    assert schema["type"] == "object"
    assert "storage_key" not in json.dumps(schema)
    assert model_type.model_json_schema() == schema

    if model_type is PublicDocumentMetadata:
        assert "metadata" in schema["properties"]
        assert "extra_metadata" not in schema["properties"]


def test_async_facade_exposes_awaitable_counterparts_for_all_public_sdk_operations() -> None:
    expected_methods = {
        "upload_document",
        "upload_file",
        "upload_document_stream",
        "get_upload_operation",
        "get_internal_document_metadata",
        "get_document_metadata",
        "list_documents",
        "list_documents_page",
        "inspect_document",
        "list_recovery_candidates",
        "reconcile_document",
        "execute_reconciliation_plan",
        "reconcile_documents",
        "get_document_content",
        "get_document_content_stream",
        "get_document_content_async_stream",
        "delete_document",
        "soft_delete_document",
        "hard_delete_document",
        "clear_all_data",
        "initialize_for_data_load",
    }

    assert expected_methods <= set(vars(AsyncDocumentManagementSDK))
    assert all(
        inspect.iscoroutinefunction(getattr(AsyncDocumentManagementSDK, method))
        for method in expected_methods
    )


@pytest.mark.asyncio
async def test_async_facade_runs_metadata_list_delete_without_global_lifecycle() -> None:
    sync_sdk = DefaultDocumentManagementSDK(
        metadata_store=CursorMemoryStore(), object_store=StreamMemoryObjectStore()
    )
    sdk = AsyncDocumentManagementSDK(sync_sdk)

    uploaded = await sdk.upload_document(
        UploadDocumentRequest(
            content=b"payload",
            filename="payload.txt",
            content_type="text/plain",
        )
    )
    metadata = await sdk.get_document_metadata(uploaded.document_id)
    page = await sdk.list_documents(limit=10)
    content = await sdk.get_document_content(uploaded.document_id)
    inspection = await sdk.inspect_document(uploaded.document_id)
    deleted = await sdk.soft_delete_document(uploaded.document_id)


    assert metadata.document_id == uploaded.document_id
    assert page.items == [metadata]
    assert content.content == b"payload"
    assert inspection.document_id == uploaded.document_id
    assert deleted.status is DocumentStatus.DELETED



def test_async_facade_factory_wraps_component_assembly() -> None:
    sdk = AsyncDocumentManagementSDK(
        DefaultDocumentManagementSDK(
            metadata_store=CursorMemoryStore(), object_store=StreamMemoryObjectStore()
        )
    )

    assert isinstance(sdk, AsyncDocumentManagementSDK)


@pytest.mark.asyncio
async def test_async_facade_cancellation_waits_for_mutation_final_state() -> None:
    started = threading.Event()
    release = threading.Event()

    class BlockingObjectStore(StreamMemoryObjectStore):
        def put_object(self, request: PutObjectRequest) -> str:
            started.set()
            assert release.wait(timeout=2)
            return super().put_object(request)

    sync_sdk = DefaultDocumentManagementSDK(
        metadata_store=CursorMemoryStore(), object_store=BlockingObjectStore()
    )
    sdk = AsyncDocumentManagementSDK(sync_sdk)
    upload = asyncio.create_task(sdk.upload_document(UploadDocumentRequest(
        document_id="cancelled-call",
        content=b"payload",
        filename="payload.txt",
        content_type="text/plain",
    )))

    assert await asyncio.to_thread(started.wait, 1)
    upload.cancel()
    await asyncio.sleep(0)
    assert upload.done() is False
    release.set()

    with pytest.raises(asyncio.CancelledError):
        await upload
    assert (await sdk.get_document_metadata("cancelled-call")).document_id == "cancelled-call"
