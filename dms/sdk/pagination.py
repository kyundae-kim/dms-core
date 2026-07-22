from __future__ import annotations

import base64
import json
from datetime import datetime

from dms.domain.models import DocumentStatus
from dms.sdk.errors import ValidationError

MAX_CURSOR_LENGTH = 4096


def encode_cursor(
    created_at: datetime,
    document_id: str,
    status: DocumentStatus | None,
    page_size: int,
) -> str:
    if (
        created_at.tzinfo is None
        or created_at.utcoffset() is None
        or not document_id.strip()
        or page_size <= 0
    ):
        raise ValidationError("invalid document list cursor state")
    payload = json.dumps(
        {
            "v": 2,
            "t": created_at.isoformat(),
            "i": document_id,
            "s": status.value if status is not None else None,
            "p": page_size,
        },
        separators=(",", ":"),
    ).encode()
    encoded = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    if len(encoded) > MAX_CURSOR_LENGTH:
        raise ValidationError("document list cursor exceeds maximum length")
    return encoded


def decode_cursor(cursor: str) -> tuple[datetime, str, str | None, int]:
    try:
        if not isinstance(cursor, str) or not cursor or len(cursor) > MAX_CURSOR_LENGTH:
            raise ValueError
        payload = base64.b64decode(
            cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True
        )
        value = json.loads(payload)
        if not isinstance(value, dict) or set(value) != {"v", "t", "i", "s", "p"}:
            raise ValueError
        if type(value["v"]) is not int or value["v"] != 2:
            raise ValueError
        if (
            not isinstance(value["t"], str)
            or not isinstance(value["i"], str)
            or not value["i"].strip()
        ):
            raise ValueError
        if value["s"] is not None and (
            not isinstance(value["s"], str)
            or value["s"] not in {status.value for status in DocumentStatus}
        ):
            raise ValueError
        if type(value["p"]) is not int or value["p"] <= 0:
            raise ValueError
        created_at = datetime.fromisoformat(value["t"])
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError
        return created_at, value["i"], value["s"], value["p"]
    except Exception as exc:
        raise ValidationError("invalid document list cursor") from exc
