from __future__ import annotations

from hashlib import sha256

import pytest

from dms import (
    AsyncUploadDocumentStreamRequest,
    AsyncUploadDocumentUnknownSizeStreamRequest,
    ConsistencyError,
    DocumentPage,
    IdempotencyInProgressError,
    MetadataStoreError,
    PayloadTooLargeError,
    UploadDocumentRequest,
    ValidationError,
    create_sdk_from_components,
    recommended_http_error,
)
from test_dms.sdk_test_support import CursorMemoryStore, StreamMemoryObjectStore


class AsyncReader:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = iter(chunks)
        self.closed = False

    async def read(self, size: int = -1) -> bytes:
        del size
        return next(self._chunks, b"")

    async def aclose(self) -> None:
        self.closed = True


def _sdk(*, close_callbacks=None):
    return create_sdk_from_components(
        metadata_store=CursorMemoryStore(),
        object_store=StreamMemoryObjectStore(),
        close_callbacks=close_callbacks,
    )


def test_recommended_http_mapping_is_transport_only_and_serializable() -> None:
    validation = recommended_http_error(ValidationError("bad cursor"))
    pending = recommended_http_error(IdempotencyInProgressError("pending"))
    storage = recommended_http_error(MetadataStoreError("database password=secret"))
    consistency = recommended_http_error(ConsistencyError("inconsistent"))

    assert validation.status == 400
    assert validation.body == {
        "code": "validation_invalid",
        "category": "validation",
        "retryable": False,
        "message": "bad cursor",
    }
    assert pending.status == 425
    assert storage.status == 503
    assert storage.body["message"] == "A storage dependency failed"
    assert consistency.status == 500
    assert recommended_http_error(PayloadTooLargeError("too large")).status == 413
    assert not hasattr(ValidationError("bad"), "http_status")


@pytest.mark.asyncio
async def test_async_known_size_upload_and_download_stream_without_closing_input() -> None:
    sdk = _sdk()
    source = AsyncReader([b"hel", b"lo"])

    result = await sdk.upload_document_async_stream(AsyncUploadDocumentStreamRequest(
        stream=source,
        size=5,
        filename="hello.txt",
        content_type="text/plain",
        checksum=sha256(b"hello").hexdigest(),
    ))

    assert source.closed is False
    async with await sdk.get_document_content_async_stream(result.document_id, chunk_size=2) as content:
        chunks = [chunk async for chunk in content.iter_chunks()]
    assert b"".join(chunks) == b"hello"
    assert content.closed is True

    unscoped = await sdk.get_document_content_async_stream(result.document_id, chunk_size=2)
    assert b"".join([chunk async for chunk in unscoped.iter_chunks()]) == b"hello"
    assert unscoped.closed is True


@pytest.mark.asyncio
async def test_async_unknown_size_upload_is_bounded_and_keeps_input_open() -> None:
    sdk = _sdk()
    source = AsyncReader([b"abc", b"def"])

    with pytest.raises(ValidationError, match="exceeds max_size"):
        await sdk.upload_document_async_unknown_size_stream(
            AsyncUploadDocumentUnknownSizeStreamRequest(
                stream=source,
                max_size=5,
                filename="too-large.txt",
                content_type="text/plain",
            )
        )
    assert source.closed is False


@pytest.mark.asyncio
async def test_sdk_async_context_closes_owned_resources_once() -> None:
    closed: list[str] = []
    sdk = _sdk(close_callbacks=[lambda: closed.append("sdk")])

    async with sdk as entered:
        assert entered is sdk

    await sdk.aclose()
    assert closed == ["sdk"]


def test_default_list_uses_cursor_page_and_offset_path_is_removed() -> None:
    sdk = _sdk()
    sdk.upload_document(UploadDocumentRequest(
        content=b"one", filename="one.txt", content_type="text/plain", document_id="one"
    ))

    default_page = sdk.list_documents()
    assert isinstance(default_page, DocumentPage)
    assert [item.document_id for item in default_page.items] == ["one"]
    assert not hasattr(sdk, "list_documents_offset")


def test_cursor_is_bound_to_page_size() -> None:
    sdk = _sdk()
    for document_id in ("a", "b", "c"):
        sdk.upload_document(UploadDocumentRequest(
            content=b"x", filename=f"{document_id}.txt", content_type="text/plain",
            document_id=document_id,
        ))

    first = sdk.list_documents(limit=1)
    with pytest.raises(ValidationError, match="page size"):
        sdk.list_documents(cursor=first.next_cursor, limit=2)
    with pytest.raises(TypeError, match="offset"):
        sdk.list_documents(cursor=first.next_cursor, offset=0, limit=1)


def test_configured_file_size_limit_has_distinct_public_error() -> None:
    sdk = create_sdk_from_components(
        metadata_store=CursorMemoryStore(),
        object_store=StreamMemoryObjectStore(),
        max_file_size=2,
    )

    with pytest.raises(PayloadTooLargeError):
        sdk.upload_document(UploadDocumentRequest(
            content=b"abc", filename="large.txt", content_type="text/plain"
        ))
