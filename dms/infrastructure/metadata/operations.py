from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, String, UniqueConstraint, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from dms.domain.models import UploadOperation, UploadOperationClaim, UploadOperationState
from dms.sdk.errors import IdempotencyConflictError


class _Base(DeclarativeBase):
    pass


class UploadOperationRecord(_Base):
    __tablename__ = "upload_operations"
    __table_args__ = (UniqueConstraint("scope", "idempotency_key", name="uq_upload_operation_scope_key"),)

    scope: Mapped[str] = mapped_column(String(255), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    document_id: Mapped[str] = mapped_column(String(255), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SqlAlchemyUploadOperationStore:
    """Persistent atomic upload claim store for PostgreSQL and SQLite.

    A failed claim is explicitly retryable: the next matching claim atomically moves
    it back to pending and reuses its original document id.
    """

    def __init__(self, engine: Engine) -> None:
        self._sessions = sessionmaker(engine, expire_on_commit=False)
        _Base.metadata.create_all(engine)

    def claim(self, *, scope: str, idempotency_key: str, fingerprint: str,
              document_id: str) -> UploadOperationClaim:
        now = datetime.now(UTC)
        try:
            with self._sessions.begin() as session:
                record = UploadOperationRecord(scope=scope, idempotency_key=idempotency_key,
                    fingerprint=fingerprint, document_id=document_id,
                    state=UploadOperationState.PENDING.value, created_at=now, updated_at=now)
                session.add(record)
                session.flush()
            return UploadOperationClaim(operation=self._domain(record), claimed=True)
        except IntegrityError:
            pass

        with self._sessions.begin() as session:
            record = session.scalar(select(UploadOperationRecord).where(
                UploadOperationRecord.scope == scope,
                UploadOperationRecord.idempotency_key == idempotency_key).with_for_update())
            if record is None:  # a concurrent transaction rolled back; retry insertion
                return self.claim(scope=scope, idempotency_key=idempotency_key,
                                  fingerprint=fingerprint, document_id=document_id)
            if record.fingerprint != fingerprint:
                raise IdempotencyConflictError("Idempotency key was used with a different upload request")
            if record.state == UploadOperationState.FAILED.value:
                changed = session.execute(update(UploadOperationRecord).where(
                    UploadOperationRecord.scope == scope,
                    UploadOperationRecord.idempotency_key == idempotency_key,
                    UploadOperationRecord.state == UploadOperationState.FAILED.value,
                ).values(state=UploadOperationState.PENDING.value, updated_at=now)).rowcount
                if changed:
                    record.state = UploadOperationState.PENDING.value
                    record.updated_at = now
                    return UploadOperationClaim(operation=self._domain(record), claimed=True)
            return UploadOperationClaim(operation=self._domain(record), claimed=False)

    def get(self, *, scope: str, idempotency_key: str) -> UploadOperation:
        with self._sessions() as session:
            record = session.scalar(select(UploadOperationRecord).where(
                UploadOperationRecord.scope == scope,
                UploadOperationRecord.idempotency_key == idempotency_key,
            ))
        if record is None:
            raise LookupError((scope, idempotency_key))
        return self._domain(record)

    def mark_succeeded(self, *, scope: str, idempotency_key: str) -> None:
        self._mark(scope, idempotency_key, UploadOperationState.SUCCEEDED)

    def mark_failed(self, *, scope: str, idempotency_key: str) -> None:
        self._mark(scope, idempotency_key, UploadOperationState.FAILED)

    def _mark(self, scope: str, key: str, state: UploadOperationState) -> None:
        with self._sessions.begin() as session:
            session.execute(update(UploadOperationRecord).where(
                UploadOperationRecord.scope == scope,
                UploadOperationRecord.idempotency_key == key,
                UploadOperationRecord.state == UploadOperationState.PENDING.value,
            ).values(state=state.value, updated_at=datetime.now(UTC)))

    @staticmethod
    def _domain(record: Any) -> UploadOperation:
        return UploadOperation(scope=record.scope, idempotency_key=record.idempotency_key,
            fingerprint=record.fingerprint, document_id=record.document_id,
            state=UploadOperationState(record.state), created_at=record.created_at,
            updated_at=record.updated_at)
