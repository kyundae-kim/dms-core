from __future__ import annotations

import os
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from threading import RLock
from typing import Iterator, Literal

from docmesh_py_core import HealthcheckPolicy, RuntimePlan, Service, diagnose_services


_CORE_ENVIRONMENT_LOCK = RLock()
_CORE_ENVIRONMENT_PREFIXES = ("DOCMESH_", "POSTGRES_", "SQLITE_", "MINIO_")


@dataclass(frozen=True)
class EnvironmentDiagnosis:
    metadata_backend: str | None
    object_backend: str
    healthcheck_enabled: bool
    missing_required_keys: tuple[str, ...]
    warnings: tuple[str, ...]
    unsupported_keys: tuple[str, ...]
    valid: bool


def value(env: Mapping[str, str], key: str) -> str | None:
    candidate = env.get(key)
    return candidate.strip() if candidate is not None and candidate.strip() else None


def truthy(env: Mapping[str, str], key: str) -> bool:
    return (value(env, key) or "false").lower() in {"1", "true", "yes", "on"}


def explicit_backend(env: Mapping[str, str]) -> str | None:
    selected = value(env, "DMS_METADATA_BACKEND")
    return selected.lower() if selected is not None else None


def has_postgres_configuration(env: Mapping[str, str]) -> bool:
    return any(key.startswith("POSTGRES_") for key in env)


def has_sqlite_configuration(env: Mapping[str, str]) -> bool:
    return "SQLITE_PATH" in env


def healthcheck_enabled(env: Mapping[str, str]) -> bool:
    candidate = env.get("DOCMESH_HEALTHCHECK_ENABLED")
    return candidate is None or candidate.strip().lower() not in {"0", "false", "no", "off"}


def resolve_assembly_policy(
    env: Mapping[str, str],
) -> tuple[set[str], set[str], tuple[set[str], ...]]:
    plan, _ = resolve_runtime_plan(env)
    return (
        {service.value for service in plan.selected_services},
        {service.value for service in plan.required_services},
        tuple({service.value for service in group} for group in plan.alternative_groups),
    )


def resolve_runtime_plan(env: Mapping[str, str]) -> tuple[RuntimePlan, Literal["auto", "explicit", "strict"]]:
    explicit = explicit_backend(env)
    if explicit is not None:
        metadata = Service.POSTGRES if explicit == "postgresql" else Service.SQLITE
        mode: Literal["auto", "explicit", "strict"] = "explicit"
        services = (metadata.required(), Service.MINIO.required())
        one_of: tuple[tuple[Service, ...], ...] = ()
    elif has_postgres_configuration(env):
        services = (Service.POSTGRES.required(), Service.MINIO.required())
        one_of = ()
        mode = "strict" if has_sqlite_configuration(env) and truthy(env, "DMS_CONFIGURATION_STRICT") else "auto"
    elif has_sqlite_configuration(env):
        services = (Service.SQLITE.required(), Service.MINIO.required())
        one_of = ()
        mode = "auto"
    else:
        services = (Service.POSTGRES, Service.SQLITE, Service.MINIO.required())
        one_of = ((Service.POSTGRES, Service.SQLITE),)
        mode = "auto"
    return RuntimePlan(
        services=services,
        one_of=one_of,
        healthcheck=HealthcheckPolicy(on_startup=healthcheck_enabled(env)),
    ), mode


def _is_core_environment_key(key: str) -> bool:
    return key.startswith(_CORE_ENVIRONMENT_PREFIXES)


@contextmanager
def core_environment(env: Mapping[str, str]) -> Iterator[None]:
    """Temporarily expose a supplied SDK environment to process-only core APIs."""
    with _CORE_ENVIRONMENT_LOCK:
        original = {key: value for key, value in os.environ.items() if _is_core_environment_key(key)}
        supplied = {key: value for key, value in env.items() if _is_core_environment_key(key)}
        try:
            for key in tuple(os.environ):
                if _is_core_environment_key(key):
                    del os.environ[key]
            os.environ.update(supplied)
            yield
        finally:
            for key in tuple(os.environ):
                if _is_core_environment_key(key):
                    del os.environ[key]
            os.environ.update(original)


