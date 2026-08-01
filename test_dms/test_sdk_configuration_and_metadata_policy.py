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
from dms import (ConfigurationError, DefaultMetadataPolicy, StorageError, UploadDocumentRequest, UploadDocumentStreamRequest, ValidationError, create_sdk_from_components)
from dms.domain.interfaces import ObjectStore, PutObjectRequest

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
