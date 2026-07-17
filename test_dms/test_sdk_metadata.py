from __future__ import annotations

from datetime import UTC, datetime

import pytest

from dms.domain.models import DocumentMetadata, DocumentStatus

from dms.sdk import MetadataSchemaValidationError, MetadataValidationIssue, PublicDocumentMetadata, RecoveryAction, RecoveryAuditEvent, StructuredMetadataValidator, UploadDocumentRequest, public_metadata

from dms.sdk.factory import create_sdk_from_components

from test_dms.sdk_test_support import CursorMemoryStore, StreamMemoryObjectStore

def test_public_metadata_projection_accepts_metadata_and_upload_result_without_storage_key():
    store, objects = (CursorMemoryStore(), StreamMemoryObjectStore())
    sdk = create_sdk_from_components(metadata_store=store, object_store=objects)
    result = sdk.upload_document(UploadDocumentRequest(content=b'x', filename='x.txt', content_type='text/plain'))
    projected = public_metadata(result)
    assert isinstance(projected, PublicDocumentMetadata)
    assert projected == public_metadata(result.metadata)
    assert not hasattr(projected, 'storage_key')
    assert projected.extra_metadata is not result.metadata.extra_metadata

def test_structured_validator_checks_version_and_preserves_field_issues():
    calls = []

    def parser(value):
        calls.append(value)
        if 'title' not in value:
            raise MetadataSchemaValidationError([MetadataValidationIssue(path=('title',), code='required', message='required')])
        return {'schema_version': value['schema_version'], 'title': str(value['title']).strip()}
    validator = StructuredMetadataValidator(parser=parser, schema_version='1')
    assert validator({'schema_version': '1', 'title': ' ok '})['title'] == 'ok'
    with pytest.raises(MetadataSchemaValidationError) as mismatch:
        validator({'schema_version': '2', 'title': 'x'})
    assert mismatch.value.issues[0].path == ('schema_version',)
    with pytest.raises(MetadataSchemaValidationError) as missing:
        validator({'schema_version': '1'})
    assert missing.value.issues[0].code == 'required'
    assert calls

def test_existing_metadata_validator_callable_remains_compatible():
    sdk = create_sdk_from_components(metadata_store=CursorMemoryStore(), object_store=StreamMemoryObjectStore(), metadata_validator=lambda value: {**value, 'normalized': True})
    result = sdk.upload_document(UploadDocumentRequest(content=b'x', filename='x', content_type='x', metadata={}))
    assert result.metadata.extra_metadata == {'normalized': True}
