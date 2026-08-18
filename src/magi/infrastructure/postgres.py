"""PostgreSQL persistence for model invocations and LangGraph checkpoints."""

from __future__ import annotations

import os
from collections.abc import Mapping
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any, AsyncIterator

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from magi.agents.invocation import (
    InvocationLedger,
    InvocationStatus,
    ModelInvocationRecord,
)


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

    async def __aenter__(self) -> PostgresPersistenceRuntime:
        await self.open()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()


def decision_thread_id(decision_id: object, version: int) -> str:
    if version < 1:
        raise ValueError("decision version must be positive")
    thread_id = f"{decision_id}:{version}"
    if len(thread_id) > 255:
        raise ValueError("decision thread ID exceeds PostgreSQL checkpointer limit")
    return thread_id


def _advisory_lock_id(idempotency_key: str) -> int:
    if len(idempotency_key) != 64:
        raise ValueError("idempotency key must be a 64-character SHA-256 digest")
    try:
        digest_prefix = bytes.fromhex(idempotency_key[:16])
    except ValueError as exc:
        raise ValueError("idempotency key must be hexadecimal") from exc
    return int.from_bytes(digest_prefix, byteorder="big", signed=True)


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
