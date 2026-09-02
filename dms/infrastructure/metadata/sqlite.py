from __future__ import annotations

from dms.infrastructure.metadata.sqlalchemy import SqlAlchemyMetadataStore


class SqliteMetadataStore(SqlAlchemyMetadataStore):
    """SQLite entry point for the shared SQLAlchemy ORM store."""
