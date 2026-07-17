from __future__ import annotations

from dataclasses import replace

from datetime import UTC, datetime, timedelta

from io import BytesIO

import warnings

import pytest

from sqlalchemy import create_engine

from dms.domain.interfaces import PutObjectRequest

from dms.domain.models import DocumentStatus, UploadOperation, UploadOperationClaim, UploadOperationState

from dms.infrastructure.metadata.postgres import PostgresMetadataStore

from dms.infrastructure.metadata.sqlite import SqliteMetadataStore

from dms.sdk import DocumentPage, UploadDocumentRequest, UploadDocumentStreamRequest

from dms.sdk.errors import ValidationError

from dms.sdk.factory import create_sdk_from_components

from test_dms.test_sdk_behavior import InMemoryMetadataStore, InMemoryObjectStore
from test_dms.sdk_test_support import CursorMemoryStore, RecordingOperationStore, StreamMemoryObjectStore

from datetime import UTC, datetime

from dms.domain.models import DocumentStatus, UploadOperationState

from dms.infrastructure.metadata.operations import SqlAlchemyUploadOperationStore

from dms.sdk import BatchReconciliationResult, RecoveryAction, ReconciliationResult, UploadDocumentUnknownSizeStreamRequest, UploadOperationNotFoundError, UploadOperationResult, ValidationError

from dms.sdk.types import DocumentInspection, RecoveryIssue

from test_dms.sdk_test_support import CursorMemoryStore, StreamMemoryObjectStore

def _sdk(metadata_store=None, operation_store=None):
    return create_sdk_from_components(metadata_store=metadata_store or CursorMemoryStore(), object_store=StreamMemoryObjectStore(), operation_store=operation_store)

def _request(document_id: str, **kwargs):
    return UploadDocumentRequest(document_id=document_id, content=b'x', filename=f'{document_id}.txt', content_type='text/plain', **kwargs)

def test_explicit_idempotency_scope_on_both_request_types_and_fallback_warning():
    operations = RecordingOperationStore()
    sdk = _sdk(operation_store=operations)
    sdk.upload_document(_request('bytes', idempotency_key='k1', idempotency_scope='tenant-a'))
    checksum = '2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881'
    sdk.upload_document_stream(UploadDocumentStreamRequest(document_id='stream', stream=BytesIO(b'x'), size=1, filename='stream.txt', content_type='text/plain', checksum=checksum, idempotency_key='k2', idempotency_scope='tenant-b'))
    assert operations.scopes == ['tenant-a', 'tenant-b']
    with pytest.warns(DeprecationWarning, match='idempotency_scope'):
        sdk.upload_document(_request('fallback', idempotency_key='k3', created_by='legacy-user'))
    assert operations.scopes[-1] == 'legacy-user'
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        _sdk().upload_document(_request('ordinary'))
    assert caught == []

def test_scope_aware_upload_operation_read_and_missing_contract():
    operations = SqlAlchemyUploadOperationStore(create_engine('sqlite+pysqlite:///:memory:'))
    claim = operations.claim(scope='tenant-a', idempotency_key='key', fingerprint='f', document_id='doc')
    sdk = _sdk(operation_store=operations)
    result = sdk.get_upload_operation(scope='tenant-a', idempotency_key='key')
    assert isinstance(result, UploadOperationResult)
    assert result.scope == 'tenant-a' and result.idempotency_key == 'key'
    assert result.document_id == claim.operation.document_id
    assert result.state is UploadOperationState.PENDING
    assert not hasattr(result, 'fingerprint')
    with pytest.raises(UploadOperationNotFoundError):
        sdk.get_upload_operation(scope='other', idempotency_key='key')
    with pytest.raises(ValidationError):
        sdk.get_upload_operation(scope='', idempotency_key='key')
