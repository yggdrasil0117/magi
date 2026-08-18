"""PostgreSQL persistence for model invocations and LangGraph checkpoints."""

from __future__ import annotations

import asyncio
import hashlib
import os
from collections.abc import Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime
from typing import Any, AsyncIterator
from uuid import UUID, uuid5

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from pydantic import ValidationError
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from magi.agents.invocation import (
    InvocationLedger,
    InvocationStatus,
    ModelInvocationRecord,
)
from magi.application import (
    CommandIdempotencyConflict,
    CommandIdempotencyStore,
    DecisionView,
    OperationEvent,
    OperationEventPage,
    OperationEventType,
    OperationIdempotencyConflict,
    OperationKind,
    OperationReceipt,
    OperationStage,
    OperationStatus,
    OperationStore,
)
from magi.domain import DataClassification, ProtocolViolation
from magi.orchestration import decision_thread_id


INVOCATION_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS magi_model_invocations (
        invocation_id UUID PRIMARY KEY,
        idempotency_key CHAR(64) NOT NULL,
        prompt_digest CHAR(64) NOT NULL,
        decision_id UUID NOT NULL,
        decision_version INTEGER NOT NULL CHECK (decision_version >= 1),
        agent TEXT NOT NULL CHECK (agent IN ('melchior', 'balthasar', 'casper')),
        round SMALLINT NOT NULL CHECK (round IN (1, 2)),
        attempt SMALLINT NOT NULL CHECK (attempt >= 0),
        status TEXT NOT NULL CHECK (status IN ('succeeded', 'failed', 'reused')),
        model_name TEXT NOT NULL,
        started_at TIMESTAMPTZ NOT NULL,
        completed_at TIMESTAMPTZ NOT NULL,
        latency_ms INTEGER NOT NULL CHECK (latency_ms >= 0),
        input_tokens INTEGER NOT NULL CHECK (input_tokens >= 0),
        output_tokens INTEGER NOT NULL CHECK (output_tokens >= 0),
        total_tokens INTEGER NOT NULL CHECK (total_tokens >= 0),
        error_type TEXT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS magi_model_ballots (
        idempotency_key CHAR(64) PRIMARY KEY,
        invocation_id UUID NOT NULL UNIQUE
            REFERENCES magi_model_invocations(invocation_id),
        ballot JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS magi_model_invocations_decision_idx
    ON magi_model_invocations (decision_id, decision_version, agent, round)
    """,
    """
    CREATE INDEX IF NOT EXISTS magi_model_invocations_idempotency_idx
    ON magi_model_invocations (idempotency_key, started_at)
    """,
)

COMMAND_IDEMPOTENCY_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS magi_api_command_results (
        storage_key CHAR(64) PRIMARY KEY,
        principal_digest CHAR(64) NOT NULL,
        idempotency_key_digest CHAR(64) NOT NULL,
        fingerprint CHAR(64) NOT NULL,
        response JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (principal_digest, idempotency_key_digest)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS magi_api_command_results_created_idx
    ON magi_api_command_results (created_at)
    """,
)

OPERATION_NAMESPACE = UUID("d6a00b77-4dd3-4a2e-bab8-f155432f58d1")
OPERATION_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS magi_operations (
        operation_id UUID PRIMARY KEY,
        storage_key CHAR(64) NOT NULL UNIQUE,
        principal_digest CHAR(64) NOT NULL,
        idempotency_key_digest CHAR(64) NOT NULL,
        fingerprint CHAR(64) NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('create_decision', 'run_decision')),
        decision_id UUID NOT NULL,
        decision_version INTEGER NOT NULL CHECK (decision_version >= 1),
        classification TEXT NOT NULL
            CHECK (classification IN ('public', 'internal', 'sensitive', 'restricted')),
        request_payload JSONB NOT NULL,
        status TEXT NOT NULL
            CHECK (status IN ('accepted', 'running', 'succeeded', 'failed')),
        stage TEXT NOT NULL CHECK (stage IN (
            'queued', 'coordinator', 'first_ballot', 'cross_review',
            'arbitration', 'reporting', 'complete'
        )),
        fencing_token INTEGER NOT NULL DEFAULT 0 CHECK (fencing_token >= 0),
        lease_owner_digest CHAR(64) NULL,
        lease_expires_at TIMESTAMPTZ NULL,
        result JSONB NULL,
        failure_code TEXT NULL,
        last_event_sequence INTEGER NOT NULL DEFAULT 1
            CHECK (last_event_sequence >= 1),
        created_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL,
        completed_at TIMESTAMPTZ NULL,
        retention_until TIMESTAMPTZ NULL,
        UNIQUE (principal_digest, idempotency_key_digest)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS magi_operation_events (
        operation_id UUID NOT NULL REFERENCES magi_operations(operation_id),
        sequence INTEGER NOT NULL CHECK (sequence >= 1),
        event_type TEXT NOT NULL CHECK (event_type IN (
            'accepted', 'started', 'stage_changed', 'succeeded', 'failed'
        )),
        status TEXT NOT NULL
            CHECK (status IN ('accepted', 'running', 'succeeded', 'failed')),
        stage TEXT NOT NULL CHECK (stage IN (
            'queued', 'coordinator', 'first_ballot', 'cross_review',
            'arbitration', 'reporting', 'complete'
        )),
        message_code TEXT NOT NULL,
        occurred_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (operation_id, sequence)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS magi_operations_claim_idx
    ON magi_operations (status, lease_expires_at, created_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS magi_operations_decision_idx
    ON magi_operations (decision_id, decision_version, created_at)
    """,
)


class PostgresInvocationLedger(InvocationLedger):
    """Append-only invocation ledger with a cross-process advisory guard."""

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool
        self._guard_connection: ContextVar[Any | None] = ContextVar(
            f"magi_invocation_guard_{id(self)}",
            default=None,
        )

    async def setup(self) -> None:
        async with self._connection() as connection:
            async with connection.transaction():
                for statement in INVOCATION_SCHEMA:
                    await connection.execute(statement)

    @asynccontextmanager
    async def guard(self, idempotency_key: str) -> AsyncIterator[None]:
        lock_id = _advisory_lock_id(idempotency_key)
        async with self._pool.connection() as connection:
            await connection.execute("SELECT pg_advisory_lock(%s)", (lock_id,))
            token = self._guard_connection.set(connection)
            try:
                yield
            finally:
                try:
                    await connection.execute("SELECT pg_advisory_unlock(%s)", (lock_id,))
                finally:
                    self._guard_connection.reset(token)

    async def get_ballot(self, idempotency_key: str) -> Mapping[str, Any] | None:
        async with self._connection() as connection:
            cursor = await connection.execute(
                "SELECT ballot FROM magi_model_ballots WHERE idempotency_key = %s",
                (idempotency_key,),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row["ballot"])

    async def append(
        self,
        record: ModelInvocationRecord,
        ballot: Mapping[str, Any] | None = None,
    ) -> None:
        if ballot is not None and record.status is not InvocationStatus.SUCCEEDED:
            raise ValueError("only successful invocations may store a ballot")
        async with self._connection() as connection:
            async with connection.transaction():
                await connection.execute(
                    """
                    INSERT INTO magi_model_invocations (
                        invocation_id, idempotency_key, prompt_digest,
                        decision_id, decision_version, agent, round, attempt,
                        status, model_name, started_at, completed_at, latency_ms,
                        input_tokens, output_tokens, total_tokens, error_type
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    _record_parameters(record),
                )
                if ballot is not None:
                    await connection.execute(
                        """
                        INSERT INTO magi_model_ballots (
                            idempotency_key, invocation_id, ballot
                        ) VALUES (%s, %s, %s)
                        ON CONFLICT (idempotency_key) DO NOTHING
                        """,
                        (
                            record.idempotency_key,
                            record.invocation_id,
                            Jsonb(dict(ballot)),
                        ),
                    )

    @asynccontextmanager
    async def _connection(self) -> AsyncIterator[Any]:
        guarded = self._guard_connection.get()
        if guarded is not None:
            yield guarded
            return
        async with self._pool.connection() as connection:
            yield connection


class PostgresCommandIdempotencyStore(CommandIdempotencyStore):
    """Durable principal-scoped command results with a cross-process guard."""

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    async def setup(self) -> None:
        async with self._pool.connection() as connection:
            async with connection.transaction():
                for statement in COMMAND_IDEMPOTENCY_SCHEMA:
                    await connection.execute(statement)

    async def execute(
        self,
        *,
        principal: str,
        idempotency_key: str,
        fingerprint: str,
        operation: Callable[[], Awaitable[DecisionView]],
    ) -> DecisionView:
        storage_key, principal_digest, key_digest = _command_storage_keys(
            principal,
            idempotency_key,
        )
        if len(fingerprint) != 64:
            raise ValueError("command fingerprint must be a 64-character digest")
        try:
            bytes.fromhex(fingerprint)
        except ValueError as exc:
            raise ValueError("command fingerprint must be hexadecimal") from exc

        lock_id = _advisory_lock_id(storage_key)
        async with self._pool.connection() as connection:
            await connection.execute("SELECT pg_advisory_lock(%s)", (lock_id,))
            try:
                cursor = await connection.execute(
                    """
                    SELECT fingerprint, response
                    FROM magi_api_command_results
                    WHERE storage_key = %s
                    """,
                    (storage_key,),
                )
                row = await cursor.fetchone()
                if row is not None:
                    if row["fingerprint"] != fingerprint:
                        raise CommandIdempotencyConflict(
                            "idempotency key was already used for another command"
                        )
                    try:
                        return DecisionView.model_validate(row["response"])
                    except ValidationError as exc:
                        raise ProtocolViolation(
                            "persisted API command response is invalid"
                        ) from exc

                operation_cursor = await connection.execute(
                    "SELECT 1 FROM magi_operations WHERE storage_key = %s",
                    (storage_key,),
                )
                if await operation_cursor.fetchone() is not None:
                    raise CommandIdempotencyConflict(
                        "idempotency key was already used for an async operation"
                    )

                view = await operation()
                async with connection.transaction():
                    await connection.execute(
                        """
                        INSERT INTO magi_api_command_results (
                            storage_key, principal_digest,
                            idempotency_key_digest, fingerprint, response
                        ) VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            storage_key,
                            principal_digest,
                            key_digest,
                            fingerprint,
                            Jsonb(view.model_dump(mode="json")),
                        ),
                    )
                return view
            finally:
                await connection.execute(
                    "SELECT pg_advisory_unlock(%s)",
                    (lock_id,),
                )


class PostgresOperationStore(OperationStore):
    """Durable async operation receipts and append-only public events."""

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    async def setup(self) -> None:
        async with self._pool.connection() as connection:
            async with connection.transaction():
                for statement in OPERATION_SCHEMA:
                    await connection.execute(statement)

    async def accept(
        self,
        *,
        principal: str,
        idempotency_key: str,
        fingerprint: str,
        kind: OperationKind,
        decision_id: UUID,
        decision_version: int,
        classification: DataClassification,
        request_payload: Mapping[str, Any],
        accepted_at: datetime,
    ) -> OperationReceipt:
        storage_key, principal_digest, key_digest = _command_storage_keys(
            principal,
            idempotency_key,
        )
        _validate_digest(fingerprint, "operation fingerprint")
        if decision_version < 1:
            raise ValueError("operation decision version must be positive")
        if accepted_at.tzinfo is None:
            raise ValueError("operation acceptance time must be timezone-aware")
        operation_id = uuid5(OPERATION_NAMESPACE, storage_key)
        lock_id = _advisory_lock_id(storage_key)
        async with self._pool.connection() as connection:
            await connection.execute("SELECT pg_advisory_lock(%s)", (lock_id,))
            try:
                cursor = await connection.execute(
                    """
                    SELECT * FROM magi_operations
                    WHERE storage_key = %s
                    """,
                    (storage_key,),
                )
                existing = await cursor.fetchone()
                if existing is not None:
                    if existing["fingerprint"] != fingerprint:
                        raise OperationIdempotencyConflict(
                            "idempotency key was already used for another operation"
                        )
                    return _operation_receipt(existing)

                sync_cursor = await connection.execute(
                    "SELECT 1 FROM magi_api_command_results WHERE storage_key = %s",
                    (storage_key,),
                )
                if await sync_cursor.fetchone() is not None:
                    raise OperationIdempotencyConflict(
                        "idempotency key was already used for a synchronous command"
                    )

                async with connection.transaction():
                    await connection.execute(
                        """
                        INSERT INTO magi_operations (
                            operation_id, storage_key, principal_digest,
                            idempotency_key_digest, fingerprint, kind,
                            decision_id, decision_version, classification,
                            request_payload, status, stage,
                            last_event_sequence, created_at, updated_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            'accepted', 'queued', 1, %s, %s
                        )
                        """,
                        (
                            operation_id,
                            storage_key,
                            principal_digest,
                            key_digest,
                            fingerprint,
                            kind.value,
                            decision_id,
                            decision_version,
                            classification.value,
                            Jsonb(dict(request_payload)),
                            accepted_at,
                            accepted_at,
                        ),
                    )
                    await connection.execute(
                        """
                        INSERT INTO magi_operation_events (
                            operation_id, sequence, event_type, status,
                            stage, message_code, occurred_at
                        ) VALUES (%s, 1, 'accepted', 'accepted', 'queued',
                                  'operation_accepted', %s)
                        """,
                        (operation_id, accepted_at),
                    )
                return OperationReceipt(
                    operation_id=operation_id,
                    kind=kind,
                    status=OperationStatus.ACCEPTED,
                    stage=OperationStage.QUEUED,
                    decision_id=decision_id,
                    decision_version=decision_version,
                    created_at=accepted_at,
                    updated_at=accepted_at,
                    last_event_sequence=1,
                    next_poll_after_ms=1000,
                )
            finally:
                await connection.execute(
                    "SELECT pg_advisory_unlock(%s)",
                    (lock_id,),
                )

    async def get(
        self,
        *,
        principal: str,
        operation_id: UUID,
    ) -> OperationReceipt | None:
        principal_digest = _principal_digest(principal)
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT * FROM magi_operations
                WHERE operation_id = %s AND principal_digest = %s
                """,
                (operation_id, principal_digest),
            )
            row = await cursor.fetchone()
        return None if row is None else _operation_receipt(row)

    async def events(
        self,
        *,
        principal: str,
        operation_id: UUID,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> OperationEventPage | None:
        if after_sequence < 0:
            raise ValueError("operation event cursor cannot be negative")
        if limit < 1 or limit > 100:
            raise ValueError("operation event limit must be between 1 and 100")
        principal_digest = _principal_digest(principal)
        async with self._pool.connection() as connection:
            owner_cursor = await connection.execute(
                """
                SELECT 1 FROM magi_operations
                WHERE operation_id = %s AND principal_digest = %s
                """,
                (operation_id, principal_digest),
            )
            if await owner_cursor.fetchone() is None:
                return None
            cursor = await connection.execute(
                """
                SELECT operation_id, sequence, event_type, status,
                       stage, message_code, occurred_at
                FROM magi_operation_events
                WHERE operation_id = %s AND sequence > %s
                ORDER BY sequence ASC
                LIMIT %s
                """,
                (operation_id, after_sequence, limit + 1),
            )
            rows = await cursor.fetchall()
        has_more = len(rows) > limit
        selected = rows[:limit]
        try:
            events = tuple(OperationEvent.model_validate(row) for row in selected)
            next_after = events[-1].sequence if events else after_sequence
            return OperationEventPage(
                operation_id=operation_id,
                after_sequence=after_sequence,
                events=events,
                next_after_sequence=next_after,
                has_more=has_more,
            )
        except ValidationError as exc:
            raise ProtocolViolation("persisted operation event is invalid") from exc


class PostgresPersistenceRuntime:
    """Own one pool shared by the MAGI ledger and LangGraph checkpointer."""

    def __init__(
        self,
        conninfo: str,
        *,
        min_size: int = 1,
        max_size: int = 10,
    ) -> None:
        if not conninfo.strip():
            raise ValueError("PostgreSQL connection string is required")
        if min_size < 0 or max_size < 2 or min_size > max_size:
            raise ValueError(
                "PostgreSQL pool requires 0 <= min_size <= max_size and max_size >= 2"
            )
        self.pool = AsyncConnectionPool(
            conninfo,
            kwargs={
                "autocommit": True,
                "prepare_threshold": 0,
                "row_factory": dict_row,
            },
            min_size=min_size,
            max_size=max_size,
            open=False,
            name="magi-postgres",
        )
        self.invocation_ledger = PostgresInvocationLedger(self.pool)
        self.command_idempotency_store = PostgresCommandIdempotencyStore(self.pool)
        self.operation_store = PostgresOperationStore(self.pool)
        self._checkpointer: AsyncPostgresSaver | None = None
        self._opened = False

    @classmethod
    def from_environment(cls) -> PostgresPersistenceRuntime:
        conninfo = os.getenv("MAGI_DATABASE_URL", "")
        if not conninfo:
            raise ValueError("MAGI_DATABASE_URL is not configured")
        return cls(conninfo)

    @property
    def checkpointer(self) -> AsyncPostgresSaver:
        if self._checkpointer is None:
            raise RuntimeError("PostgreSQL persistence runtime is not open")
        return self._checkpointer

    async def open(self, *, setup: bool = True) -> None:
        if self._opened:
            return
        await self.pool.open(wait=True)
        serializer = JsonPlusSerializer(allowed_msgpack_modules=None)
        self._checkpointer = AsyncPostgresSaver(self.pool, serde=serializer)
        try:
            if setup:
                await self.invocation_ledger.setup()
                await self.command_idempotency_store.setup()
                await self.operation_store.setup()
                await self._checkpointer.setup()
        except Exception:
            self._checkpointer = None
            await self.pool.close()
            raise
        self._opened = True

    async def close(self) -> None:
        if not self._opened:
            return
        self._checkpointer = None
        self._opened = False
        await self.pool.close()

    async def is_ready(self, *, timeout_seconds: float = 2.0) -> bool:
        """Return whether the opened pool can execute a bounded probe query."""

        if not self._opened or timeout_seconds <= 0:
            return False
        try:
            async with asyncio.timeout(timeout_seconds):
                async with self.pool.connection() as connection:
                    await connection.execute("SELECT 1")
        except Exception:
            return False
        return True

    async def __aenter__(self) -> PostgresPersistenceRuntime:
        await self.open()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()


def _advisory_lock_id(idempotency_key: str) -> int:
    if len(idempotency_key) != 64:
        raise ValueError("idempotency key must be a 64-character SHA-256 digest")
    try:
        digest_prefix = bytes.fromhex(idempotency_key[:16])
    except ValueError as exc:
        raise ValueError("idempotency key must be hexadecimal") from exc
    return int.from_bytes(digest_prefix, byteorder="big", signed=True)


def _command_storage_keys(
    principal: str,
    idempotency_key: str,
) -> tuple[str, str, str]:
    if not principal:
        raise ValueError("command principal is required")
    if not idempotency_key:
        raise ValueError("command idempotency key is required")
    principal_digest = hashlib.sha256(principal.encode("utf-8")).hexdigest()
    key_digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    material = f"magi-api-v1:{principal_digest}:{key_digest}".encode("ascii")
    storage_key = hashlib.sha256(material).hexdigest()
    return storage_key, principal_digest, key_digest


def _principal_digest(principal: str) -> str:
    if not principal:
        raise ValueError("operation principal is required")
    return hashlib.sha256(principal.encode("utf-8")).hexdigest()


def _validate_digest(value: str, label: str) -> None:
    if len(value) != 64:
        raise ValueError(f"{label} must be a 64-character digest")
    try:
        bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be hexadecimal") from exc


def _operation_receipt(row: Mapping[str, Any]) -> OperationReceipt:
    terminal = row["status"] in {
        OperationStatus.SUCCEEDED.value,
        OperationStatus.FAILED.value,
    }
    try:
        if row["status"] == OperationStatus.SUCCEEDED.value:
            DecisionView.model_validate(row.get("result"))
        elif row.get("result") is not None:
            raise ProtocolViolation(
                "non-successful persisted operation contains a result"
            )
        return OperationReceipt(
            operation_id=row["operation_id"],
            kind=row["kind"],
            status=row["status"],
            stage=row["stage"],
            decision_id=row["decision_id"],
            decision_version=row["decision_version"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            completed_at=row.get("completed_at"),
            last_event_sequence=row["last_event_sequence"],
            next_poll_after_ms=None if terminal else 1000,
            result_available=row["status"] == OperationStatus.SUCCEEDED.value,
            failure_code=row.get("failure_code"),
        )
    except (KeyError, ValidationError) as exc:
        raise ProtocolViolation("persisted operation receipt is invalid") from exc


def _record_parameters(record: ModelInvocationRecord) -> tuple[object, ...]:
    return (
        record.invocation_id,
        record.idempotency_key,
        record.prompt_digest,
        record.decision_id,
        record.decision_version,
        record.agent.value,
        record.round,
        record.attempt,
        record.status.value,
        record.model_name,
        record.started_at,
        record.completed_at,
        record.latency_ms,
        record.usage.input_tokens,
        record.usage.output_tokens,
        record.usage.total_tokens,
        record.error_type,
    )
