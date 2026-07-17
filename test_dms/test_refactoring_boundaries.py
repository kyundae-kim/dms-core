from __future__ import annotations

from datetime import UTC, datetime

import pytest

from dms import DocumentStatus, ValidationError
from dms.sdk._idempotency import build_upload_fingerprint
from dms.sdk._pagination import decode_cursor, encode_cursor


def test_environment_policy_has_a_side_effect_free_module_boundary(monkeypatch) -> None:
    import dms.sdk._environment as environment

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
    assert report.__class__.__module__ == "dms.sdk._environment"


def test_factory_keeps_environment_policy_compatibility_imports() -> None:
    from dms.sdk import factory
    from dms.sdk import _environment

    assert factory.EnvironmentDiagnosis is _environment.EnvironmentDiagnosis
    assert factory.diagnose_environment is _environment.diagnose_environment
    assert factory._resolve_assembly_policy is _environment.resolve_assembly_policy


def test_named_metadata_adapters_are_thin_common_store_subclasses() -> None:
    from dms.infrastructure.metadata.postgres import PostgresMetadataStore
    from dms.infrastructure.metadata.sqlalchemy import SqlAlchemyMetadataStore
    from dms.infrastructure.metadata.sqlite import SqliteMetadataStore

    assert PostgresMetadataStore.__bases__ == (SqlAlchemyMetadataStore,)
    assert SqliteMetadataStore.__bases__ == (SqlAlchemyMetadataStore,)
    assert "save_metadata" not in PostgresMetadataStore.__dict__
    assert "save_metadata" not in SqliteMetadataStore.__dict__


def test_upload_responsibility_has_an_internal_service_boundary() -> None:
    from dms.sdk._upload import UploadService

    assert UploadService.__module__ == "dms.sdk._upload"


def test_reconciliation_responsibility_has_an_internal_coordinator_boundary() -> None:
    from dms.sdk._reconciliation import ReconciliationCoordinator

    assert ReconciliationCoordinator.__module__ == "dms.sdk._reconciliation"


def test_pagination_policy_round_trips_filter_bound_cursor() -> None:
    created_at = datetime(2026, 1, 2, 3, 4, tzinfo=UTC)

    cursor = encode_cursor(created_at, "doc-1", DocumentStatus.AVAILABLE)

    assert decode_cursor(cursor) == (created_at, "doc-1", "available")


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
