"""PostgreSQL persistence for model invocations and LangGraph checkpoints."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any, AsyncIterator

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
)
from magi.domain import ProtocolViolation
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
