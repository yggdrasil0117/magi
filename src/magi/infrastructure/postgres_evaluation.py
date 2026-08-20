"""PostgreSQL append-only storage for deterministic decision evaluations."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from magi.domain import ProtocolViolation
from magi.evaluation import (
    DecisionEvaluation,
    EvaluationHistory,
    EvaluationRecord,
    EvaluationStore,
    build_evaluation_history,
    build_evaluation_record,
    evaluation_digest,
    evaluation_id,
)


EVALUATION_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS magi_decision_evaluations (
        decision_id UUID NOT NULL,
        decision_version INTEGER NOT NULL CHECK (decision_version >= 1),
        sequence INTEGER NOT NULL CHECK (sequence >= 1),
        evaluation_id UUID NOT NULL UNIQUE,
        evaluation_digest CHAR(64) NOT NULL,
        evaluation JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (decision_id, decision_version, sequence),
        UNIQUE (decision_id, decision_version, evaluation_digest)
    )
    """,
    """
    CREATE OR REPLACE FUNCTION magi_reject_evaluation_mutation()
    RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION 'magi decision evaluation records are append-only';
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_trigger
            WHERE tgname = 'magi_decision_evaluations_append_only'
              AND tgrelid = 'magi_decision_evaluations'::regclass
        ) THEN
            CREATE TRIGGER magi_decision_evaluations_append_only
            BEFORE UPDATE OR DELETE ON magi_decision_evaluations
            FOR EACH ROW EXECUTE FUNCTION magi_reject_evaluation_mutation();
        END IF;
    END;
    $$
    """,
    """
    CREATE INDEX IF NOT EXISTS magi_decision_evaluations_time_idx
    ON magi_decision_evaluations (decision_id, decision_version, created_at)
    """,
)


class PostgresEvaluationStore(EvaluationStore):
    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    async def setup(self) -> None:
        async with self._pool.connection() as connection:
            async with connection.transaction():
                for statement in EVALUATION_SCHEMA:
                    await connection.execute(statement)

    async def append(
        self, evaluation: DecisionEvaluation, *, created_at: datetime
    ) -> EvaluationRecord:
        digest = evaluation_digest(evaluation)
        identity = evaluation_id(evaluation.decision_id, evaluation.version, digest)
        async with self._pool.connection() as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT pg_advisory_xact_lock(%s)",
                    (_evaluation_lock_id(evaluation.decision_id, evaluation.version),),
                )
                existing_cursor = await connection.execute(
                    """
                    SELECT * FROM magi_decision_evaluations
                    WHERE evaluation_id = %s
                    """,
                    (identity,),
                )
                existing = await existing_cursor.fetchone()
                if existing is not None:
                    record = _evaluation_record(existing)
                    if record.evaluation != evaluation:
                        raise ProtocolViolation(
                            "persisted evaluation idempotency identity is invalid"
                        )
                    return record
                last_cursor = await connection.execute(
                    """
                    SELECT sequence FROM magi_decision_evaluations
                    WHERE decision_id = %s AND decision_version = %s
                    ORDER BY sequence DESC LIMIT 1
                    """,
                    (evaluation.decision_id, evaluation.version),
                )
                last = await last_cursor.fetchone()
                record = build_evaluation_record(
                    evaluation,
                    sequence=1 if last is None else int(last["sequence"]) + 1,
                    created_at=created_at,
                )
                await connection.execute(
                    """
                    INSERT INTO magi_decision_evaluations (
                        decision_id, decision_version, sequence,
                        evaluation_id, evaluation_digest, evaluation, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        record.decision_id,
                        record.decision_version,
                        record.sequence,
                        record.evaluation_id,
                        record.evaluation_digest,
                        Jsonb(record.evaluation.model_dump(mode="json")),
                        record.created_at,
                    ),
                )
                return record

    async def history(
        self, decision_id: UUID, decision_version: int, *, limit: int
    ) -> EvaluationHistory:
        if not 1 <= limit <= 100:
            raise ValueError("evaluation history limit must be between 1 and 100")
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT *, COUNT(*) OVER() AS total_count
                FROM magi_decision_evaluations
                WHERE decision_id = %s AND decision_version = %s
                ORDER BY sequence DESC LIMIT %s
                """,
                (decision_id, decision_version, limit),
            )
            rows = await cursor.fetchall()
        total_count = 0 if not rows else int(rows[0]["total_count"])
        records = tuple(reversed(tuple(_evaluation_record(row) for row in rows)))
        return build_evaluation_history(
            decision_id,
            decision_version,
            total_count=total_count,
            records=records,
        )


def _evaluation_record(row: Mapping[str, Any]) -> EvaluationRecord:
    try:
        return EvaluationRecord(
            evaluation_id=row["evaluation_id"],
            decision_id=row["decision_id"],
            decision_version=row["decision_version"],
            sequence=row["sequence"],
            evaluation_digest=row["evaluation_digest"],
            evaluation=DecisionEvaluation.model_validate(row["evaluation"]),
            created_at=row["created_at"],
        )
    except (KeyError, ValidationError, ValueError) as exc:
        raise ProtocolViolation("persisted evaluation record is invalid") from exc


def _evaluation_lock_id(decision_id: UUID, decision_version: int) -> int:
    material = f"magi-evaluation-v1:{decision_id}:{decision_version}".encode("ascii")
    prefix = hashlib.sha256(material).digest()[:8]
    return int.from_bytes(prefix, byteorder="big", signed=True)
