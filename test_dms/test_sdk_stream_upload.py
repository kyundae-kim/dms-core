from __future__ import annotations

from datetime import UTC, datetime

from io import BytesIO

import pytest

from sqlalchemy import create_engine

from dms.domain.models import DocumentStatus, UploadOperationState

from dms.infrastructure.metadata.operations import SqlAlchemyUploadOperationStore

from dms.sdk import BatchReconciliationResult, RecoveryAction, ReconciliationResult, UploadDocumentUnknownSizeStreamRequest, UploadOperationNotFoundError, UploadOperationResult, ValidationError

from dms.sdk.factory import create_sdk_from_components

from dms.sdk.types import DocumentInspection, RecoveryIssue

from test_dms.sdk_test_support import CursorMemoryStore, StreamMemoryObjectStore

def _sdk(*, operation_store=None, metadata_store=None):
    return create_sdk_from_components(metadata_store=metadata_store or CursorMemoryStore(), object_store=StreamMemoryObjectStore(), operation_store=operation_store)

def test_unknown_size_upload_spools_hashes_bounds_and_closes_spool(monkeypatch):
    sdk = _sdk()
    observed = {}
    original = sdk.upload_document_stream

    def recording(request):
        observed['size'] = request.size
        observed['checksum'] = request.checksum
        observed['stream'] = request.stream
        return original(request)
    monkeypatch.setattr(sdk, 'upload_document_stream', recording)
    result = sdk.upload_document_unknown_size_stream(UploadDocumentUnknownSizeStreamRequest(stream=BytesIO(b'payload'), max_size=7, filename='x.bin', content_type='application/octet-stream', document_id='doc', chunk_size=2))
    assert result.metadata.file_size == 7
    assert observed['size'] == 7
    assert observed['checksum'] == '239f59ed55e737c77147cf55ad0c1b030b6d7ee748a7426952f9b852d5a935e5'
    assert observed['stream'].closed
    with pytest.raises(ValidationError, match='max_size'):
        sdk.upload_document_unknown_size_stream(UploadDocumentUnknownSizeStreamRequest(stream=BytesIO(b'x'), max_size=0, filename='x', content_type='x'))
    with pytest.raises(ValidationError, match='exceeds max_size'):
        sdk.upload_document_unknown_size_stream(UploadDocumentUnknownSizeStreamRequest(stream=BytesIO(b'too large'), max_size=3, filename='x', content_type='x'))
