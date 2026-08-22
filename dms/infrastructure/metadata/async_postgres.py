from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from dms.infrastructure.metadata.async_sqlalchemy import AsyncSqlAlchemyMetadataStore


class AsyncPostgresMetadataStore(AsyncSqlAlchemyMetadataStore):
    """PostgreSQL entry point for the shared async SQLAlchemy ORM store."""

    def __init__(
        self,
        engine: AsyncEngine,
        *,
        table_name: str = "document_metadata",
    ) -> None:
        super().__init__(engine, table_name=table_name)
