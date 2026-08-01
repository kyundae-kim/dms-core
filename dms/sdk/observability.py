from __future__ import annotations

from collections.abc import Mapping


def build_log_extra(event: str, context: Mapping[str, object]) -> dict[str, object]:
    return {"dms_event": event, **{f"dms_{key}": value for key, value in context.items()}}
