from __future__ import annotations

from hashlib import sha256
from io import BytesIO

import pytest
from sqlalchemy import create_engine

from dms import IdempotencyConflictError, UploadDocumentRequest, UploadDocumentStreamRequest
from dms.domain.interfaces import PutObjectRequest, PutObjectStreamRequest
from dms.domain.models import UploadOperationState
from dms.infrastructure.metadata.operations import SqlAlchemyUploadOperationStore
from dms.sdk.errors import ValidationError
from dms.sdk.factory import create_sdk_from_components
from test_dms.test_sdk_behavior import InMemoryMetadataStore, InMemoryObjectStore


class StreamingObjectStore(InMemoryObjectStore):
    def put_object_stream(self, request: PutObjectStreamRequest) -> str:
        content = request.stream.read()
        return self.put_object(
            PutObjectRequest(
                document_id=request.document_id,
                storage_key=request.storage_key,
                content=content,
                content_type=request.content_type,
                filename=request.filename,
                checksum=request.checksum,
                metadata=request.metadata,
            )
        )


def test_sqlite_claim_is_persistent_and_atomic(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'ops.db'}")
    first = SqlAlchemyUploadOperationStore(engine)
    claim = first.claim(scope="alice", idempotency_key="key", fingerprint="fp", document_id="doc")
    assert claim.claimed is True
    second = SqlAlchemyUploadOperationStore(engine)
    replay = second.claim(scope="alice", idempotency_key="key", fingerprint="fp", document_id="other")
    assert replay.claimed is False
    assert replay.operation.state is UploadOperationState.PENDING
    assert replay.operation.document_id == "doc"


def test_sqlite_failed_operation_is_retried_with_same_document_id(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'ops.db'}")
    store = SqlAlchemyUploadOperationStore(engine)
    store.claim(scope="anonymous", idempotency_key="key", fingerprint="fp", document_id="doc")
    store.mark_failed(scope="anonymous", idempotency_key="key")
    retried = store.claim(scope="anonymous", idempotency_key="key", fingerprint="fp", document_id="new")
    assert retried.claimed is True
    assert retried.operation.document_id == "doc"
    assert retried.operation.state is UploadOperationState.PENDING


def test_request_contract_has_idempotency_key():
    assert UploadDocumentRequest(content=b"x", filename="x", content_type="text/plain", idempotency_key="k").idempotency_key == "k"
    assert UploadDocumentStreamRequest(stream=BytesIO(b"x"), size=1, filename="x", content_type="text/plain", checksum="0" * 64, idempotency_key="k").idempotency_key == "k"


def test_bytes_replay_conflict_pending_and_scope(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'sdk.db'}")
    operations = SqlAlchemyUploadOperationStore(engine)
    metadata, objects = InMemoryMetadataStore(), InMemoryObjectStore()
    sdk = create_sdk_from_components(metadata_store=metadata, object_store=objects,
                                     operation_store=operations, id_generator=lambda: "doc-1")
    request = UploadDocumentRequest(content=b"hello", filename="a.txt", content_type="text/plain",
                                    created_by="alice", idempotency_key="same")
    assert sdk.upload_document(request).created is True
    assert sdk.upload_document(request).created is False
    assert len(objects._items) == 1
    with pytest.raises(IdempotencyConflictError):
        sdk.upload_document(UploadDocumentRequest(content=b"other", filename="a.txt",
            content_type="text/plain", created_by="alice", idempotency_key="same"))

    operations.claim(scope="alice", idempotency_key="pending", fingerprint="irrelevant", document_id="p")
    # Store-level atomic pending behavior is asserted without relying on process memory.
    pending = operations.claim(scope="alice", idempotency_key="pending", fingerprint="irrelevant", document_id="q")
    assert pending.claimed is False and pending.operation.state is UploadOperationState.PENDING

    # Same key in another creator scope is independent.
    other = UploadDocumentRequest(content=b"hello", filename="a.txt", content_type="text/plain",
                                  created_by="bob", idempotency_key="same", document_id="doc-2")
    assert sdk.upload_document(other).created is True


def test_stream_requires_checksum_before_read_and_replays(tmp_path):
    operations = SqlAlchemyUploadOperationStore(create_engine(f"sqlite:///{tmp_path / 'stream.db'}"))
    sdk = create_sdk_from_components(metadata_store=InMemoryMetadataStore(),
        object_store=StreamingObjectStore(), operation_store=operations, id_generator=lambda: "stream-doc")
    unread = BytesIO(b"abc")
    with pytest.raises(ValidationError, match="checksum is required"):
        sdk.upload_document_stream(UploadDocumentStreamRequest(stream=unread, size=3,
            filename="x", content_type="text/plain", idempotency_key="key"))
    assert unread.tell() == 0

    checksum = sha256(b"abc").hexdigest()
    first = UploadDocumentStreamRequest(stream=BytesIO(b"abc"), size=3, filename="x",
        content_type="text/plain", checksum=checksum, idempotency_key="stream-key")
    assert sdk.upload_document_stream(first).created is True
    replay_stream = BytesIO(b"abc")
    replay = UploadDocumentStreamRequest(stream=replay_stream, size=3, filename="x",
        content_type="text/plain", checksum=checksum, idempotency_key="stream-key")
    assert sdk.upload_document_stream(replay).created is False
    assert replay_stream.tell() == 0
