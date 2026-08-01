from __future__ import annotations
from io import BytesIO
from typing import Any, cast
import pytest
from dms import (DefaultMetadataPolicy, UploadDocumentRequest, UploadDocumentStreamRequest, ValidationError, create_sdk_from_components)
from dms.domain.interfaces import ObjectStore, PutObjectRequest

from test_dms.sdk_test_support import InMemoryMetadataStore, InMemoryObjectStore


def _sdk(options: dict[str, Any] | None = None):
    class StreamStore(InMemoryObjectStore):
        def put_object_stream(self, request):
            content = request.stream.read()
            return self.put_object(PutObjectRequest(
                document_id=request.document_id, storage_key=request.storage_key,
                content=content, content_type=request.content_type,
                filename=request.filename, checksum=request.checksum,
                metadata=request.metadata,
            ))
    objects = cast(ObjectStore, StreamStore())
    return create_sdk_from_components(metadata_store=InMemoryMetadataStore(), object_store=objects, **(options or {}))

def test_metadata_normalizer_applies_to_bytes_and_stream_uploads():
    calls: list[object] = []
    def normalize(metadata):
        calls.append(metadata)
        return {"schema_version": "1", "normalized": True}
    sdk = _sdk({"metadata_validator": normalize})
    one = sdk.upload_document(UploadDocumentRequest(content=b"a", filename="a.txt", content_type="text/plain", metadata={"raw": 1}))
    two = sdk.upload_document_stream(UploadDocumentStreamRequest(stream=BytesIO(b"b"), size=1, filename="b.txt", content_type="text/plain", metadata={"raw": 2}))
    expected = {"schema_version": "1", "normalized": True}
    assert one.metadata.extra_metadata == two.metadata.extra_metadata == expected
    assert len(calls) == 2

def test_default_metadata_policy_rejections_and_configurable_limits():
    sdk = _sdk({"metadata_max_serialized_bytes": 20, "metadata_max_depth": 2})
    invalid: list[Any] = [{"password": "x"}, {1: "x"}, {"nested": {"too": {"deep": True}}}, {"large": "x" * 30}, {"bad": object()}]
    for metadata in invalid:
        with pytest.raises(ValidationError):
            sdk.upload_document(UploadDocumentRequest(content=b"x", filename="x", content_type="text/plain", metadata=metadata))
    assert DefaultMetadataPolicy()({"schema_version": "1", "tags": ["safe"]})["schema_version"] == "1"
