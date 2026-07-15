from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Index, Integer, String, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from dms.domain.models import DocumentMetadata, DocumentStatus


class PostgresMetadataStore:
    def __init__(self, engine: Engine, *, table_name: str = "document_metadata") -> None:
        self._engine = engine
        self._record_type: Any = _build_record_type(table_name)
        self._session_factory = sessionmaker(bind=self._engine, expire_on_commit=False)
        self._record_type.metadata.create_all(self._engine)

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
        with self._session_factory.begin() as session:
            session.add(self._from_domain(metadata))
        return metadata

    def update_metadata(self, metadata: DocumentMetadata) -> DocumentMetadata:
        with self._session_factory.begin() as session:
            if session.get(self._record_type, metadata.document_id) is None:
                raise LookupError(metadata.document_id)
            session.merge(self._from_domain(metadata))
        return metadata

    def get_metadata(self, document_id: str) -> DocumentMetadata:
        with self._session_factory() as session:
            record = session.get(self._record_type, document_id)
        if record is None:
            raise LookupError(document_id)
        return self._to_domain(record)

    def list_metadata(
        self,
        *,
        offset: int,
        limit: int,
        status: DocumentStatus | None = None,
    ) -> list[DocumentMetadata]:
        statement = select(self._record_type)
        if status is not None:
            statement = statement.where(self._record_type.status == status.value)
        statement = statement.order_by(
            self._record_type.created_at.desc(),
            self._record_type.document_id.desc(),
        ).offset(offset).limit(limit)
        with self._session_factory() as session:
            records = session.scalars(statement).all()
        return [self._to_domain(record) for record in records]

    def mark_deleted(self, document_id: str) -> DocumentMetadata:
        metadata = self.get_metadata(document_id)
        deleted = replace(
            metadata,
            status=DocumentStatus.DELETED,
            deleted_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.update_metadata(deleted)
        return deleted

    def hard_delete(self, document_id: str) -> None:
        with self._session_factory.begin() as session:
            record = session.get(self._record_type, document_id)
            if record is None:
                raise LookupError(document_id)
            session.delete(record)

    def exists(self, document_id: str) -> bool:
        with self._session_factory() as session:
            return session.get(self._record_type, document_id) is not None

    def _from_domain(self, metadata: DocumentMetadata) -> Any:
        return self._record_type(
            document_id=metadata.document_id,
            original_filename=metadata.original_filename,
            content_type=metadata.content_type,
            file_size=metadata.file_size,
            storage_key=metadata.storage_key,
            status=metadata.status.value,
            created_at=metadata.created_at,
            updated_at=metadata.updated_at,
            checksum=metadata.checksum,
            deleted_at=metadata.deleted_at,
            created_by=metadata.created_by,
            extra_metadata=dict(metadata.extra_metadata),
        )

    @staticmethod
    def _to_domain(record: Any) -> DocumentMetadata:
        return DocumentMetadata(
            document_id=record.document_id,
            original_filename=record.original_filename,
            content_type=record.content_type,
            file_size=record.file_size,
            storage_key=record.storage_key,
            status=DocumentStatus(record.status),
            created_at=record.created_at,
            updated_at=record.updated_at,
            checksum=record.checksum,
            deleted_at=record.deleted_at,
            created_by=record.created_by,
            extra_metadata=dict(record.extra_metadata or {}),
        )


def _build_record_type(table_name: str) -> Any:
    class _StoreOrmBase(DeclarativeBase):
        pass

    class DocumentMetadataRecord(_StoreOrmBase):
        __tablename__ = table_name
        __table_args__ = (
            Index(f"ix_{table_name}_storage_key", "storage_key"),
            Index(f"ix_{table_name}_status", "status"),
            Index(f"ix_{table_name}_created_at", "created_at"),
        )

        document_id: Mapped[str] = mapped_column(String(255), primary_key=True)
        original_filename: Mapped[str] = mapped_column(String(1024), nullable=False)
        content_type: Mapped[str] = mapped_column(String(255), nullable=False)
        file_size: Mapped[int] = mapped_column(Integer, nullable=False)
        storage_key: Mapped[str] = mapped_column(String(2048), nullable=False)
        status: Mapped[str] = mapped_column(String(32), nullable=False)
        created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
        updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
        checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
        deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
        created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
        extra_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    return DocumentMetadataRecord
