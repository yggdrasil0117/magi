"""PostgreSQL persistence for model invocations and LangGraph checkpoints."""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
from collections.abc import Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta
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
    ModelTokenUsage,
)
from magi.application import (
    DecisionCatalog,
    DecisionCatalogEntry,
    DecisionHistory,
    CommandIdempotencyConflict,
    CommandIdempotencyStore,
    DecisionView,
    OperationEvent,
    OperationEventPage,
    OperationEventType,
    OperationIdempotencyConflict,
    OperationInbox,
    OperationKind,
    OperationLease,
    OperationLeaseLost,
    OperationReceipt,
    OperationStage,
    OperationStatus,
    OperationStore,
)
from magi.domain import DataClassification, ProtocolViolation
from magi.orchestration import decision_thread_id

from .postgres_audit import PostgresAuditLedger
from .postgres_evaluation import PostgresEvaluationStore


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
    """
    CREATE TABLE IF NOT EXISTS magi_decision_catalog (
        principal_digest CHAR(64) NOT NULL,
        decision_id UUID NOT NULL,
        decision_version INTEGER NOT NULL CHECK (decision_version >= 1),
        view JSONB NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (principal_digest, decision_id, decision_version)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS magi_decision_catalog_recent_idx
    ON magi_decision_catalog (principal_digest, updated_at DESC)
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

    async def records_for(
        self, decision_id: UUID, decision_version: int
    ) -> tuple[ModelInvocationRecord, ...]:
        async with self._connection() as connection:
            cursor = await connection.execute(
                """
                SELECT * FROM magi_model_invocations
                WHERE decision_id = %s AND decision_version = %s
                ORDER BY started_at ASC, invocation_id ASC
                """,
                (decision_id, decision_version),
            )
            rows = await cursor.fetchall()
        return tuple(_invocation_record(row) for row in rows)

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
        self._lease_connection: ContextVar[Any | None] = ContextVar(
            f"magi_operation_lease_{id(self)}", default=None
        )

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

    async def inbox(
        self,
        *,
        principal: str,
        limit: int = 50,
    ) -> OperationInbox:
        if limit < 1 or limit > 100:
            raise ValueError("operation inbox limit must be between 1 and 100")
        principal_digest = _principal_digest(principal)
        async with self._pool.connection() as connection:
            count_cursor = await connection.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE status IN ('accepted', 'running')) AS active_count,
                    COUNT(*) FILTER (WHERE status = 'failed') AS failed_count
                FROM magi_operations WHERE principal_digest = %s
                """,
                (principal_digest,),
            )
            counts = await count_cursor.fetchone()
            cursor = await connection.execute(
                """
                SELECT * FROM magi_operations
                WHERE principal_digest = %s
                ORDER BY updated_at DESC, operation_id DESC
                LIMIT %s
                """,
                (principal_digest, limit),
            )
            rows = await cursor.fetchall()
        if counts is None:
            raise ProtocolViolation("persisted operation counts are invalid")
        return OperationInbox(
            operations=tuple(_operation_receipt(row) for row in rows),
            active_count=counts["active_count"],
            failed_count=counts["failed_count"],
        )

    async def decisions(self, *, principal: str, limit: int = 50) -> DecisionCatalog:
        if limit < 1 or limit > 100:
            raise ValueError("decision catalog limit must be between 1 and 100")
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT view, updated_at FROM (
                    SELECT DISTINCT ON (decision_id) decision_id, view, updated_at
                    FROM magi_decision_catalog WHERE principal_digest = %s
                    ORDER BY decision_id, decision_version DESC
                ) latest
                ORDER BY updated_at DESC, decision_id DESC LIMIT %s
                """,
                (_principal_digest(principal), limit),
            )
            rows = await cursor.fetchall()
        entries = tuple(_catalog_entry(row) for row in rows)
        entries = tuple(sorted(entries, key=lambda item: item.updated_at, reverse=True))
        return DecisionCatalog(
            decisions=entries,
            required_action_count=sum(bool(item.available_actions) for item in entries),
        )

    async def versions(
        self, *, principal: str, decision_id: UUID
    ) -> DecisionHistory | None:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT view FROM magi_decision_catalog
                WHERE principal_digest = %s AND decision_id = %s
                ORDER BY decision_version DESC
                """,
                (_principal_digest(principal), decision_id),
            )
            rows = await cursor.fetchall()
        if not rows:
            return None
        try:
            return DecisionHistory(
                decision_id=decision_id,
                versions=tuple(DecisionView.model_validate(row["view"]) for row in rows),
            )
        except ValidationError as exc:
            raise ProtocolViolation("persisted decision catalog is invalid") from exc

    async def record_decision(
        self, *, principal: str, view: DecisionView, updated_at: datetime
    ) -> None:
        if updated_at.tzinfo is None:
            raise ValueError("decision catalog update must be timezone-aware")
        async with self._pool.connection() as connection:
            await connection.execute(
                """
                INSERT INTO magi_decision_catalog (
                    principal_digest, decision_id, decision_version, view, updated_at
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (principal_digest, decision_id, decision_version)
                DO UPDATE SET view = EXCLUDED.view, updated_at = EXCLUDED.updated_at
                """,
                (_principal_digest(principal), view.decision_id, view.version,
                 Jsonb(view.model_dump(mode="json")), updated_at),
            )

    @asynccontextmanager
    async def claim(
        self, *, worker_id: str, claimed_at: datetime, lease_seconds: int
    ) -> AsyncIterator[OperationLease | None]:
        owner_digest = _worker_digest(worker_id)
        _validate_lease_time(claimed_at, lease_seconds)
        lock_id: int | None = None
        token: object | None = None
        async with self._pool.connection() as connection:
            try:
                async with connection.transaction():
                    cursor = await connection.execute(
                        """
                        SELECT * FROM magi_operations
                        WHERE status = 'accepted'
                           OR (status = 'running' AND lease_expires_at <= %s)
                        ORDER BY created_at ASC
                        FOR UPDATE SKIP LOCKED LIMIT 1
                        """,
                        (claimed_at,),
                    )
                    row = await cursor.fetchone()
                    lease = None
                    if row is not None:
                        lock_id = _advisory_lock_id(row["storage_key"])
                        lock_cursor = await connection.execute(
                            "SELECT pg_try_advisory_lock(%s) AS acquired", (lock_id,)
                        )
                        lock_row = await lock_cursor.fetchone()
                        if lock_row is None or not lock_row["acquired"]:
                            lock_id = None
                        else:
                            fencing_token = int(row["fencing_token"]) + 1
                            stage = (
                                OperationStage.COORDINATOR
                                if row["kind"] == OperationKind.CREATE_DECISION.value
                                else OperationStage.FIRST_BALLOT
                            )
                            sequence = int(row["last_event_sequence"]) + 1
                            expires_at = claimed_at + timedelta(seconds=lease_seconds)
                            await connection.execute(
                                """
                                UPDATE magi_operations
                                SET status = 'running', stage = %s,
                                    fencing_token = %s, lease_owner_digest = %s,
                                    lease_expires_at = %s,
                                    last_event_sequence = %s, updated_at = %s
                                WHERE operation_id = %s
                                """,
                                (stage.value, fencing_token, owner_digest, expires_at,
                                 sequence, claimed_at, row["operation_id"]),
                            )
                            await connection.execute(
                                """
                                INSERT INTO magi_operation_events (
                                    operation_id, sequence, event_type, status,
                                    stage, message_code, occurred_at
                                ) VALUES (%s, %s, 'started', 'running', %s, %s, %s)
                                """,
                                (row["operation_id"], sequence, stage.value,
                                 "operation_started" if row["status"] == "accepted"
                                 else "operation_resumed", claimed_at),
                            )
                            lease = OperationLease(
                                operation_id=row["operation_id"], kind=row["kind"],
                                decision_id=row["decision_id"],
                                decision_version=row["decision_version"],
                                classification=row["classification"],
                                request_payload=dict(row["request_payload"]),
                                fencing_token=fencing_token,
                                lease_expires_at=expires_at,
                            )
                if lease is not None:
                    token = self._lease_connection.set(connection)
                yield lease
            finally:
                if token is not None:
                    self._lease_connection.reset(token)
                if lock_id is not None:
                    await connection.execute("SELECT pg_advisory_unlock(%s)", (lock_id,))

    async def renew(
        self, lease: OperationLease, *, worker_id: str,
        renewed_at: datetime, lease_seconds: int
    ) -> OperationLease:
        _validate_lease_time(renewed_at, lease_seconds)
        expires_at = renewed_at + timedelta(seconds=lease_seconds)
        async with self._connection() as connection:
            cursor = await connection.execute(
                """
                UPDATE magi_operations SET lease_expires_at = %s, updated_at = %s
                WHERE operation_id = %s AND status = 'running'
                  AND fencing_token = %s AND lease_owner_digest = %s
                RETURNING operation_id
                """,
                (expires_at, renewed_at, lease.operation_id, lease.fencing_token,
                 _worker_digest(worker_id)),
            )
            if await cursor.fetchone() is None:
                raise OperationLeaseLost("operation lease is no longer current")
        return lease.model_copy(update={"lease_expires_at": expires_at})

    async def advance(
        self, lease: OperationLease, *, worker_id: str, stage: OperationStage,
        message_code: str, occurred_at: datetime
    ) -> OperationReceipt:
        return await self._transition(
            lease, worker_id=worker_id, status=OperationStatus.RUNNING,
            stage=stage, event_type=OperationEventType.STAGE_CHANGED,
            message_code=message_code, occurred_at=occurred_at,
        )

    async def succeed(
        self, lease: OperationLease, *, worker_id: str, result: DecisionView,
        completed_at: datetime
    ) -> OperationReceipt:
        validated = DecisionView.model_validate(result)
        if (validated.decision_id != lease.decision_id
                or validated.version != lease.decision_version):
            raise ValueError("operation result decision identity does not match")
        return await self._transition(
            lease, worker_id=worker_id, status=OperationStatus.SUCCEEDED,
            stage=OperationStage.COMPLETE, event_type=OperationEventType.SUCCEEDED,
            message_code="operation_succeeded", occurred_at=completed_at,
            result=validated,
        )

    async def fail(
        self, lease: OperationLease, *, worker_id: str, failure_code: str,
        completed_at: datetime
    ) -> OperationReceipt:
        if re.fullmatch(r"[a-z][a-z0-9_]{0,99}", failure_code) is None:
            raise ValueError("operation failure code is invalid")
        return await self._transition(
            lease, worker_id=worker_id, status=OperationStatus.FAILED,
            stage=OperationStage.COMPLETE, event_type=OperationEventType.FAILED,
            message_code="operation_failed", occurred_at=completed_at,
            failure_code=failure_code,
        )

    async def _transition(
        self, lease: OperationLease, *, worker_id: str, status: OperationStatus,
        stage: OperationStage, event_type: OperationEventType, message_code: str,
        occurred_at: datetime, result: DecisionView | None = None,
        failure_code: str | None = None,
    ) -> OperationReceipt:
        if occurred_at.tzinfo is None:
            raise ValueError("operation transition time must be timezone-aware")
        OperationEvent(
            operation_id=lease.operation_id, sequence=1, event_type=event_type,
            status=status, stage=stage, occurred_at=occurred_at,
            message_code=message_code,
        )
        completed_at = occurred_at if status is not OperationStatus.RUNNING else None
        async with self._connection() as connection:
            async with connection.transaction():
                cursor = await connection.execute(
                    """
                    UPDATE magi_operations
                    SET status = %s, stage = %s, result = %s, failure_code = %s,
                        completed_at = %s, updated_at = %s,
                        lease_owner_digest = CASE WHEN %s = 'running'
                            THEN lease_owner_digest ELSE NULL END,
                        lease_expires_at = CASE WHEN %s = 'running'
                            THEN lease_expires_at ELSE NULL END,
                        last_event_sequence = last_event_sequence + 1
                    WHERE operation_id = %s AND status = 'running'
                      AND fencing_token = %s AND lease_owner_digest = %s
                    RETURNING *
                    """,
                    (status.value, stage.value,
                     None if result is None else Jsonb(result.model_dump(mode="json")),
                     failure_code, completed_at, occurred_at, status.value, status.value,
                     lease.operation_id, lease.fencing_token, _worker_digest(worker_id)),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise OperationLeaseLost("operation lease is no longer current")
                await connection.execute(
                    """
                    INSERT INTO magi_operation_events (
                        operation_id, sequence, event_type, status,
                        stage, message_code, occurred_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (lease.operation_id, row["last_event_sequence"], event_type.value,
                     status.value, stage.value, message_code, occurred_at),
                )
                if status is OperationStatus.SUCCEEDED and result is not None:
                    await connection.execute(
                        """
                        INSERT INTO magi_decision_catalog (
                            principal_digest, decision_id, decision_version,
                            view, updated_at
                        ) SELECT principal_digest, decision_id, decision_version, %s, %s
                          FROM magi_operations WHERE operation_id = %s
                        ON CONFLICT (principal_digest, decision_id, decision_version)
                        DO UPDATE SET view = EXCLUDED.view, updated_at = EXCLUDED.updated_at
                        """,
                        (Jsonb(result.model_dump(mode="json")), occurred_at, lease.operation_id),
                    )
        return _operation_receipt(row)

    @asynccontextmanager
    async def _connection(self) -> AsyncIterator[Any]:
        leased = self._lease_connection.get()
        if leased is not None:
            yield leased
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
        self.audit_ledger = PostgresAuditLedger(self.pool)
        self.evaluation_store = PostgresEvaluationStore(self.pool)
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
                await self.audit_ledger.setup()
                await self.evaluation_store.setup()
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


def _worker_digest(worker_id: str) -> str:
    if not worker_id.strip():
        raise ValueError("operation worker id is required")
    return hashlib.sha256(worker_id.encode("utf-8")).hexdigest()


def _validate_lease_time(timestamp: datetime, lease_seconds: int) -> None:
    if timestamp.tzinfo is None:
        raise ValueError("operation lease time must be timezone-aware")
    if lease_seconds < 3 or lease_seconds > 3600:
        raise ValueError("operation lease must be between 3 and 3600 seconds")


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


def _catalog_entry(row: Mapping[str, Any]) -> DecisionCatalogEntry:
    try:
        view = DecisionView.model_validate(row["view"])
        return DecisionCatalogEntry(
            decision_id=view.decision_id,
            version=view.version,
            title=view.case.title,
            state=view.state.value,
            risk_level=view.case.risk_level.value,
            data_classification=view.case.data_classification,
            available_actions=view.available_actions,
            updated_at=row["updated_at"],
        )
    except (KeyError, ValidationError) as exc:
        raise ProtocolViolation("persisted decision catalog is invalid") from exc


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


def _invocation_record(row: Mapping[str, Any]) -> ModelInvocationRecord:
    try:
        return ModelInvocationRecord(
            invocation_id=row["invocation_id"],
            idempotency_key=row["idempotency_key"],
            prompt_digest=row["prompt_digest"],
            decision_id=row["decision_id"],
            decision_version=row["decision_version"],
            agent=row["agent"],
            round=row["round"],
            attempt=row["attempt"],
            status=row["status"],
            model_name=row["model_name"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            latency_ms=row["latency_ms"],
            usage=ModelTokenUsage(
                input_tokens=row["input_tokens"],
                output_tokens=row["output_tokens"],
                total_tokens=row["total_tokens"],
            ),
            error_type=row["error_type"],
        )
    except (KeyError, ValidationError, ValueError) as exc:
        raise ProtocolViolation("persisted invocation record is invalid") from exc
