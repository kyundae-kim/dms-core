from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Lock
from time import perf_counter
from typing import Awaitable

from dms.sdk.contracts import ManagedResource, ResourceOwnership
from dms.sdk.errors import ResourceCleanupError
from dms.sdk.types import HealthStatus, ServiceHealth


class LifecycleService:
    def __init__(
        self,
        *,
        service_checks: Mapping[str, Callable[[], object]],
        close_callbacks: list[Callable[[], object]],
        managed_resources: list[ManagedResource],
        logger: logging.Logger,
    ) -> None:
        self._service_checks = service_checks
        callback_resources = [
            ManagedResource(
                resource=callback,
                ownership=ResourceOwnership.SDK,
                close=callback,
                name=getattr(callback, "__name__", "close_callback"),
            )
            for callback in close_callbacks
        ]
        self._resources = [
            *callback_resources,
            *(
                resource
                for resource in managed_resources
                if resource.ownership is ResourceOwnership.SDK
            ),
        ]
        self._logger = logger
        self._closed = False
        self._close_lock = Lock()

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def resource_count(self) -> int:
        return len(self._resources)

    def check_health(self) -> HealthStatus:
        services: list[ServiceHealth] = []
        overall_ok = True
        for name, check in self._service_checks.items():
            started = perf_counter()
            try:
                check()
            except Exception as exc:
                overall_ok = False
                services.append(ServiceHealth(
                    service=name,
                    ok=False,
                    latency_ms=(perf_counter() - started) * 1000,
                    error=str(exc),
                ))
            else:
                services.append(ServiceHealth(
                    service=name,
                    ok=True,
                    latency_ms=(perf_counter() - started) * 1000,
                    error=None,
                ))
        return HealthStatus(
            ok=overall_ok,
            services=services,
            checked_at=datetime.now(UTC),
        )

    def close(self) -> None:
        resources = self._claim_resources()
        if resources is None:
            return
        errors: list[Exception] = []
        for resource in reversed(resources):
            try:
                self._close_resource(resource)
            except Exception as exc:
                errors.append(exc)
        self._raise_cleanup_errors(errors)

    async def aclose(self) -> None:
        resources = self._claim_resources()
        if resources is None:
            return
        cleanup_task = asyncio.create_task(self._aclose_resources(resources))
        try:
            await asyncio.shield(cleanup_task)
        except asyncio.CancelledError:
            await cleanup_task
            raise

    async def _aclose_resources(self, resources: list[ManagedResource]) -> None:
        errors: list[Exception] = []
        for resource in reversed(resources):
            try:
                if resource.aclose is not None:
                    result = resource.aclose()
                    if inspect.isawaitable(result):
                        await result
                elif resource.close is not None:
                    result = await asyncio.to_thread(resource.close)
                    if inspect.isawaitable(result):
                        await result
            except asyncio.CancelledError as exc:
                cleanup_error = RuntimeError("Managed resource cleanup was cancelled")
                cleanup_error.__cause__ = exc
                errors.append(cleanup_error)
            except Exception as exc:
                errors.append(exc)
        self._raise_cleanup_errors(errors)

    def _claim_resources(self) -> list[ManagedResource] | None:
        with self._close_lock:
            if self._closed:
                return None
            self._closed = True
            return list(self._resources)

    @staticmethod
    def _close_resource(resource: ManagedResource) -> None:
        if resource.close is not None:
            result = resource.close()
            if inspect.isawaitable(result):
                _run_awaitable(result)
            return
        if resource.aclose is not None:
            result = resource.aclose()
            if inspect.isawaitable(result):
                _run_awaitable(result)

    def _raise_cleanup_errors(self, errors: list[Exception]) -> None:
        if not errors:
            return
        self._logger.error(
            "sdk.close.failed",
            extra={"dms_event": "sdk.close.failed", "failure_count": len(errors)},
        )
        raise ResourceCleanupError(
            "One or more managed resources failed to close",
            errors=tuple(errors),
        )


def _run_awaitable(awaitable: Awaitable[object]) -> object:
    coroutine = _await_result(awaitable)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coroutine).result()


async def _await_result(awaitable: Awaitable[object]) -> object:
    return await awaitable