def diagnose_environment(env: Mapping[str, str]) -> EnvironmentDiagnosis:
    """Diagnose supplied configuration without assembling services or connecting."""
    explicit = explicit_backend(env)
    pg = has_postgres_configuration(env)
    sqlite = has_sqlite_configuration(env)
    notes: list[str] = []
    unsupported = tuple(key for key in ("POSTGRES_DSN",) if key in env)
    if unsupported:
        notes.append("POSTGRES_DSN is unsupported; use individual POSTGRES_* fields")
    core_valid = True
    invalid_selection = explicit is not None and explicit not in {"postgresql", "sqlite"}
    if invalid_selection:
        backend = None
        notes.append("DMS_METADATA_BACKEND must be 'postgresql' or 'sqlite'")
    elif explicit is not None:
        backend = explicit
    elif pg:
        backend = "postgresql"
        if sqlite:
            notes.append("Both PostgreSQL and SQLite are configured; PostgreSQL takes precedence in auto mode")
    elif sqlite:
        backend = "sqlite"
    else:
        backend = None

    missing = [
        key
        for key in ("MINIO_ENDPOINT", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY", "MINIO_BUCKET")
        if value(env, key) is None
    ]
    if backend == "postgresql":
        missing += [
            key
            for key in ("POSTGRES_HOST", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD")
            if value(env, key) is None
        ]
    elif backend == "sqlite" and value(env, "SQLITE_PATH") is None:
        missing.append("SQLITE_PATH")
    elif backend is None and not invalid_selection:
        missing.append("DMS_METADATA_BACKEND or PostgreSQL/SQLite configuration")

    strict = explicit is None and pg and sqlite and truthy(env, "DMS_CONFIGURATION_STRICT")
    if strict:
        notes.append("Ambiguous metadata backend configuration is forbidden by DMS_CONFIGURATION_STRICT")
    if backend is not None and not missing and not unsupported and not invalid_selection and not strict:
        plan, selection_mode = resolve_runtime_plan(env)
        with core_environment(env):
            core_diagnosis = diagnose_services(plan=plan, selection_mode=selection_mode)
        core_valid = core_diagnosis.ok
        for issue in core_diagnosis.issues:
            if (
                issue.env_key
                and issue.error_type == "missing"
                and value(env, issue.env_key) is None
                and issue.env_key not in missing
            ):
                missing.append(issue.env_key)
            note = f"{issue.service}: {issue.reason}"
            if issue.remediation:
                note = f"{note} ({issue.remediation})"
            notes.append(note)
        notes.extend(f"{warning.service}: {warning.reason}" for warning in core_diagnosis.warnings)

    return EnvironmentDiagnosis(
        backend,
        "minio",
        healthcheck_enabled(env),
        tuple(dict.fromkeys(missing)),
        tuple(dict.fromkeys(notes)),
        unsupported,
        not missing and not unsupported and not invalid_selection and not strict and core_valid,
    )


def format_environment_diagnosis(diagnosis: EnvironmentDiagnosis) -> str:
    """Render a secret-safe diagnosis for logs and operator-facing output."""
    lines = [
        f"metadata backend: {diagnosis.metadata_backend or 'unselected'}",
        f"object backend: {diagnosis.object_backend}",
        f"startup health check: {'enabled' if diagnosis.healthcheck_enabled else 'disabled'}",
        f"valid: {'yes' if diagnosis.valid else 'no'}",
    ]
    if diagnosis.missing_required_keys:
        lines.append("missing required keys: " + ", ".join(diagnosis.missing_required_keys))
    if diagnosis.unsupported_keys:
        lines.append("unsupported keys: " + ", ".join(diagnosis.unsupported_keys))
    if diagnosis.warnings:
        lines.append("warnings: " + "; ".join(diagnosis.warnings))
    return "\n".join(lines)
