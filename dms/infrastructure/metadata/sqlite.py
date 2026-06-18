from __future__ import annotations

from sqlalchemy.engine import Engine

from dms.infrastructure.metadata.postgres import PostgresMetadataStore


class SqliteMetadataStore(PostgresMetadataStore):
    def __init__(self, engine: Engine, *, table_name: str = "document_metadata") -> None:
        super().__init__(engine, table_name=table_name)
