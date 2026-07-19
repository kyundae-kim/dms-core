from __future__ import annotations
import os
from dataclasses import replace
from io import BytesIO
from typing import Any, cast
import pytest
from docmesh_py_core import (
    ConfigError,
    HealthCheckError,
    ServiceClientError,
    ServiceClientWrapper,
    ServiceHealthStatus,
    ServiceUnavailableError,
    load_service_configs,
)
from dms import (ConfigurationError, DefaultMetadataPolicy, StorageError, UploadDocumentRequest, UploadDocumentStreamRequest, ValidationError, create_sdk_from_components, create_sdk_from_environment, diagnose_environment, format_environment_diagnosis)
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

ENVIRONMENT_PREFIXES = ("DMS_", "DOCMESH_", "POSTGRES_", "SQLITE_", "MINIO_")


def set_process_environment(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    for key in tuple(os.environ):
        if key.startswith(ENVIRONMENT_PREFIXES):
            monkeypatch.delenv(key)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

def configured(extra: dict[str, str]) -> dict[str, str]:
    result = dict(MINIO)
    result.update(extra)
    return result


def service_configs(monkeypatch: pytest.MonkeyPatch, backend: str = "sqlite"):
    metadata = {"SQLITE_PATH": ":memory:"} if backend == "sqlite" else POSTGRES
    set_process_environment(monkeypatch, configured(metadata))
    return load_service_configs(services={backend, "minio"})


def test_service_configs_fixture_loads_exactly_one_metadata_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sqlite_configs = service_configs(monkeypatch, "sqlite")
    postgres_configs = service_configs(monkeypatch, "postgres")

    assert sqlite_configs.sqlite is not None and sqlite_configs.postgres is None
    assert postgres_configs.postgres is not None and postgres_configs.sqlite is None


def _wrapper(client: object, service: str, calls: list[str]) -> ServiceClientWrapper[Any]:
    return ServiceClientWrapper(
        client,
        lambda: ServiceHealthStatus(service=service, ok=True, latency_ms=0, required=True),
        service_name=service,
        close_fn=lambda: calls.append(service),
    )


@pytest.mark.parametrize("case", ["neither", "both", "no_minio", "no_bucket", "insecure_production"])
def test_service_configs_validation_precedes_client_creation(
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    import dms.sdk.factory as factory_module

    configs = service_configs(monkeypatch)
    postgres = service_configs(monkeypatch, "postgres").postgres
    if case == "neither":
        configs = replace(configs, sqlite=None)
    elif case == "both":
        configs = replace(configs, postgres=postgres)
    elif case == "no_minio":
        configs = replace(configs, minio=None)
    elif case == "no_bucket":
        configs = replace(configs, minio=configs.minio.model_copy(update={"bucket": " "}))
    else:
        configs = replace(
            configs,
            common=configs.common.model_copy(update={"env": "production"}),
            minio=configs.minio.model_copy(update={"secure": False}),
        )
    calls: list[str] = []
    for name in ("create_postgres_client", "create_sqlite_client", "create_minio_client"):
        monkeypatch.setattr(factory_module, name, lambda *_args, _name=name: calls.append(_name))

    with pytest.raises(ConfigurationError) as captured:
        factory_module.create_sdk_from_service_configs(configs)

    assert calls == []
    assert "access-secret-value" not in str(captured.value)
    assert "super-secret-value" not in str(captured.value)


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
def test_service_configs_factory_selects_metadata_backend_and_minio_without_reading_environment(
    monkeypatch: pytest.MonkeyPatch,
    backend: str,
) -> None:
    import dms.sdk.factory as factory_module

    configs = service_configs(monkeypatch, backend)
    engine = object()
    minio = object()
    calls: list[str] = []
    monkeypatch.setattr(
        factory_module,
        "create_sqlite_client",
        lambda config: _wrapper(engine, "sqlite", calls) if backend == "sqlite" else pytest.fail("sqlite called"),
    )
    monkeypatch.setattr(
        factory_module,
        "create_postgres_client",
        lambda config: _wrapper(engine, "postgres", calls) if backend == "postgres" else pytest.fail("postgres called"),
    )
    monkeypatch.setattr(factory_module, "create_minio_client", lambda config: _wrapper(minio, "minio", calls))
    monkeypatch.setattr(factory_module, "_create_sdk_from_bundle", lambda bundle, **options: bundle)
    snapshot = dict(os.environ)

    bundle = cast(Any, factory_module.create_sdk_from_service_configs(configs))

    assert bundle.get_client(backend).unwrap() is engine
    assert bundle.get_client("minio").unwrap() is minio
    assert dict(os.environ) == snapshot


def test_service_configs_factory_rolls_back_metadata_when_minio_creation_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import dms.sdk.factory as factory_module

    configs = service_configs(monkeypatch)
    closes: list[str] = []
    monkeypatch.setattr(factory_module, "create_sqlite_client", lambda config: _wrapper(object(), "sqlite", closes))
    monkeypatch.setattr(
        factory_module,
        "create_minio_client",
        lambda config: (_ for _ in ()).throw(ServiceClientError(
            service="minio", operation="create", error_type="RuntimeError", error="unavailable"
        )),
    )

    with pytest.raises(StorageError):
        factory_module.create_sdk_from_service_configs(configs)

    assert closes == ["sqlite"]


def test_service_configs_factory_optional_startup_check_closes_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import dms.sdk.factory as factory_module

    configs = service_configs(monkeypatch)
    closes: list[str] = []
    monkeypatch.setattr(factory_module, "create_sqlite_client", lambda config: _wrapper(object(), "sqlite", closes))
    monkeypatch.setattr(factory_module, "create_minio_client", lambda config: _wrapper(object(), "minio", closes))
    status = ServiceHealthStatus(
        service="minio", ok=False, latency_ms=1, required=True, error="connection refused"
    )
    monkeypatch.setattr(factory_module.ServiceBundle, "check", lambda self, **kwargs: (_ for _ in ()).throw(HealthCheckError(status)))

    with pytest.raises(factory_module.HealthCheckFailedError) as captured:
        factory_module.create_sdk_from_service_configs(configs, check_on_startup=True)

    assert captured.value.service == "minio"
    assert captured.value.reason == "connection refused"
    assert set(closes) == {"sqlite", "minio"}


def test_service_configs_sdk_owns_healthchecks_and_closes_wrappers_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import dms.sdk.factory as factory_module

    configs = service_configs(monkeypatch)
    closes: list[str] = []
    monkeypatch.setattr(factory_module, "create_sqlite_client", lambda config: _wrapper(object(), "sqlite", closes))
    monkeypatch.setattr(factory_module, "create_minio_client", lambda config: _wrapper(object(), "minio", closes))
    monkeypatch.setattr(factory_module, "_create_metadata_stores", lambda bundle: (InMemoryMetadataStore(), None))
    monkeypatch.setattr(factory_module, "_create_object_store", lambda bundle: InMemoryObjectStore())

    sdk = factory_module.create_sdk_from_service_configs(configs)
    health = sdk.check_health()
    sdk.close()
    sdk.close()

    assert health.ok is True
    assert {service.service for service in health.services} == {"sqlite", "minio"}
    assert set(closes) == {"sqlite", "minio"}
    assert len(closes) == 2


@pytest.mark.parametrize(
    ("core_error", "expected"),
    [
        (ConfigError("bad config"), ConfigurationError),
        (ServiceClientError(service="postgres", operation="create", error_type="RuntimeError", error="bad"), __import__("dms").MetadataStoreError),
        (ServiceUnavailableError("down", service="minio"), __import__("dms").StorageError),
    ],
)
def test_service_configs_factory_maps_core_errors(
    monkeypatch: pytest.MonkeyPatch, core_error: Exception, expected: type[Exception]
) -> None:
    import dms.sdk.factory as factory_module

    configs = service_configs(monkeypatch)
    monkeypatch.setattr(factory_module, "create_sqlite_client", lambda config: (_ for _ in ()).throw(core_error))

    with pytest.raises(expected):
        factory_module.create_sdk_from_service_configs(configs)

def test_explicit_selection_only_requests_selected_backend_and_validates_it(
    monkeypatch: pytest.MonkeyPatch,
):
    env = configured({"DMS_METADATA_BACKEND": "sqlite", "SQLITE_PATH": ":memory:", **POSTGRES})
    assert _resolve_assembly_policy(env) == ({"minio", "sqlite"}, {"minio", "sqlite"}, ())
    bad = configured({"DMS_METADATA_BACKEND": "postgresql", "SQLITE_PATH": ":memory:"})
    set_process_environment(monkeypatch, bad)
    with pytest.raises(ConfigurationError, match="POSTGRES_"):
        create_sdk_from_environment()

def test_auto_selection_precedence_warning_and_strict_rejection(monkeypatch: pytest.MonkeyPatch):
    env = configured({**POSTGRES, "SQLITE_PATH": ":memory:"})
    report = diagnose_environment(env)
    assert report.metadata_backend == "postgresql" and report.valid and report.warnings
    assert _resolve_assembly_policy(env)[0] == {"postgres", "minio"}
    strict = dict(env)
    strict["DMS_CONFIGURATION_STRICT"] = "true"
    assert diagnose_environment(strict).valid is False
    set_process_environment(monkeypatch, strict)
    with pytest.raises(ConfigurationError, match="Invalid DMS environment"):
        create_sdk_from_environment()

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
