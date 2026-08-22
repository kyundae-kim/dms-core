from __future__ import annotations

from hashlib import sha256


def user_storage_segment(user_id: str) -> str:
    """Return a path-safe, non-reversible storage segment for a user."""
    return sha256(user_id.encode("utf-8")).hexdigest()


def user_storage_prefix(user_id: str) -> str:
    return f"documents/users/{user_storage_segment(user_id)}/"


def user_operation_scope_prefix(user_id: str) -> str:
    return f"user:{user_storage_segment(user_id)}:"


def user_operation_scope(user_id: str, scope: str) -> str:
    """Namespace idempotency records without exposing the user id in a key."""
    return f"{user_operation_scope_prefix(user_id)}{scope}"
