from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine

from dms.sdk import factory
from dms.sdk.environment import EnvironmentDiagnosis
from docmesh_py_core import HealthcheckPolicy, RuntimePlan, Service, ServiceRuntime


class StubMinioClient:
    pass


@pytest.mark.asyncio
async def test_environment_factory_assembles_typed_runtime_and_owns_async_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine("sqlite:///:memory:")
    minio = StubMinioClient()
    plan = RuntimePlan(
        services=(Service.SQLITE.required(), Service.MINIO.required()),
        healthcheck=HealthcheckPolicy(on_startup=True),
    )
    diagnosis = EnvironmentDiagnosis(
        metadata_backend="sqlite",
        object_backend="minio",
        healthcheck_enabled=True,
        missing_required_keys=(),
        warnings=(),
        unsupported_keys=(),
        valid=True,
    )
    runtime = ServiceRuntime(
        configs=SimpleNamespace(
            sqlite=object(),
            postgres=None,
            minio=SimpleNamespace(bucket="documents"),
        ),
        clients={Service.SQLITE: engine, Service.MINIO: minio},
        selected_services=frozenset({Service.SQLITE, Service.MINIO}),
        required_services=frozenset({Service.SQLITE, Service.MINIO}),
    )
    received_plans: list[RuntimePlan] = []

    async def assemble(*, plan: RuntimePlan) -> ServiceRuntime:
        received_plans.append(plan)
        return runtime

    monkeypatch.setattr(
        factory,
        "resolve_assembly_decision",
        lambda env: SimpleNamespace(
            diagnosis=diagnosis,
            plan=plan,
            should_reject=False,
        ),
    )
    monkeypatch.setattr(factory, "assemble_service_runtime", assemble)

    sdk = factory.create_sdk_from_environment()

    assert received_plans == [plan]
    assert sdk._metadata_store._engine is engine
    assert sdk._object_store._client is minio

    sdk.close()
    assert runtime._closed is True
