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

from test_dms.sdk_test_support import InMemoryMetadataStore, InMemoryObjectStore
from test_dms.sdk_test_support import CursorMemoryStore, RecordingOperationStore, StreamMemoryObjectStore

def _sdk(metadata_store=None, operation_store=None):
    return create_sdk_from_components(metadata_store=metadata_store or CursorMemoryStore(), object_store=StreamMemoryObjectStore(), operation_store=operation_store)

def _request(document_id: str, **kwargs):
    return UploadDocumentRequest(document_id=document_id, content=b'x', filename=f'{document_id}.txt', content_type='text/plain', **kwargs)

def test_explicit_delete_methods_preserve_legacy_dispatch():
    sdk = _sdk()
    sdk.upload_document(_request('soft'))
    sdk.upload_document(_request('hard'))
    sdk.upload_document(_request('legacy'))
    assert sdk.soft_delete_document('soft').hard_deleted is False
    assert sdk.hard_delete_document('hard').hard_deleted is True
    assert sdk.delete_document('legacy', hard_delete=True).hard_deleted is True
