from __future__ import annotations

import asyncio
from dataclasses import replace
from io import BytesIO
import logging
from typing import Any, cast

import pytest

from dms import (
    AccessContext,
    AccessDeniedError,
    DmsAssemblyPlan,
    DmsOperationContext,
    DocumentContentStream,
    DocumentStatus,
    RecoveryAction,
    StorageError,
    UploadDocumentRequest,
    ValidationError,
    create_sdk_from_components,
    recommended_http_error,
)
from dms.sdk.async_sdk import AsyncDocumentManagementSDK
from dms.sdk.contracts import ManagedResource, ResourceOwnership
from dms.sdk.lifecycle import LifecycleService
from test_dms.sdk_test_support import CursorMemoryStore, StreamMemoryObjectStore


class AdminOnlyPolicy:
    def allows(self, *, operation, context, metadata):
        return context is not None and "admin" in context.roles


def test_recovery_uses_the_authorized_context_for_internal_metadata() -> None:
    metadata = CursorMemoryStore()
    objects = StreamMemoryObjectStore()
    sdk = create_sdk_from_components(
        metadata_store=metadata,
        object_store=objects,
        plan=DmsAssemblyPlan(access_policy=AdminOnlyPolicy()),
    )
    sdk.upload_document(UploadDocumentRequest(
        document_id="failed",
        content=b"x",
        filename="x.txt",
        content_type="text/plain",
    ))
    stored = metadata.get_metadata("failed")
    objects.delete_object("failed", stored.storage_key)
    metadata.update_metadata(replace(stored, status=DocumentStatus.FAILED))

    result = sdk.reconcile_document(
        "failed",
        RecoveryAction.MARK_FAILED,
        access_context=AccessContext(roles=frozenset({"admin"})),
    )

    assert result.document_id == "failed"


def test_access_denied_errors_map_to_forbidden_http_responses() -> None:
    response = recommended_http_error(AccessDeniedError("denied"))

    assert response.status == 403


def test_recovery_input_validation_runs_before_enum_value_access() -> None:
    sdk = create_sdk_from_components(
        metadata_store=CursorMemoryStore(),
        object_store=StreamMemoryObjectStore(),
    )

    with pytest.raises(ValidationError):
        sdk.reconcile_document("missing", cast(Any, "invalid"))
    with pytest.raises(ValidationError):
        sdk.list_recovery_candidates(status=cast(Any, "failed"))
    with pytest.raises(ValidationError):
        sdk.reconcile_documents(
            status=DocumentStatus.FAILED,
            action=cast(Any, "invalid"),
        )


def test_stream_chunk_size_zero_is_rejected() -> None:
    stream = DocumentContentStream(
        document_id="document",
        stream=BytesIO(b"content"),
        content_type="text/plain",
        filename="document.txt",
        size=7,
        chunk_size=2,
    )

    with pytest.raises(ValueError, match="chunk_size"):
        list(stream.iter_chunks(0))


def test_invalid_factory_configuration_rolls_back_registered_callbacks() -> None:
    closed: list[str] = []

    with pytest.raises(ValueError):
        create_sdk_from_components(
            metadata_store=CursorMemoryStore(),
            object_store=StreamMemoryObjectStore(),
            max_file_size=0,
            close_callbacks=[lambda: closed.append("callback")],
        )

    assert closed == ["callback"]


def test_upload_file_maps_local_file_errors_to_storage_error(tmp_path) -> None:
    sdk = create_sdk_from_components(
        metadata_store=CursorMemoryStore(),
        object_store=StreamMemoryObjectStore(),
    )

    with pytest.raises(StorageError):
        sdk.upload_file(tmp_path / "does-not-exist.bin")


@pytest.mark.asyncio
async def test_async_scoped_facade_preserves_streaming_and_recovery_surface(tmp_path) -> None:
    sdk = create_sdk_from_components(
        metadata_store=CursorMemoryStore(),
        object_store=StreamMemoryObjectStore(),
    )
    path = tmp_path / "async-scoped.txt"
    path.write_bytes(b"async scoped")
    sdk.upload_file(path, document_id="async-scoped")

    async_sdk = AsyncDocumentManagementSDK(sdk)
    scoped = async_sdk.scoped(DmsOperationContext(access=AccessContext()))

    stream = await scoped.get_document_content_stream("async-scoped", chunk_size=4)
    assert b"".join([chunk async for chunk in stream.iter_chunks()]) == b"async scoped"
    assert (await scoped.inspect_document("async-scoped")).document_id == "async-scoped"
    assert (await scoped.check_health()).ok
    await async_sdk.aclose()


@pytest.mark.asyncio
async def test_direct_lifecycle_cancellation_finishes_all_async_cleanup() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    closed: list[str] = []

    async def close_after_blocking_resource() -> None:
        closed.append("blocking-start")
        started.set()
        await release.wait()
        closed.append("blocking-end")

    async def close_last_resource() -> None:
        closed.append("last")

    lifecycle = LifecycleService(
        service_checks={},
        close_callbacks=[],
        managed_resources=[
            ManagedResource(
                resource=object(),
                ownership=ResourceOwnership.SDK,
                aclose=close_last_resource,
            ),
            ManagedResource(
                resource=object(),
                ownership=ResourceOwnership.SDK,
                aclose=close_after_blocking_resource,
            ),
        ],
        logger=logging.getLogger("test.lifecycle"),
    )
    task = asyncio.create_task(lifecycle.aclose())
    await started.wait()
    task.cancel()
    await asyncio.sleep(0)
    release.set()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed == ["blocking-start", "blocking-end", "last"]
