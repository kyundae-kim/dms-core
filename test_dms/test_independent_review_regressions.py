from __future__ import annotations

import base64
import json
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from io import BytesIO

import pytest

from dms.domain.models import DocumentStatus
from dms.sdk import (
    DefaultMetadataPolicy,
    ReconciliationPlan,
    ReconciliationPlanItem,
    RecoveryAction,
    StructuredMetadataValidator,
    UploadDocumentUnknownSizeStreamRequest,
    ValidationError,
    public_metadata,
)
from dms.sdk.factory import create_sdk_from_components
from test_dms.sdk_test_support import CursorMemoryStore, StreamMemoryObjectStore, metadata


def sdk(**kwargs):
    return create_sdk_from_components(
        metadata_store=kwargs.pop("metadata_store", CursorMemoryStore()),
        object_store=kwargs.pop("object_store", StreamMemoryObjectStore()),
        **kwargs,
    )


def cursor(value: object) -> str:
    raw = json.dumps(value, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


@pytest.mark.parametrize("value", [
    [], {"v": 1, "t": datetime.now(UTC).isoformat(), "i": "d", "s": None, "extra": 1},
    {"v": True, "t": datetime.now(UTC).isoformat(), "i": "d", "s": None},
    {"v": 1, "t": datetime.now().isoformat(), "i": "d", "s": None},
    {"v": 1, "t": datetime.now(UTC).isoformat(), "i": "", "s": None},
    {"v": 1, "t": datetime.now(UTC).isoformat(), "i": "d", "s": "bogus"},
])
def test_cursor_rejects_noncanonical_schema_and_values(value):
    with pytest.raises(ValidationError, match="invalid document list cursor"):
        sdk().list_documents_page(cursor=cursor(value))


def test_cursor_and_page_limits_are_bounded():
    client = sdk()
    with pytest.raises(ValidationError):
        client.list_documents_page(cursor="a" * 4097)
    with pytest.raises(ValidationError, match="between 1 and 1000"):
        client.list_documents_page(limit=1001)


def test_unknown_size_spool_has_fixed_threshold_and_pre_read_bounds(monkeypatch):
    import dms.sdk.implementation as implementation

    observed: dict[str, int] = {}
    real = implementation.SpooledTemporaryFile
    def recording(*, max_size, mode):
        observed["threshold"] = max_size
        return real(max_size=max_size, mode=mode)
    monkeypatch.setattr(implementation, "SpooledTemporaryFile", recording)
    client = sdk(max_file_size=20_000_000)
    client.upload_document_unknown_size_stream(UploadDocumentUnknownSizeStreamRequest(
        stream=BytesIO(b"x"), max_size=10_000_000, filename="x", content_type="x"))
    assert observed["threshold"] == 1_048_576

    stream = BytesIO(b"must not read")
    with pytest.raises(ValidationError, match="configured max_file_size"):
        sdk(max_file_size=4).upload_document_unknown_size_stream(
            UploadDocumentUnknownSizeStreamRequest(stream=stream, max_size=5, filename="x", content_type="x"))
    assert stream.tell() == 0
    with pytest.raises(ValidationError, match="chunk_size"):
        client.upload_document_unknown_size_stream(UploadDocumentUnknownSizeStreamRequest(
            stream=BytesIO(b"x"), max_size=1, chunk_size=1_048_577, filename="x", content_type="x"))


def test_structured_metadata_always_applies_configurable_default_policy():
    validator = StructuredMetadataValidator(
        parser=lambda value: {**value, "nested": {"token": "secret"}},
        schema_version="1",
    )
    with pytest.raises(ValueError, match="blocked"):
        validator({"schema_version": "1"})
    tiny = StructuredMetadataValidator(parser=lambda value: value, schema_version="1",
        policy=DefaultMetadataPolicy(max_serialized_bytes=10))
    with pytest.raises(ValueError, match="serialized bytes"):
        tiny({"schema_version": "1"})


def test_public_metadata_deep_copies_nested_values():
    source = metadata()
    source.extra_metadata["nested"] = {"values": [1]}
    projected = public_metadata(source)
    projected.extra_metadata["nested"]["values"].append(2)
    assert source.extra_metadata["nested"] == {"values": [1]}


def test_plan_is_immutable_action_bound_and_preserves_empty_batch_origin(monkeypatch):
    plan = ReconciliationPlan(status=DocumentStatus.DELETING,
        action=RecoveryAction.COMPLETE_DELETION_SOFT, items=())
    result = sdk().execute_reconciliation_plan(plan)
    assert result.status is DocumentStatus.DELETING
    assert result.action is RecoveryAction.COMPLETE_DELETION_SOFT
    assert result.items == []
    with pytest.raises(FrozenInstanceError):
        plan.items = ()
    with pytest.raises(ValueError, match="plan action"):
        ReconciliationPlan(status=DocumentStatus.FAILED, action=RecoveryAction.MARK_FAILED,
            items=(ReconciliationPlanItem(document_id="d", action=RecoveryAction.COMPLETE_DELETION_SOFT),))


def test_plan_execution_catches_unexpected_item_errors_and_continues(monkeypatch):
    client = sdk()
    plan = ReconciliationPlan(status=DocumentStatus.FAILED, action=RecoveryAction.MARK_FAILED,
        items=(ReconciliationPlanItem(document_id="a", action=RecoveryAction.MARK_FAILED),
               ReconciliationPlanItem(document_id="b", action=RecoveryAction.MARK_FAILED)))
    calls = []
    def fail(document_id, action, **kwargs):
        calls.append(document_id)
        raise RuntimeError("boom")
    monkeypatch.setattr(client, "reconcile_document", fail)
    monkeypatch.setattr(client, "inspect_document", lambda document_id: (_ for _ in ()).throw(RuntimeError("down")))
    result = client.execute_reconciliation_plan(plan)
    assert calls == ["a", "b"]
    assert [item.error_type for item in result.items] == ["RuntimeError", "RuntimeError"]
    assert all(item.inspection is None for item in result.items)
