from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from docmesh_py_core import HealthcheckPolicy, RuntimePlan, Service, diagnose_services


@dataclass(frozen=True)
class EnvironmentDiagnosis:
    metadata_backend: str | None
    object_backend: str
    healthcheck_enabled: bool
    missing_required_keys: tuple[str, ...]
    warnings: tuple[str, ...]
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
    explicit = explicit_backend(env)
    if explicit is not None:
        service = "postgres" if explicit == "postgresql" else explicit
        return {"minio", service}, {"minio", service}, ()
    if has_postgres_configuration(env):
        return {"minio", "postgres"}, {"minio", "postgres"}, ()
    if has_sqlite_configuration(env):
        return {"minio", "sqlite"}, {"minio", "sqlite"}, ()
    return {"minio", "postgres", "sqlite"}, {"minio"}, ({"postgres", "sqlite"},)


def diagnose_environment(env: Mapping[str, str]) -> EnvironmentDiagnosis:
    """Diagnose supplied configuration without assembling services or connecting."""
    explicit = explicit_backend(env)
    pg = has_postgres_configuration(env)
    sqlite = has_sqlite_configuration(env)
    notes: list[str] = []
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
    if backend is not None and not missing and not invalid_selection and not strict:
        metadata_service = Service.POSTGRES if backend == "postgresql" else Service.SQLITE
        core_diagnosis = diagnose_services(
            env,
            plan=RuntimePlan(
                services=(metadata_service.required(), Service.MINIO.required()),
                healthcheck=HealthcheckPolicy(on_startup=healthcheck_enabled(env)),
            ),
        )
        core_valid = core_diagnosis.ok
        for issue in core_diagnosis.issues:
            if issue.env_key and value(env, issue.env_key) is None and issue.env_key not in missing:
                missing.append(issue.env_key)
            notes.append(f"{issue.service}: {issue.reason}")
        notes.extend(f"{warning.service}: {warning.reason}" for warning in core_diagnosis.warnings)

    return EnvironmentDiagnosis(
        backend,
        "minio",
        healthcheck_enabled(env),
        tuple(dict.fromkeys(missing)),
        tuple(notes),
        not missing and not invalid_selection and not strict and core_valid,
    )
