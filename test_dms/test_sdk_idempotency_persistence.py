from __future__ import annotations

import pytest
from sqlalchemy import create_engine

from dms import IdempotencyConflictError, UploadDocumentRequest
from dms.domain.models import UploadOperationState
from dms.infrastructure.metadata.operations import SqlAlchemyUploadOperationStore

from dms.sdk.factory import create_sdk_from_components
from test_dms.sdk_test_support import InMemoryMetadataStore, InMemoryObjectStore



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


def test_bytes_request_contract_has_idempotency_key():
    assert UploadDocumentRequest(content=b"x", filename="x", content_type="text/plain", idempotency_key="k").idempotency_key == "k"


def test_bytes_replay_conflict_pending_and_scope(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'sdk.db'}")
    operations = SqlAlchemyUploadOperationStore(engine)
    metadata, objects = InMemoryMetadataStore(), InMemoryObjectStore()
    sdk = create_sdk_from_components(metadata_store=metadata, object_store=objects,
                                     operation_store=operations, id_generator=lambda: "doc-1")
    request = UploadDocumentRequest(content=b"hello", filename="a.txt", content_type="text/plain",
                                    created_by="alice", idempotency_key="same",
                                    idempotency_scope="alice")
    assert sdk.upload_document(request).created is True
    assert sdk.upload_document(request).created is False
    assert len(objects._items) == 1
    with pytest.raises(IdempotencyConflictError):
        sdk.upload_document(UploadDocumentRequest(content=b"other", filename="a.txt",
            content_type="text/plain", created_by="alice", idempotency_key="same",
            idempotency_scope="alice"))

    operations.claim(scope="alice", idempotency_key="pending", fingerprint="irrelevant", document_id="p")
    # Store-level atomic pending behavior is asserted without relying on process memory.
    pending = operations.claim(scope="alice", idempotency_key="pending", fingerprint="irrelevant", document_id="q")
    assert pending.claimed is False and pending.operation.state is UploadOperationState.PENDING

    # Same key in another creator scope is independent.
    other = UploadDocumentRequest(content=b"hello", filename="a.txt", content_type="text/plain",
                                  created_by="bob", idempotency_key="same",
                                  idempotency_scope="bob", document_id="doc-2")
    assert sdk.upload_document(other).created is True
