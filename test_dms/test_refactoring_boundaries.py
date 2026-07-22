from __future__ import annotations

from datetime import UTC, datetime
import inspect

import pytest

from dms import DocumentStatus, ValidationError
from dms.sdk.idempotency import build_upload_fingerprint
from dms.sdk.pagination import decode_cursor, encode_cursor
from dms.sdk.factory import create_sdk_from_components
from test_dms.sdk_test_support import CursorMemoryStore, StreamMemoryObjectStore


def test_environment_policy_has_a_side_effect_free_module_boundary(monkeypatch) -> None:
    import dms.sdk.environment as environment

    def forbidden(*args, **kwargs):
        raise AssertionError("environment diagnosis must not assemble services")

    monkeypatch.setattr("docmesh_py_core.assemble_services", forbidden)
    report = environment.diagnose_environment(
        {
            "DMS_METADATA_BACKEND": "sqlite",
            "SQLITE_PATH": ":memory:",
            "MINIO_ENDPOINT": "minio:9000",
            "MINIO_ACCESS_KEY": "access-key-value",
            "MINIO_SECRET_KEY": "secret-key-value",
            "MINIO_BUCKET": "documents",
        }
    )

    assert report.valid
    assert report.__class__.__module__ == "dms.sdk.environment"


def test_factory_keeps_environment_policy_compatibility_imports() -> None:
    from dms.sdk import factory
    from dms.sdk import environment

    assert factory.EnvironmentDiagnosis is environment.EnvironmentDiagnosis
    assert factory.diagnose_environment is environment.diagnose_environment
    assert factory._resolve_assembly_policy is environment.resolve_assembly_policy


def test_factory_responsibilities_have_dedicated_module_boundaries() -> None:
    from dms.sdk.assembly import create_sdk_from_bundle
    from dms.sdk.configuration import validate_dms_service_configs
    from dms.sdk.core_compat import diagnose_core_environment
    from dms.sdk.error_translation import translate_assembly_error

    assert callable(create_sdk_from_bundle)
    assert callable(validate_dms_service_configs)
    assert callable(diagnose_core_environment)
    assert callable(translate_assembly_error)


def test_environment_resolution_returns_one_typed_decision() -> None:
    from dms.sdk.environment import MetadataBackend, resolve_assembly_decision

    decision = resolve_assembly_decision(
        {
            "DMS_METADATA_BACKEND": "sqlite",
            "SQLITE_PATH": ":memory:",
            "MINIO_ENDPOINT": "minio:9000",
            "MINIO_ACCESS_KEY": "access-key-value",
            "MINIO_SECRET_KEY": "secret-key-value",
            "MINIO_BUCKET": "documents",
        }
    )

    assert decision.backend is MetadataBackend.SQLITE
    assert decision.selection_mode == "explicit"
    assert {selection.service.value for selection in decision.plan.services} == {"sqlite", "minio"}
    assert decision.diagnosis.valid


def test_sdk_document_and_lifecycle_responsibilities_have_service_boundaries() -> None:
    from dms.sdk.documents import DocumentService
    from dms.sdk.lifecycle import LifecycleService

    assert DocumentService.__module__ == "dms.sdk.documents"
    assert LifecycleService.__module__ == "dms.sdk.lifecycle"


def test_named_metadata_adapters_are_thin_common_store_subclasses() -> None:
    from dms.infrastructure.metadata.postgres import PostgresMetadataStore
    from dms.infrastructure.metadata.sqlalchemy import SqlAlchemyMetadataStore
    from dms.infrastructure.metadata.sqlite import SqliteMetadataStore

    assert PostgresMetadataStore.__bases__ == (SqlAlchemyMetadataStore,)
    assert SqliteMetadataStore.__bases__ == (SqlAlchemyMetadataStore,)
    assert "save_metadata" not in PostgresMetadataStore.__dict__
    assert "save_metadata" not in SqliteMetadataStore.__dict__


def test_upload_responsibility_has_an_internal_service_boundary() -> None:
    from dms.sdk.upload import UploadService

    assert UploadService.__module__ == "dms.sdk.upload"


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

    sdk = create_sdk_from_components(
        metadata_store=CursorMemoryStore(),
        object_store=StreamMemoryObjectStore(),
    )

    assert isinstance(sdk._documents, DocumentService)


def test_sdk_lifecycle_facade_remains_available_after_service_extraction() -> None:
    closed: list[bool] = []
    sdk = create_sdk_from_components(
        metadata_store=CursorMemoryStore(),
        object_store=StreamMemoryObjectStore(),
        service_checks={"metadata": lambda: None},
        close_callbacks=[lambda: closed.append(True)],
    )

    assert sdk.check_health().ok
    with sdk:
        pass
    sdk.close()

    assert closed == [True]
