from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from dms.domain.interfaces import MetadataConflictError
from dms.domain.models import DocumentMetadata, DocumentStatus
from dms.infrastructure.metadata.sqlalchemy import (
    SqlAlchemyMetadataStore,
    _build_record_types,
)


class AsyncSqlAlchemyMetadataStore(SqlAlchemyMetadataStore):
    """Async SQLAlchemy ORM adapter sharing the sync store's domain mapping."""

    def __init__(
        self,
        engine: AsyncEngine,
        *,
        table_name: str = "document_metadata",
    ) -> None:
        self._engine = engine
        self._record_type, self._id_record_type = _build_record_types(table_name)
        self._session_factory = async_sessionmaker(
            bind=self._engine,
            expire_on_commit=False,
        )
        self._initialized = False
        self._initialize_lock: asyncio.Lock | None = None

    async def initialize(self) -> None:
        if self._initialized:
            return
        if self._initialize_lock is None:
            self._initialize_lock = asyncio.Lock()
        async with self._initialize_lock:
            if self._initialized:
                return
            async with self._engine.begin() as connection:
                await connection.run_sync(self._record_type.metadata.create_all)
            self._initialized = True

    async def allocate_document_id(self) -> str:
        async with self._session_factory.begin() as session:
            while True:
                sequence_record = self._id_record_type()
                session.add(sequence_record)
                await session.flush()
                document_id = str(sequence_record.id)
                if await session.get(self._record_type, document_id) is None:
                    return document_id

    async def save_metadata(self, metadata: DocumentMetadata) -> DocumentMetadata:
        try:
            async with self._session_factory.begin() as session:
                session.add(self._from_domain(metadata))
        except IntegrityError as exc:
            raise MetadataConflictError(metadata.document_id) from exc
        return metadata

    async def update_metadata(self, metadata: DocumentMetadata) -> DocumentMetadata:
        async with self._session_factory.begin() as session:
            if await session.get(self._record_type, metadata.document_id) is None:
                raise LookupError(metadata.document_id)
            await session.merge(self._from_domain(metadata))
        return metadata

    async def get_metadata(self, document_id: str) -> DocumentMetadata:
        async with self._session_factory() as session:
            record = await session.get(self._record_type, document_id)
        if record is None:
            raise LookupError(document_id)
        return self._to_domain(record)

    async def list_metadata(
        self,
        *,
        offset: int,
        limit: int,
        status: DocumentStatus | None = None,
        excluded_statuses: tuple[DocumentStatus, ...] = (),
    ) -> list[DocumentMetadata]:
        statement = self._metadata_statement(
            status=status,
            excluded_statuses=excluded_statuses,
        ).order_by(
            self._record_type.created_at.desc(),
            self._record_type.document_id.desc(),
        ).offset(offset).limit(limit)
        async with self._session_factory() as session:
            records = (await session.scalars(statement)).all()
        return [self._to_domain(record) for record in records]

    async def list_metadata_page(
        self,
        *,
        after_created_at: datetime | None = None,
        after_document_id: str | None = None,
        limit: int,
        status: DocumentStatus | None = None,
        excluded_statuses: tuple[DocumentStatus, ...] = (),
    ) -> list[DocumentMetadata]:
        statement = self._metadata_statement(
            status=status,
            excluded_statuses=excluded_statuses,
        )
        if after_created_at is not None:
            if after_document_id is None:
                raise ValueError("after_document_id is required with after_created_at")
            statement = statement.where(
                or_(
                    self._record_type.created_at < after_created_at,
                    and_(
                        self._record_type.created_at == after_created_at,
                        self._record_type.document_id < after_document_id,
                    ),
                )
            )
        statement = statement.order_by(
            self._record_type.created_at.desc(),
            self._record_type.document_id.desc(),
        ).limit(limit)
        async with self._session_factory() as session:
            records = (await session.scalars(statement)).all()
        return [self._to_domain(record) for record in records]

    async def mark_deleted(self, document_id: str) -> DocumentMetadata:
        metadata = await self.get_metadata(document_id)
        now = datetime.now(UTC)
        deleted = replace(
            metadata,
            status=DocumentStatus.DELETED,
            deleted_at=now,
            updated_at=now,
        )
        await self.update_metadata(deleted)
        return deleted

    async def hard_delete(self, document_id: str) -> None:
        async with self._session_factory.begin() as session:
            record = await session.get(self._record_type, document_id)
            if record is None:
                raise LookupError(document_id)
            await session.delete(record)

    async def clear_all(self) -> int:
        async with self._session_factory.begin() as session:
            records = (await session.scalars(select(self._record_type))).all()
            for record in records:
                await session.delete(record)
        return len(records)

    async def exists(self, document_id: str) -> bool:
        async with self._session_factory() as session:
            return await session.get(self._record_type, document_id) is not None

    def _from_domain(self, metadata: DocumentMetadata) -> Any:
        return super()._from_domain(metadata)
