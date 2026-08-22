from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Index,
    Integer,
    String,
    and_,
    inspect,
    or_,
    select,
)
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from dms.domain.models import DocumentMetadata, DocumentStatus


class SqlAlchemyMetadataStore:
    def __init__(self, engine: Engine, *, table_name: str = "document_metadata") -> None:
        self._engine = engine
        self._record_type, self._id_record_type = _build_record_types(table_name)
        self._session_factory = sessionmaker(bind=self._engine, expire_on_commit=False)
        with self._engine.begin() as connection:
            self._record_type.metadata.create_all(connection)
            self._ensure_user_id_schema(connection)

    def allocate_document_id(self) -> str:
        """Return a document identifier from the database auto-increment sequence."""
        with self._session_factory.begin() as session:
            while True:
                sequence_record = self._id_record_type()
                session.add(sequence_record)
                session.flush()
                document_id = str(sequence_record.id)
                if session.get(self._record_type, document_id) is None:
                    return document_id

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
        user_id: str | None = None,
        extra_metadata: Any = None,
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
            user_id=user_id,
            extra_metadata=extra_metadata if extra_metadata is not None else {},
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

    def get_metadata(self, document_id: str, *, user_id: str | None = None) -> DocumentMetadata:
        with self._session_factory() as session:
            statement = select(self._record_type).where(
                self._record_type.document_id == document_id
            )
            if user_id is not None:
                statement = statement.where(self._record_type.user_id == user_id)
            record = session.scalar(statement)
        if record is None:
            raise LookupError(document_id)
        return self._to_domain(record)

    def list_metadata(
        self,
        *,
        offset: int,
        limit: int,
        status: DocumentStatus | None = None,
        excluded_statuses: tuple[DocumentStatus, ...] = (),
        user_id: str | None = None,
        unscoped_only: bool = False,
    ) -> list[DocumentMetadata]:
        statement = self._metadata_statement(
            status=status,
            excluded_statuses=excluded_statuses,
            user_id=user_id,
            unscoped_only=unscoped_only,
        )
        statement = statement.order_by(
            self._record_type.created_at.desc(),
            self._record_type.document_id.desc(),
        ).offset(offset).limit(limit)
        with self._session_factory() as session:
            records = session.scalars(statement).all()
        return [self._to_domain(record) for record in records]

    def list_metadata_page(
        self,
        *,
        after_created_at: datetime | None = None,
        after_document_id: str | None = None,
        limit: int,
        status: DocumentStatus | None = None,
        excluded_statuses: tuple[DocumentStatus, ...] = (),
        user_id: str | None = None,
        unscoped_only: bool = False,
    ) -> list[DocumentMetadata]:
        statement = self._metadata_statement(
            status=status,
            excluded_statuses=excluded_statuses,
            user_id=user_id,
            unscoped_only=unscoped_only,
        )
        if after_created_at is not None:
            if after_document_id is None:
                raise ValueError("after_document_id is required with after_created_at")
            statement = statement.where(or_(
                self._record_type.created_at < after_created_at,
                and_(self._record_type.created_at == after_created_at,
                     self._record_type.document_id < after_document_id),
            ))
        statement = statement.order_by(
            self._record_type.created_at.desc(), self._record_type.document_id.desc()
        ).limit(limit)
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

    def clear_all(self, *, user_id: str | None = None) -> int:
        with self._session_factory.begin() as session:
            statement = select(self._record_type)
            if user_id is not None:
                statement = statement.where(self._record_type.user_id == user_id)
            records = session.scalars(statement).all()
            for record in records:
                session.delete(record)
        return len(records)

    def exists(self, document_id: str, *, user_id: str | None = None) -> bool:
        with self._session_factory() as session:
            statement = select(self._record_type.document_id).where(
                self._record_type.document_id == document_id
            )
            if user_id is not None:
                statement = statement.where(self._record_type.user_id == user_id)
            return session.scalar(statement) is not None

    def _metadata_statement(
        self,
        *,
        status: DocumentStatus | None,
        excluded_statuses: tuple[DocumentStatus, ...],
        user_id: str | None = None,
        unscoped_only: bool = False,
    ) -> Any:
        statement = select(self._record_type)
        if unscoped_only:
            statement = statement.where(self._record_type.user_id.is_(None))
        elif user_id is not None:
            statement = statement.where(self._record_type.user_id == user_id)
        if status is not None:
            statement = statement.where(self._record_type.status == status.value)
        if excluded_statuses:
            statement = statement.where(
                self._record_type.status.not_in(
                    tuple(item.value for item in excluded_statuses)
                )
            )
        return statement

    def _ensure_user_id_schema(self, connection: Connection) -> None:
        table = self._record_type.__table__
        inspector = inspect(connection)
        columns = {column["name"] for column in inspector.get_columns(table.name)}
        if "user_id" not in columns:
            quoted_table = connection.dialect.identifier_preparer.quote(table.name)
            connection.exec_driver_sql(
                f"ALTER TABLE {quoted_table} ADD COLUMN user_id VARCHAR(255)"
            )
        indexes = {index["name"] for index in inspector.get_indexes(table.name)}
        index_name = f"ix_{table.name}_user_id"
        if index_name not in indexes:
            quoted_table = connection.dialect.identifier_preparer.quote(table.name)
            quoted_index = connection.dialect.identifier_preparer.quote(index_name)
            connection.exec_driver_sql(
                f"CREATE INDEX {quoted_index} ON {quoted_table} (user_id)"
            )

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
            user_id=metadata.user_id,
            extra_metadata=metadata.extra_metadata,
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
            created_at=_as_utc(record.created_at),
            updated_at=_as_utc(record.updated_at),
            checksum=record.checksum,
            deleted_at=(
                _as_utc(record.deleted_at) if record.deleted_at is not None else None
            ),
            created_by=record.created_by,
            user_id=record.user_id,
            extra_metadata=record.extra_metadata if record.extra_metadata is not None else {},
        )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _build_record_types(table_name: str) -> tuple[Any, Any]:
    class _StoreOrmBase(DeclarativeBase):
        pass

    class DocumentMetadataRecord(_StoreOrmBase):
        __tablename__ = table_name
        __table_args__ = (
            Index(f"ix_{table_name}_storage_key", "storage_key"),
            Index(f"ix_{table_name}_status", "status"),
            Index(f"ix_{table_name}_created_at", "created_at"),
            Index(f"ix_{table_name}_user_id", "user_id"),
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
        user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
        extra_metadata: Mapped[Any] = mapped_column(JSON, nullable=False)

    class DocumentIdSequenceRecord(_StoreOrmBase):
        __tablename__ = f"{table_name}_id_sequence"

        id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    return DocumentMetadataRecord, DocumentIdSequenceRecord