from __future__ import annotations

import logging
from collections.abc import Mapping


def build_log_extra(event: str, context: Mapping[str, object]) -> dict[str, object]:
    return {"dms_event": event, **{f"dms_{key}": value for key, value in context.items()}}


class _LoggingMixin:
    """Share the SDK service logging contract without duplicating wrappers."""

    _logger: logging.Logger

    def _log_info(self, event: str, **context: object) -> None:
        self._logger.info(event, extra=build_log_extra(event, context))

    def _log_warning(self, event: str, **context: object) -> None:
        self._logger.warning(event, extra=build_log_extra(event, context))

    def _log_exception(self, event: str, exc: Exception, **context: object) -> None:
        self._logger.exception(
            event,
            extra=build_log_extra(event, {**context, "error_type": type(exc).__name__}),
        )
