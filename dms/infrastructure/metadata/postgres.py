from __future__ import annotations

from dms.infrastructure.metadata.sqlalchemy import SqlAlchemyMetadataStore


class PostgresMetadataStore(SqlAlchemyMetadataStore):
    """PostgreSQL entry point for the shared SQLAlchemy ORM store."""
