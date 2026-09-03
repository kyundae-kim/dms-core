from __future__ import annotations

import inspect
from dataclasses import fields
from io import BytesIO

import dms
from dms.sdk.async_sdk import AsyncDocumentManagementSDK
from dms.sdk.implementation import DefaultDocumentManagementSDK
from test_dms.sdk_test_support import (
    DEFAULT_PARTITION,
    CursorMemoryStore,
    StreamMemoryObjectStore,
)

_REMOVED_REQUEST_TYPES = {
    "UploadDocumentBoundedStreamRequest",
    "UploadDocumentUnknownSizeStreamRequest",
    "AsyncUploadDocumentStreamRequest",
    "AsyncUploadDocumentBoundedStreamRequest",
    "AsyncUploadDocumentUnknownSizeStreamRequest",
}

_REMOVED_METHODS = {
    "upload_bytes",
    "upload_source",
    "upload_document_bounded_stream",
    "upload_document_unknown_size_stream",
    "upload_document_async_stream",
    "upload_document_async_bounded_stream",
    "upload_document_async_unknown_size_stream",
}


def test_public_upload_surface_excludes_unknown_bounded_and_async_input_streams() -> (
    None
):
    assert _REMOVED_REQUEST_TYPES.isdisjoint(vars(dms))
    assert {
        "ScopedDocumentManagementSDK",
        "AsyncScopedDocumentManagementSDK",
        "DmsOperationContext",
    }.isdisjoint(vars(dms))
    canonical_uploads = {"upload_document", "upload_file", "upload_document_stream"}
    for sdk_type in (
        DefaultDocumentManagementSDK,
        AsyncDocumentManagementSDK,
    ):
        assert "scoped" not in vars(sdk_type)
        assert _REMOVED_METHODS.isdisjoint(vars(sdk_type))
        assert canonical_uploads <= set(vars(sdk_type))


def test_known_size_stream_request_has_only_the_minimal_stream_contract() -> None:
    assert [field.name for field in fields(dms.UploadDocumentStreamRequest)] == [
        "stream",
        "size",
        "filename",
        "content_type",
        "document_id",
        "metadata",
        "created_by",
    ]


def test_file_upload_uses_sdk_size_policy_instead_of_request_upload_controls() -> None:
    parameters = inspect.signature(DefaultDocumentManagementSDK.upload_file).parameters

    assert "max_size" not in parameters
    assert "checksum" not in parameters
    assert "idempotency_key" not in parameters
    assert "idempotency_scope" not in parameters


def test_bytes_file_and_known_size_stream_uploads_remain_supported(tmp_path) -> None:
    sdk = dms.DefaultDocumentManagementSDK(
        metadata_store=CursorMemoryStore(),
        object_store=StreamMemoryObjectStore(),
    )
    path = tmp_path / "file.txt"
    path.write_bytes(b"file")
    stream = BytesIO(b"stream")

    bytes_result = sdk.upload_document(
        dms.UploadDocumentRequest(
            content=b"bytes",
            filename="bytes.txt",
            content_type="text/plain",
            document_id="bytes",
        ),
        partition=DEFAULT_PARTITION,
    )
    file_result = sdk.upload_file(path, document_id="file", partition=DEFAULT_PARTITION)
    stream_result = sdk.upload_document_stream(
        dms.UploadDocumentStreamRequest(
            stream=stream,
            size=6,
            filename="stream.txt",
            content_type="text/plain",
            document_id="stream",
        ),
        partition=DEFAULT_PARTITION,
    )

    assert (
        sdk.get_document_content(
            bytes_result.document_id, partition=DEFAULT_PARTITION
        ).content
        == b"bytes"
    )
    assert (
        sdk.get_document_content(
            file_result.document_id, partition=DEFAULT_PARTITION
        ).content
        == b"file"
    )
    assert (
        sdk.get_document_content(
            stream_result.document_id, partition=DEFAULT_PARTITION
        ).content
        == b"stream"
    )
    assert stream.closed is False
