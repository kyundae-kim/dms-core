from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from threading import RLock
from typing import Callable, Literal

from docmesh_py_core import RuntimePlan, diagnose_services

_CORE_ENVIRONMENT_LOCK = RLock()
_CORE_ENVIRONMENT_PREFIXES = ("DOCMESH_", "POSTGRES_", "SQLITE_", "MINIO_")


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


def diagnose_core_environment(
    env: Mapping[str, str], *, plan: RuntimePlan,
    selection_mode: Literal["auto", "explicit", "strict"],
    diagnose: Callable[..., object] = diagnose_services,
):
    with core_environment(env):
        return diagnose(plan=plan, selection_mode=selection_mode)
