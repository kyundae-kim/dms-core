from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from time import perf_counter

from dms.sdk.errors import MetadataStoreError
from dms.sdk.types import HealthStatus, ServiceHealth


class LifecycleService:
    def __init__(
        self,
        *,
        service_checks: Mapping[str, Callable[[], object]],
        close_callbacks: list[Callable[[], object]],
        logger: logging.Logger,
    ) -> None:
        self._service_checks = service_checks
        self._close_callbacks = close_callbacks
        self._logger = logger
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def check_health(self) -> HealthStatus:
        services: list[ServiceHealth] = []
        overall_ok = True
        for name, check in self._service_checks.items():
            started = perf_counter()
            try:
                check()
            except Exception as exc:
                overall_ok = False
                services.append(ServiceHealth(service=name, ok=False,
                    latency_ms=(perf_counter() - started) * 1000, error=str(exc)))
            else:
                services.append(ServiceHealth(service=name, ok=True,
                    latency_ms=(perf_counter() - started) * 1000, error=None))
        return HealthStatus(ok=overall_ok, services=services, checked_at=datetime.now(UTC))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        errors: list[Exception] = []
        for callback in self._close_callbacks:
            try:
                callback()
            except Exception as exc:
                errors.append(exc)
        if errors:
            self._logger.exception("sdk.close.failed", extra={"dms_event": "sdk.close.failed"})
            raise MetadataStoreError("One or more cleanup callbacks failed") from errors[0]
