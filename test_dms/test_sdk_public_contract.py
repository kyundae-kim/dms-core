from __future__ import annotations

import inspect
import os

import pytest
from docmesh_py_core import HealthCheckError, ServiceHealthStatus

from dms import (
    ConfigurationError,
    HealthCheckFailedError,
    DocumentDeletedError,
    PublicDocumentMetadata,
    UploadDocumentRequest,
    create_sdk_from_components,
    create_sdk_from_environment,
    create_sdk_from_service_configs,
    diagnose_environment,
    format_environment_diagnosis,
)
from test_dms.sdk_test_support import CursorMemoryStore, StreamMemoryObjectStore


_ENVIRONMENT_PREFIXES = ("DMS_", "DOCMESH_", "POSTGRES_", "SQLITE_", "MINIO_")


def _set_process_environment(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    for key in tuple(os.environ):
        if key.startswith(_ENVIRONMENT_PREFIXES):
            monkeypatch.delenv(key)
    for key, value in env.items():
        monkeypatch.setenv(key, value)


def _sdk():
    return create_sdk_from_components(
        metadata_store=CursorMemoryStore(),
        object_store=StreamMemoryObjectStore(),
    )


def test_service_configs_factory_is_exported_from_public_sdk() -> None:
    import dms
    import dms.sdk

    assert "create_sdk_from_service_configs" in dms.sdk.__all__
    assert "create_sdk_from_service_configs" in dms.__all__
    assert dms.create_sdk_from_service_configs is create_sdk_from_service_configs


def test_service_configs_factory_has_public_signature() -> None:
    signature = inspect.signature(create_sdk_from_service_configs)

    assert next(iter(signature.parameters)) == "configs"
    assert signature.parameters["check_on_startup"].kind is inspect.Parameter.KEYWORD_ONLY
    assert signature.parameters["check_on_startup"].default is False


def test_deleted_document_content_and_stream_raise_deleted_error() -> None:
    sdk = _sdk()
    result = sdk.upload_document(
        UploadDocumentRequest(
            document_id="deleted",
            content=b"content",
            filename="deleted.txt",
            content_type="text/plain",
        )
    )
    sdk.soft_delete_document(result.document_id)

    with pytest.raises(DocumentDeletedError) as content_error:
        sdk.get_document_content(result.document_id)
    with pytest.raises(DocumentDeletedError):
        sdk.get_document_content_stream(result.document_id)

    assert content_error.value.code == "document_deleted"
    assert content_error.value.retryable is False
    assert content_error.value.document_id == result.document_id


def test_default_metadata_and_upload_results_hide_storage_key() -> None:
    sdk = _sdk()
    result = sdk.upload_document(
        UploadDocumentRequest(
            document_id="public",
            content=b"content",
            filename="public.txt",
            content_type="text/plain",
        )
    )

    metadata = sdk.get_document_metadata(result.document_id)
    listed = sdk.list_documents()
    page = sdk.list_documents_page()

    assert isinstance(result.metadata, PublicDocumentMetadata)
    assert isinstance(metadata, PublicDocumentMetadata)
    assert all(isinstance(item, PublicDocumentMetadata) for item in listed)
    assert all(isinstance(item, PublicDocumentMetadata) for item in page.items)
    assert not hasattr(result, "storage_key")
    assert not hasattr(metadata, "storage_key")


def test_privileged_metadata_access_is_explicit() -> None:
    sdk = _sdk()
    result = sdk.upload_document(
        UploadDocumentRequest(content=b"x", filename="x.txt", content_type="text/plain")
    )

    internal = sdk.get_internal_document_metadata(result.document_id)

    assert internal.storage_key.startswith("documents/")


@pytest.mark.parametrize("legacy_dsn", ["postgresql://user:***@db/dms", "", "   "])
def test_legacy_postgres_dsn_is_structured_and_rejected(
    monkeypatch: pytest.MonkeyPatch,
    legacy_dsn: str,
) -> None:
    env = {
        "POSTGRES_DSN": legacy_dsn,
        "MINIO_ENDPOINT": "minio:9000",
        "MINIO_ACCESS_KEY": "access",
        "MINIO_SECRET_KEY": "secret",
        "MINIO_BUCKET": "documents",
    }

    diagnosis = diagnose_environment(env)

    assert diagnosis.unsupported_keys == ("POSTGRES_DSN",)
    assert diagnosis.valid is False
    assert "POSTGRES_DSN" in format_environment_diagnosis(diagnosis)
    _set_process_environment(monkeypatch, env)
    with pytest.raises(ConfigurationError) as captured:
        create_sdk_from_environment()
    assert captured.value.diagnosis == diagnosis
    assert captured.value.code == "configuration_invalid"
    assert captured.value.retryable is False


def test_startup_health_error_exposes_service_and_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    import dms.sdk.factory as factory_module

    def fail(**options):
        raise HealthCheckError(ServiceHealthStatus(
            service="minio", ok=False, latency_ms=1, required=True,
            error="connection refused"))

    monkeypatch.setattr(factory_module, "assemble_services", fail)
    env = {
        "DMS_METADATA_BACKEND": "sqlite",
        "SQLITE_PATH": ":memory:",
        "MINIO_ENDPOINT": "minio:9000",
        "MINIO_ACCESS_KEY": "access",
        "MINIO_SECRET_KEY": "secret",
        "MINIO_BUCKET": "documents",
    }
    _set_process_environment(monkeypatch, env)

    with pytest.raises(HealthCheckFailedError) as captured:
        create_sdk_from_environment()

    assert captured.value.code == "startup_health_failed"
    assert captured.value.retryable is True
    assert captured.value.service == "minio"
    assert captured.value.reason == "connection refused"
