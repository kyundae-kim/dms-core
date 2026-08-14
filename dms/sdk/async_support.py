from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TypeVar

from dms.domain.models import DocumentMetadata, DocumentStatus
from dms.sdk.types import DocumentPage, PublicDocumentMetadata

_ResultT = TypeVar("_ResultT")


async def run_blocking(
    operation: Callable[..., _ResultT],
    *args: object,
    **kwargs: object,
) -> _ResultT:
    """Run blocking work off-loop and finish it before propagating cancellation."""
    task = asyncio.create_task(asyncio.to_thread(operation, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await task
        except Exception:
            raise
        raise


async def iterate_document_pages(
    fetch_page: Callable[..., Awaitable[DocumentPage]],
    *,
    status: DocumentStatus | None,
    page_size: int,
    **kwargs: object,
) -> AsyncIterator[PublicDocumentMetadata]:
    cursor: str | None = None
    while True:
        page = await fetch_page(
            cursor=cursor,
            limit=page_size,
            status=status,
            **kwargs,
        )
        for item in page.items:
            yield item
        if page.next_cursor is None:
            return
        cursor = page.next_cursor


async def iterate_recovery_pages(
    fetch_page: Callable[..., Awaitable[list[DocumentMetadata]]],
    *,
    status: DocumentStatus,
    page_size: int,
    **kwargs: object,
) -> AsyncIterator[DocumentMetadata]:
    offset = 0
    while True:
        items = await fetch_page(
            status=status,
            offset=offset,
            limit=page_size,
            **kwargs,
        )
        if not items:
            return
        for item in items:
            yield item
        if len(items) < page_size:
            return
        offset += len(items)
