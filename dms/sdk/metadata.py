from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeAlias

from dms.sdk.errors import ValidationError


class MetadataValidator(Protocol):
    """Validate and normalize user metadata without mutating the input."""

    def __call__(self, metadata: Mapping[str, Any]) -> dict[str, Any]: ...


MetadataNormalizer: TypeAlias = Callable[[Mapping[str, Any]], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class MetadataValidationIssue:
    """A machine-readable metadata problem at ``path``."""
    path: tuple[str | int, ...]
    code: str
    message: str


class MetadataSchemaValidationError(ValidationError):
    """Structured schema failure with field-level ``issues``."""
    def __init__(self, issues: list[MetadataValidationIssue] | tuple[MetadataValidationIssue, ...]) -> None:
        self.issues = tuple(issues)
        super().__init__("Invalid document metadata schema: " + "; ".join(
            f"{'.'.join(map(str, issue.path)) or '<root>'}: {issue.message}" for issue in self.issues))


@dataclass(frozen=True, slots=True)
class StructuredMetadataValidator:
    """Dependency-free adapter around a parser/model callable.

    The parser receives a mapping and returns a mapping. Model libraries can
    be bridged by supplying a model-to-mapping ``projector`` callable.
    """
    parser: Callable[[Mapping[str, Any]], object]
    schema_version: str
    version_field: str = "schema_version"
    projector: Callable[[object], Mapping[str, Any]] | None = None
    policy: MetadataValidator = field(default_factory=lambda: DefaultMetadataPolicy())

    def __call__(self, metadata: Mapping[str, Any]) -> dict[str, Any]:
        actual = metadata.get(self.version_field)
        if actual != self.schema_version:
            raise MetadataSchemaValidationError([MetadataValidationIssue(
                (self.version_field,), "schema_version",
                f"expected {self.schema_version!r}, got {actual!r}")])
        parsed = self.parser(dict(metadata))
        projected = self.projector(parsed) if self.projector is not None else parsed
        if not isinstance(projected, Mapping):
            raise MetadataSchemaValidationError([MetadataValidationIssue(
                (), "parser_result", "parser must produce a mapping")])
        return self.policy(projected)


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
        self._check_keys(normalized)
        self._check_depth(normalized, 1)
        try:
            encoded = json.dumps(normalized, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("metadata must be JSON-serializable") from exc
        if len(encoded) > self.max_serialized_bytes:
            raise ValueError(f"metadata exceeds {self.max_serialized_bytes} serialized bytes")
        # JSON round-trip gives callers an isolated, canonical JSON-compatible dictionary.
        return json.loads(encoded.decode("utf-8"))

    def _check_keys(self, value: Any) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                if not isinstance(key, str):
                    raise ValueError("metadata keys must be strings")
                if key.casefold() in self.blocked_keys:
                    raise ValueError(f"metadata key is blocked: {key}")
                self._check_keys(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                self._check_keys(child)

    def _check_depth(self, value: Any, depth: int) -> None:
        if depth > self.max_depth:
            raise ValueError(f"metadata exceeds maximum depth {self.max_depth}")
        if isinstance(value, Mapping):
            for child in value.values():
                self._check_depth(child, depth + 1)
        elif isinstance(value, (list, tuple)):
            for child in value:
                self._check_depth(child, depth + 1)
