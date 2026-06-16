from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Index, Integer, MetaData, String, Table, delete, insert, select, update
from sqlalchemy.engine import Engine, RowMapping

from dms.domain.models import DocumentMetadata, DocumentStatus


class PostgresMetadataStore:
    def __init__(self, engine: Engine, *, table_name: str = "document_metadata") -> None:
        self._engine = engine
        self._metadata = MetaData()
        self._table = Table(
            table_name,
            self._metadata,
            *self._build_columns(),
            *self._build_indexes(table_name),
        )
        self._metadata.create_all(self._engine)

    @staticmethod
    def _build_columns() -> tuple[object, ...]:
        from sqlalchemy import Column

        return (
            Column("document_id", String(255), primary_key=True),
            Column("original_filename", String(1024), nullable=False),
            Column("content_type", String(255), nullable=False),
            Column("file_size", Integer, nullable=False),
            Column("storage_key", String(2048), nullable=False),
            Column("status", String(32), nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False),
            Column("checksum", String(128), nullable=True),
            Column("deleted_at", DateTime(timezone=True), nullable=True),
            Column("created_by", String(255), nullable=True),
            Column("extra_metadata", JSON, nullable=False),
        )

    @staticmethod
    def _build_indexes(table_name: str) -> tuple[Index, ...]:
        return (
            Index(f"ix_{table_name}_storage_key", "storage_key"),
            Index(f"ix_{table_name}_status", "status"),
            Index(f"ix_{table_name}_created_at", "created_at"),
        )

    def build_metadata(
        self,
        *,
        document_id: str,
        filename: str,
        content_type: str,
        file_size: int,
        storage_key: str,
        checksum: str | None,
        created_by: str | None,
        extra_metadata: dict[str, Any] | None = None,
        status: DocumentStatus = DocumentStatus.AVAILABLE,
    ) -> DocumentMetadata:
        now = datetime.now(UTC)
        return DocumentMetadata(
            document_id=document_id,
            original_filename=filename,
            content_type=content_type,
            file_size=file_size,
            storage_key=storage_key,
            status=status,
            created_at=now,
            updated_at=now,
            checksum=checksum,
            deleted_at=None,
            created_by=created_by,
            extra_metadata=dict(extra_metadata or {}),
        )

    def save_metadata(self, metadata: DocumentMetadata) -> DocumentMetadata:
        payload = self._to_record(metadata)
        with self._engine.begin() as connection:
            exists = connection.execute(
                select(self._table.c.document_id).where(self._table.c.document_id == metadata.document_id)
            ).first()
            if exists is None:
                connection.execute(insert(self._table).values(**payload))
            else:
                connection.execute(
                    update(self._table)
                    .where(self._table.c.document_id == metadata.document_id)
                    .values(**payload)
                )
        return metadata

    def get_metadata(self, document_id: str) -> DocumentMetadata:
        with self._engine.begin() as connection:
            row = connection.execute(
                select(self._table).where(self._table.c.document_id == document_id)
            ).mappings().first()
        if row is None:
            raise LookupError(document_id)
        return self._from_row(row)

    def mark_deleted(self, document_id: str) -> DocumentMetadata:
        metadata = self.get_metadata(document_id)
        deleted = replace(
            metadata,
            status=DocumentStatus.DELETED,
            deleted_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.save_metadata(deleted)
        return deleted

    def hard_delete(self, document_id: str) -> None:
        with self._engine.begin() as connection:
            result = connection.execute(
                delete(self._table).where(self._table.c.document_id == document_id)
            )
        if result.rowcount == 0:
            raise LookupError(document_id)

    def exists(self, document_id: str) -> bool:
        with self._engine.begin() as connection:
            row = connection.execute(
                select(self._table.c.document_id).where(self._table.c.document_id == document_id)
            ).first()
        return row is not None

    @staticmethod
    def _to_record(metadata: DocumentMetadata) -> dict[str, Any]:
        return {
            "document_id": metadata.document_id,
            "original_filename": metadata.original_filename,
            "content_type": metadata.content_type,
            "file_size": metadata.file_size,
            "storage_key": metadata.storage_key,
            "status": metadata.status.value,
            "created_at": metadata.created_at,
            "updated_at": metadata.updated_at,
            "checksum": metadata.checksum,
            "deleted_at": metadata.deleted_at,
            "created_by": metadata.created_by,
            "extra_metadata": dict(metadata.extra_metadata),
        }

    @staticmethod
    def _from_row(row: RowMapping) -> DocumentMetadata:
        return DocumentMetadata(
            document_id=row["document_id"],
            original_filename=row["original_filename"],
            content_type=row["content_type"],
            file_size=row["file_size"],
            storage_key=row["storage_key"],
            status=DocumentStatus(row["status"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            checksum=row["checksum"],
            deleted_at=row["deleted_at"],
            created_by=row["created_by"],
            extra_metadata=dict(row["extra_metadata"] or {}),
        )
