from __future__ import annotations

from dataclasses import replace
from io import BytesIO
from typing import Any, cast

import pytest

from dms import (
    AccessContext,
    DmsOperationContext,
    DocumentContentStream,
    DocumentStatus,
    RecoveryAction,
    StorageError,
    UploadDocumentRequest,
    ValidationError,
    create_sdk_from_components,
)
from dms.sdk.async_sdk import AsyncDocumentManagementSDK
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
        access_policy=AdminOnlyPolicy(),
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


def test_invalid_factory_configuration_is_rejected_without_resource_ownership() -> None:
    with pytest.raises(ValueError):
        create_sdk_from_components(
            metadata_store=CursorMemoryStore(),
            object_store=StreamMemoryObjectStore(),
            max_file_size=0,
        )


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
