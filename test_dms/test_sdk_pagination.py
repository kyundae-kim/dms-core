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

def _sdk(metadata_store=None, operation_store=None):
    return create_sdk_from_components(metadata_store=metadata_store or CursorMemoryStore(), object_store=StreamMemoryObjectStore(), operation_store=operation_store)

def _request(document_id: str, **kwargs):
    return UploadDocumentRequest(document_id=document_id, content=b'x', filename=f'{document_id}.txt', content_type='text/plain', **kwargs)

def test_cursor_page_is_stable_opaque_and_status_bound():
    store = CursorMemoryStore()
    sdk = _sdk(store)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for index, document_id in enumerate(('a', 'b', 'c', 'd')):
        sdk.upload_document(_request(document_id))
        item = store.get_metadata(document_id)
        store.update_metadata(replace(item, created_at=base + timedelta(seconds=index // 2)))
    first = sdk.list_documents_page(limit=2, status=DocumentStatus.AVAILABLE)
    assert isinstance(first, DocumentPage)
    assert [item.document_id for item in first.items] == ['d', 'c']
    assert first.has_more is True and isinstance(first.next_cursor, str)
    assert '2026' not in first.next_cursor
    second = sdk.list_documents_page(limit=2, cursor=first.next_cursor, status=DocumentStatus.AVAILABLE)
    assert [item.document_id for item in second.items] == ['b', 'a']
    assert second.has_more is False and second.next_cursor is None
    with pytest.raises(ValidationError):
        sdk.list_documents_page(cursor=first.next_cursor, status=DocumentStatus.DELETED)
    with pytest.raises(ValidationError):
        sdk.list_documents_page(cursor='not-a-cursor')

@pytest.mark.parametrize('store_type', [PostgresMetadataStore, SqliteMetadataStore])
def test_sql_adapters_cursor_on_created_at_and_document_id(store_type):
    store = store_type(create_engine('sqlite+pysqlite:///:memory:'))
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for document_id in ('a', 'b', 'c'):
        metadata = store.build_metadata(document_id=document_id, filename='x', content_type='text/plain', file_size=1, storage_key=document_id, checksum=None, created_by=None)
        store.save_metadata(replace(metadata, created_at=base))
    first = store.list_metadata_page(limit=2, status=DocumentStatus.AVAILABLE)
    second = store.list_metadata_page(after_created_at=first[-1].created_at, after_document_id=first[-1].document_id, limit=2, status=DocumentStatus.AVAILABLE)
    assert [item.document_id for item in first] == ['c', 'b']
    assert [item.document_id for item in second] == ['a']
