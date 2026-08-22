from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from dms.domain.models import (
    UploadOperation,
    UploadOperationClaim,
    UploadOperationState,
)
from dms.infrastructure.metadata.operations import UploadOperationRecord, _Base
from dms.sdk.errors import IdempotencyConflictError


class AsyncSqlAlchemyUploadOperationStore:
    """Async persistent upload claim store for PostgreSQL and SQLite."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)
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
                await connection.run_sync(_Base.metadata.create_all)
            self._initialized = True

    async def claim(
        self,
        *,
        scope: str,
        idempotency_key: str,
        fingerprint: str,
        document_id: str,
    ) -> UploadOperationClaim:
        now = datetime.now(UTC)
        try:
            async with self._sessions.begin() as session:
                record = UploadOperationRecord(
                    scope=scope,
                    idempotency_key=idempotency_key,
                    fingerprint=fingerprint,
                    document_id=document_id,
                    state=UploadOperationState.PENDING.value,
                    created_at=now,
                    updated_at=now,
                )
                session.add(record)
                await session.flush()
            return UploadOperationClaim(operation=self._domain(record), claimed=True)
        except IntegrityError:
            pass

        while True:
            async with self._sessions.begin() as session:
                record = await session.scalar(
                    select(UploadOperationRecord)
                    .where(
                        UploadOperationRecord.scope == scope,
                        UploadOperationRecord.idempotency_key == idempotency_key,
                    )
                    .with_for_update()
                )
                if record is None:  # a concurrent transaction rolled back; retry after closing this transaction
                    continue
                if record.fingerprint != fingerprint:
                    raise IdempotencyConflictError(
                        "Idempotency key was used with a different upload request"
                    )
                if record.state == UploadOperationState.FAILED.value:
                    changed = (
                        await session.execute(
                            update(UploadOperationRecord)
                            .where(
                                UploadOperationRecord.scope == scope,
                                UploadOperationRecord.idempotency_key == idempotency_key,
                                UploadOperationRecord.state
                                == UploadOperationState.FAILED.value,
                            )
                            .values(
                                state=UploadOperationState.PENDING.value,
                                updated_at=now,
                            )
                        )
                    ).rowcount
                    if changed:
                        record.state = UploadOperationState.PENDING.value
                        record.updated_at = now
                        return UploadOperationClaim(
                            operation=self._domain(record),
                            claimed=True,
                        )
                return UploadOperationClaim(operation=self._domain(record), claimed=False)

    async def get(self, *, scope: str, idempotency_key: str) -> UploadOperation:
        async with self._sessions() as session:
            record = await session.scalar(
                select(UploadOperationRecord).where(
                    UploadOperationRecord.scope == scope,
                    UploadOperationRecord.idempotency_key == idempotency_key,
                )
            )
        if record is None:
            raise LookupError((scope, idempotency_key))
        return self._domain(record)

    async def mark_succeeded(self, *, scope: str, idempotency_key: str) -> None:
        await self._mark(scope, idempotency_key, UploadOperationState.SUCCEEDED)

    async def mark_failed(self, *, scope: str, idempotency_key: str) -> None:
        await self._mark(scope, idempotency_key, UploadOperationState.FAILED)

    async def clear_all(self, *, scope_prefix: str | None = None) -> int:
        async with self._sessions.begin() as session:
            statement = select(UploadOperationRecord)
            if scope_prefix is not None:
                statement = statement.where(UploadOperationRecord.scope.like(f"{scope_prefix}%"))
            records = (await session.scalars(statement)).all()
            for record in records:
                await session.delete(record)
        return len(records)

    async def _mark(self, scope: str, key: str, state: UploadOperationState) -> None:
        async with self._sessions.begin() as session:
            await session.execute(
                update(UploadOperationRecord)
                .where(
                    UploadOperationRecord.scope == scope,
                    UploadOperationRecord.idempotency_key == key,
                    UploadOperationRecord.state == UploadOperationState.PENDING.value,
                )
                .values(state=state.value, updated_at=datetime.now(UTC))
            )

    @staticmethod
    def _domain(record: Any) -> UploadOperation:
        return UploadOperation(
            scope=record.scope,
            idempotency_key=record.idempotency_key,
            fingerprint=record.fingerprint,
            document_id=record.document_id,
            state=UploadOperationState(record.state),
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
