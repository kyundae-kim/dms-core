from __future__ import annotations

from datetime import UTC, datetime
import inspect

import pytest

from dms import DocumentStatus, ValidationError
from dms.sdk.errors import DocumentNotFoundError
from dms.sdk.idempotency import build_upload_fingerprint
from dms.sdk.pagination import decode_cursor, encode_cursor
from dms.sdk.implementation import DefaultDocumentManagementSDK
from test_dms.sdk_test_support import (
    CursorMemoryStore,
    StreamMemoryObjectStore,
    metadata as make_metadata,
)










def test_sdk_document_responsibility_has_a_service_boundary() -> None:
    from dms.sdk.documents import DocumentService

    assert DocumentService.__module__ == "dms.sdk.documents"


def test_upload_responsibility_has_an_internal_service_boundary() -> None:
    from dms.sdk.upload import UploadService

    assert UploadService.__module__ == "dms.sdk.upload"


def test_shared_log_extra_preserves_event_and_context_namespaces() -> None:
    from dms.sdk.observability import build_log_extra

    assert build_log_extra("document.upload", {"document_id": "doc"}) == {
        "dms_event": "document.upload",
        "dms_document_id": "doc",
    }


def test_model_json_schema_dispatches_to_subclass_override() -> None:
    from dms.sdk.types import UploadDocumentResult

    class CustomUploadDocumentResult(UploadDocumentResult):
        @classmethod
        def json_schema(cls) -> dict[str, object]:
            return {"custom": True}

    assert CustomUploadDocumentResult.model_json_schema() == {"custom": True}


def test_schema_dtos_remain_slotted() -> None:
    from dms.sdk.types import (
        DeleteDocumentResult,
        DocumentPage,
        UploadDocumentResult,
        public_metadata,
    )

    public = public_metadata(make_metadata())
    values = (
        UploadDocumentResult(document_id="d", metadata=public),
        public,
        DeleteDocumentResult(
            document_id="d",
            deleted=True,
            hard_deleted=False,
            status=DocumentStatus.AVAILABLE,
        ),
        DocumentPage(items=[], next_cursor=None, has_more=False),
    )

    assert all(not hasattr(value, "__dict__") for value in values)


def test_internal_service_callbacks_preserve_facade_overrides() -> None:
    metadata_calls: list[str] = []
    status_calls: list[tuple[str, DocumentStatus]] = []

    class HookedSDK(DefaultDocumentManagementSDK):
        def get_internal_document_metadata(self, document_id: str, *, access_context=None):
            metadata_calls.append(document_id)
            return super().get_internal_document_metadata(
                document_id,
                access_context=access_context,
            )

        def _set_document_status(self, metadata, status):
            status_calls.append((metadata.document_id, status))
            return super()._set_document_status(metadata, status)

    sdk = HookedSDK(
        metadata_store=CursorMemoryStore(),
        object_store=StreamMemoryObjectStore(),
    )

    with pytest.raises(DocumentNotFoundError):
        sdk._uploads._get_internal_metadata("missing")
    with pytest.raises(DocumentNotFoundError):
        sdk._reconciliation._get_metadata("missing")
    sdk._reconciliation._set_failed(make_metadata(), DocumentStatus.FAILED)

    assert metadata_calls == ["missing", "missing"]
    assert status_calls == [("d", DocumentStatus.FAILED)]


def test_reconciliation_responsibility_has_an_internal_coordinator_boundary() -> None:
    from dms.sdk.reconciliation import ReconciliationCoordinator

    assert ReconciliationCoordinator.__module__ == "dms.sdk.reconciliation"


def test_pagination_policy_round_trips_filter_bound_cursor() -> None:
    created_at = datetime(2026, 1, 2, 3, 4, tzinfo=UTC)

    cursor = encode_cursor(created_at, "doc-1", DocumentStatus.AVAILABLE, 25)

    assert decode_cursor(cursor) == (created_at, "doc-1", "available", 25)


def test_pagination_policy_rejects_invalid_cursor() -> None:
    with pytest.raises(ValidationError, match="invalid document list cursor"):
        decode_cursor("not-json")


def test_idempotency_fingerprint_is_stable_for_metadata_order() -> None:
    first = build_upload_fingerprint(
        checksum="ABC",
        filename="a.txt",
        content_type="text/plain",
        size=3,
        document_id=None,
        metadata={"a": 1, "b": 2},
    )
    second = build_upload_fingerprint(
        checksum="abc",
        filename="a.txt",
        content_type="text/plain",
        size=3,
        document_id=None,
        metadata={"b": 2, "a": 1},
    )

    assert first == second


@pytest.mark.parametrize("module_name,class_name,owned_method", [
    ("dms.sdk.documents", "DocumentService", "get_internal_metadata"),
    ("dms.sdk.upload", "UploadService", "_save_uploaded_metadata"),
    ("dms.sdk.reconciliation", "ReconciliationCoordinator", "_apply"),
])
def test_cohesive_services_own_implementation_without_host_protocols(
    module_name: str, class_name: str, owned_method: str,
) -> None:
    service = getattr(__import__(module_name, fromlist=[class_name]), class_name)
    assert "_host" not in inspect.getsource(service)
    assert hasattr(service, owned_method)


def test_sdk_facade_uses_document_service_boundary() -> None:
    from dms.sdk.documents import DocumentService

    sdk = DefaultDocumentManagementSDK(
        metadata_store=CursorMemoryStore(),
        object_store=StreamMemoryObjectStore(),
    )

    assert isinstance(sdk._documents, DocumentService)



