from __future__ import annotations

import pytest

from dms import (
    DefaultDocumentManagementSDK,
    DocumentPage,
    PayloadTooLargeError,
    UploadDocumentRequest,
    ValidationError,
)
from test_dms.sdk_test_support import (
    DEFAULT_PARTITION,
    CursorMemoryStore,
    StreamMemoryObjectStore,
)


def _sdk():
    return DefaultDocumentManagementSDK(
        metadata_store=CursorMemoryStore(),
        object_store=StreamMemoryObjectStore(),
    )


@pytest.mark.asyncio
async def test_async_download_stream_closes_on_context_exit_and_exhaustion() -> None:
    sdk = _sdk()
    result = sdk.upload_document(
        UploadDocumentRequest(
            content=b"hello",
            filename="hello.txt",
            content_type="text/plain",
        ),
        partition=DEFAULT_PARTITION,
    )

    async with await sdk.get_document_content_async_stream(
        result.document_id, chunk_size=2, partition=DEFAULT_PARTITION
    ) as content:
        chunks = [chunk async for chunk in content.iter_chunks()]
    assert b"".join(chunks) == b"hello"
    assert content.closed is True

    unscoped = await sdk.get_document_content_async_stream(
        result.document_id, chunk_size=2, partition=DEFAULT_PARTITION
    )
    assert b"".join([chunk async for chunk in unscoped.iter_chunks()]) == b"hello"
    assert unscoped.closed is True


def test_default_list_uses_cursor_page_and_offset_path_is_removed() -> None:
    sdk = _sdk()
    sdk.upload_document(
        UploadDocumentRequest(
            content=b"one",
            filename="one.txt",
            content_type="text/plain",
            document_id="one",
        ),
        partition=DEFAULT_PARTITION,
    )

    default_page = sdk.list_documents(partition=DEFAULT_PARTITION)
    assert isinstance(default_page, DocumentPage)
    assert [item.document_id for item in default_page.items] == ["one"]
    assert not hasattr(sdk, "list_documents_offset")


def test_cursor_is_bound_to_page_size() -> None:
    sdk = _sdk()
    for document_id in ("a", "b", "c"):
        sdk.upload_document(
            UploadDocumentRequest(
                content=b"x",
                filename=f"{document_id}.txt",
                content_type="text/plain",
                document_id=document_id,
            ),
            partition=DEFAULT_PARTITION,
        )

    first = sdk.list_documents(limit=1, partition=DEFAULT_PARTITION)
    with pytest.raises(ValidationError, match="page size"):
        sdk.list_documents(
            cursor=first.next_cursor, limit=2, partition=DEFAULT_PARTITION
        )
    with pytest.raises(TypeError, match="offset"):
        sdk.list_documents(
            cursor=first.next_cursor, offset=0, limit=1, partition=DEFAULT_PARTITION
        )


def test_configured_file_size_limit_has_distinct_public_error() -> None:
    sdk = DefaultDocumentManagementSDK(
        metadata_store=CursorMemoryStore(),
        object_store=StreamMemoryObjectStore(),
        max_file_size=2,
    )

    with pytest.raises(PayloadTooLargeError):
        sdk.upload_document(
            UploadDocumentRequest(
                content=b"abc", filename="large.txt", content_type="text/plain"
            ),
            partition=DEFAULT_PARTITION,
        )
