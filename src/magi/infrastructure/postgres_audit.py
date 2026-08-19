"""PostgreSQL adapter for append-only, hash-chained decision audit records."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import ValidationError
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from magi.audit import AuditChainViolation, AuditRecord
from magi.audit.ledger import ZERO_HASH, build_audit_record
from magi.domain import DataClassification


AUDIT_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS magi_decision_audit (
        decision_id UUID NOT NULL,
        decision_version INTEGER NOT NULL CHECK (decision_version >= 1),
        sequence INTEGER NOT NULL CHECK (sequence >= 1),
        record_id UUID NOT NULL UNIQUE,
        kind TEXT NOT NULL CHECK (kind IN ('decision_state', 'redaction')),
        classification TEXT NOT NULL CHECK (classification IN (
            'public', 'internal', 'sensitive', 'restricted'
        )),
        payload JSONB NOT NULL,
        payload_hash CHAR(64) NOT NULL,
        previous_hash CHAR(64) NOT NULL,
        record_hash CHAR(64) NOT NULL UNIQUE,
        occurred_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (decision_id, decision_version, sequence),
        UNIQUE (decision_id, decision_version, kind, payload_hash)
    )
    """,
    """
    CREATE OR REPLACE FUNCTION magi_reject_audit_mutation()
    RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION 'magi decision audit records are append-only';
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_trigger
            WHERE tgname = 'magi_decision_audit_append_only'
              AND tgrelid = 'magi_decision_audit'::regclass
        ) THEN
            CREATE TRIGGER magi_decision_audit_append_only
            BEFORE UPDATE OR DELETE ON magi_decision_audit
            FOR EACH ROW EXECUTE FUNCTION magi_reject_audit_mutation();
        END IF;
    END;
    $$
    """,
    """
    CREATE INDEX IF NOT EXISTS magi_decision_audit_time_idx
    ON magi_decision_audit (decision_id, decision_version, occurred_at)
    """,
)


class PostgresAuditLedger:
    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    async def setup(self) -> None:
        async with self._pool.connection() as connection:
            async with connection.transaction():
                for statement in AUDIT_SCHEMA:
                    await connection.execute(statement)

    async def append(
        self,
        *,
        decision_id: UUID,
        decision_version: int,
        kind: Literal["decision_state", "redaction"],
        classification: DataClassification,
        payload: Mapping[str, Any],
        occurred_at: datetime,
    ) -> AuditRecord:
        identity = build_audit_record(
            decision_id=decision_id,
            decision_version=decision_version,
            sequence=1,
            kind=kind,
            classification=classification,
            payload=payload,
            previous_hash=ZERO_HASH,
            occurred_at=occurred_at,
        )
        async with self._pool.connection() as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT pg_advisory_xact_lock(%s)",
                    (_audit_lock_id(decision_id, decision_version),),
                )
                existing_cursor = await connection.execute(
                    "SELECT * FROM magi_decision_audit WHERE record_id = %s",
                    (identity.record_id,),
                )
                existing = await existing_cursor.fetchone()
                if existing is not None:
                    stored = _audit_record(existing)
                    if (
                        stored.decision_id != decision_id
                        or stored.decision_version != decision_version
                        or stored.kind != kind
                        or stored.classification is not classification
                        or stored.payload_hash != identity.payload_hash
                    ):
                        raise AuditChainViolation(
                            "persisted audit idempotency identity is invalid"
                        )
                    return stored
                last_cursor = await connection.execute(
                    """
                    SELECT sequence, record_hash FROM magi_decision_audit
                    WHERE decision_id = %s AND decision_version = %s
                    ORDER BY sequence DESC LIMIT 1
                    """,
                    (decision_id, decision_version),
                )
                last = await last_cursor.fetchone()
                record = build_audit_record(
                    decision_id=decision_id,
                    decision_version=decision_version,
                    sequence=1 if last is None else int(last["sequence"]) + 1,
                    kind=kind,
                    classification=classification,
                    payload=payload,
                    previous_hash=ZERO_HASH if last is None else last["record_hash"],
                    occurred_at=occurred_at,
                )
                await connection.execute(
                    """
                    INSERT INTO magi_decision_audit (
                        decision_id, decision_version, sequence, record_id, kind,
                        classification, payload, payload_hash, previous_hash,
                        record_hash, occurred_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        record.decision_id,
                        record.decision_version,
                        record.sequence,
                        record.record_id,
                        record.kind,
                        record.classification.value,
                        Jsonb(record.payload),
                        record.payload_hash,
                        record.previous_hash,
                        record.record_hash,
                        record.occurred_at,
                    ),
                )
                return record

    async def records(
        self, decision_id: UUID, decision_version: int
    ) -> tuple[AuditRecord, ...]:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT * FROM magi_decision_audit
                WHERE decision_id = %s AND decision_version = %s
                ORDER BY sequence ASC
                """,
                (decision_id, decision_version),
            )
            rows = await cursor.fetchall()
        return tuple(_audit_record(row) for row in rows)


def _audit_lock_id(decision_id: UUID, decision_version: int) -> int:
    material = f"magi-audit-v1:{decision_id}:{decision_version}".encode("ascii")
    prefix = hashlib.sha256(material).digest()[:8]
    return int.from_bytes(prefix, byteorder="big", signed=True)


def _audit_record(row: Mapping[str, Any]) -> AuditRecord:
    try:
        return AuditRecord(
            record_id=row["record_id"],
            decision_id=row["decision_id"],
            decision_version=row["decision_version"],
            sequence=row["sequence"],
            kind=row["kind"],
            classification=row["classification"],
            payload=dict(row["payload"]),
            payload_hash=row["payload_hash"],
            previous_hash=row["previous_hash"],
            record_hash=row["record_hash"],
            occurred_at=row["occurred_at"],
        )
    except (KeyError, ValidationError, ValueError) as exc:
        raise AuditChainViolation("persisted audit record is invalid") from exc
