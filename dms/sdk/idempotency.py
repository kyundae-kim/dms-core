from __future__ import annotations

import json
from hashlib import sha256


def build_upload_fingerprint(
    *,
    checksum: str,
    filename: str,
    content_type: str,
    size: int,
    document_id: str | None,
) -> str:
    payload = {
        "checksum": checksum.lower(),
        "filename": filename,
        "content_type": content_type,
        "size": size,
        "document_id": document_id,
    }
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    return sha256(serialized).hexdigest()
