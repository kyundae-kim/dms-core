from __future__ import annotations
import os
from io import BytesIO
from typing import Any, cast
import pytest
from dms import (ConfigurationError, DefaultMetadataPolicy, UploadDocumentRequest, UploadDocumentStreamRequest, ValidationError, create_sdk_from_components, create_sdk_from_environment, diagnose_environment, format_environment_diagnosis)
from dms.domain.interfaces import ObjectStore, PutObjectRequest
from dms.sdk.environment import core_environment
from dms.sdk.factory import _resolve_assembly_policy
from test_dms.sdk_test_support import InMemoryMetadataStore, InMemoryObjectStore

MINIO = {"MINIO_ENDPOINT": "minio:9000", "MINIO_ACCESS_KEY": "access-secret-value", "MINIO_SECRET_KEY": "super-secret-value", "MINIO_BUCKET": "documents"}
POSTGRES = {
    "POSTGRES_HOST": "db",
    "POSTGRES_PORT": "5432",
    "POSTGRES_DB": "dms",
    "POSTGRES_USER": "dms",
    "POSTGRES_PASSWORD": "postgres-secret-value",
}

def configured(extra: dict[str, str]) -> dict[str, str]:
    result = dict(MINIO)
    result.update(extra)
    return result

def test_explicit_selection_only_requests_selected_backend_and_validates_it():
    env = configured({"DMS_METADATA_BACKEND": "sqlite", "SQLITE_PATH": ":memory:", **POSTGRES})
    assert _resolve_assembly_policy(env) == ({"minio", "sqlite"}, {"minio", "sqlite"}, ())
    bad = configured({"DMS_METADATA_BACKEND": "postgresql", "SQLITE_PATH": ":memory:"})
    with pytest.raises(ConfigurationError, match="POSTGRES_"):
        create_sdk_from_environment(bad)

def test_auto_selection_precedence_warning_and_strict_rejection():
    env = configured({**POSTGRES, "SQLITE_PATH": ":memory:"})
    report = diagnose_environment(env)
    assert report.metadata_backend == "postgresql" and report.valid and report.warnings
    assert _resolve_assembly_policy(env)[0] == {"postgres", "minio"}
    strict = dict(env)
    strict["DMS_CONFIGURATION_STRICT"] = "true"
    assert diagnose_environment(strict).valid is False
    with pytest.raises(ConfigurationError, match="Invalid DMS environment"):
        create_sdk_from_environment(strict)

def test_diagnosis_is_typed_side_effect_free_and_secret_safe():
    env = configured({"DMS_METADATA_BACKEND": "postgresql", **POSTGRES, "DOCMESH_HEALTHCHECK_ENABLED": "false"})
    report = diagnose_environment(env)
    assert (report.metadata_backend, report.object_backend, report.healthcheck_enabled) == ("postgresql", "minio", False)
    assert report.missing_required_keys == () and report.valid
    assert "access-secret-value" not in repr(report)
    assert "super-secret-value" not in repr(report)
    assert "postgres-secret-value" not in repr(report)
    formatted = format_environment_diagnosis(report)
    assert "access-secret-value" not in formatted
    assert "super-secret-value" not in formatted
    assert "postgres-secret-value" not in formatted


def test_core_diagnosis_uses_v04_keyword_only_contract(monkeypatch: pytest.MonkeyPatch):
    import dms.sdk.environment as environment_module

    calls: list[dict[str, object]] = []

    class CoreDiagnosis:
        ok = True
        issues = ()
        warnings = ()

    def diagnose_services(*, plan, selection_mode="auto"):
        calls.append({"plan": plan, "selection_mode": selection_mode})
        return CoreDiagnosis()

    monkeypatch.setattr(environment_module, "diagnose_services", diagnose_services)

    report = diagnose_environment(configured({"DMS_METADATA_BACKEND": "sqlite", "SQLITE_PATH": ":memory:"}))

    assert report.valid is True
    assert len(calls) == 1
    assert calls[0]["selection_mode"] == "explicit"
    plan = cast(Any, calls[0]["plan"])
    assert {selection.service.value for selection in plan.services} == {"sqlite", "minio"}


def test_core_environment_is_filtered_and_restored_after_failure(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("POSTGRES_HOST", "original-db")
    monkeypatch.setenv("UNRELATED_SETTING", "original-unrelated")
    original_minio_endpoint = os.environ.get("MINIO_ENDPOINT")

    with pytest.raises(RuntimeError, match="stop"):
        with core_environment(
            {
                "POSTGRES_HOST": "mapped-db",
                "MINIO_ENDPOINT": "mapped-minio:9000",
                "UNRELATED_SETTING": "must-not-be-overlaid",
            }
        ):
            assert os.environ["POSTGRES_HOST"] == "mapped-db"
            assert os.environ["MINIO_ENDPOINT"] == "mapped-minio:9000"
            assert os.environ["UNRELATED_SETTING"] == "original-unrelated"
            raise RuntimeError("stop")

    assert os.environ["POSTGRES_HOST"] == "original-db"
    assert os.environ.get("MINIO_ENDPOINT") == original_minio_endpoint
    assert os.environ["UNRELATED_SETTING"] == "original-unrelated"

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
