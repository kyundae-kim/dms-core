from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, TypeAlias


class MetadataValidator(Protocol):
    """Validate and normalize user metadata without mutating the input."""

    def __call__(self, metadata: Mapping[str, Any]) -> dict[str, Any]: ...


MetadataNormalizer: TypeAlias = Callable[[Mapping[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class DefaultMetadataPolicy:
    max_serialized_bytes: int = 16_384
    max_depth: int = 8
    blocked_keys: frozenset[str] = frozenset({
        "password", "passwd", "secret", "token", "api_key", "apikey",
        "access_token", "refresh_token", "authorization", "credential",
        "credentials", "private_key",
    })

    def __post_init__(self) -> None:
        if self.max_serialized_bytes <= 0:
            raise ValueError("max_serialized_bytes must be positive")
        if self.max_depth < 1:
            raise ValueError("max_depth must be at least 1")

    def __call__(self, metadata: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(metadata, Mapping):
            raise TypeError("metadata must be a mapping")
        normalized = dict(metadata)
        for key in normalized:
            if not isinstance(key, str):
                raise ValueError("metadata top-level keys must be strings")
            if key.casefold() in self.blocked_keys:
                raise ValueError(f"metadata key is blocked: {key}")
        self._check_depth(normalized, 1)
        try:
            encoded = json.dumps(normalized, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("metadata must be JSON-serializable") from exc
        if len(encoded) > self.max_serialized_bytes:
            raise ValueError(f"metadata exceeds {self.max_serialized_bytes} serialized bytes")
        # JSON round-trip gives callers an isolated, canonical JSON-compatible dictionary.
        return json.loads(encoded.decode("utf-8"))

    def _check_depth(self, value: Any, depth: int) -> None:
        if depth > self.max_depth:
            raise ValueError(f"metadata exceeds maximum depth {self.max_depth}")
        if isinstance(value, Mapping):
            for child in value.values():
                self._check_depth(child, depth + 1)
        elif isinstance(value, (list, tuple)):
            for child in value:
                self._check_depth(child, depth + 1)
