"""Protocol-level PostgreSQL adapter tests without a database server."""

from __future__ import annotations

import unittest
from contextlib import AbstractAsyncContextManager
from datetime import datetime, timezone
from typing import Any

from magi.agents import (
    InvocationStatus,
    ModelInvocationRecord,
    ModelTokenUsage,
)
from magi.domain import AgentName
from magi.infrastructure import PostgresInvocationLedger, decision_thread_id
from tests.fixtures.factories import make_ballot, make_case


class AsyncContext(AbstractAsyncContextManager[Any]):
    def __init__(self, value: object) -> None:
        self.value = value

    async def __aenter__(self) -> object:
        return self.value

    async def __aexit__(self, *exc_info: object) -> None:
        return None


class FakeCursor:
    def __init__(self, row: dict[str, object] | None = None) -> None:
        self.row = row

    async def fetchone(self) -> dict[str, object] | None:
        return self.row


class FakeConnection:
    def __init__(self, ballot: dict[str, object]) -> None:
        self.ballot = ballot
        self.calls: list[tuple[str, object | None]] = []
        self.transactions = 0

    async def execute(self, query: str, params: object | None = None) -> FakeCursor:
        normalized = " ".join(query.split())
        self.calls.append((normalized, params))
        if normalized.startswith("SELECT ballot FROM"):
            return FakeCursor({"ballot": self.ballot})
        return FakeCursor()

    def transaction(self) -> AsyncContext:
        self.transactions += 1
        return AsyncContext(None)


class FakePool:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection_value = connection
        self.checkouts = 0

    def connection(self) -> AsyncContext:
        self.checkouts += 1
        return AsyncContext(self.connection_value)


def invocation_record() -> ModelInvocationRecord:
    case = make_case()
    timestamp = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
    return ModelInvocationRecord(
        idempotency_key="a" * 64,
        prompt_digest="b" * 64,
        decision_id=case.decision_id,
        decision_version=case.version,
        agent=AgentName.MELCHIOR,
        round=1,
        attempt=1,
        status=InvocationStatus.SUCCEEDED,
        model_name="test-model",
        started_at=timestamp,
        completed_at=timestamp,
        latency_ms=0,
        usage=ModelTokenUsage(input_tokens=3, output_tokens=2, total_tokens=5),
    )


class PostgresInvocationLedgerTests(unittest.IsolatedAsyncioTestCase):
    async def test_guard_reuses_one_connection_for_read_and_atomic_append(self) -> None:
        case = make_case()
        ballot = make_ballot(case, AgentName.MELCHIOR, "release").model_dump(mode="json")
        connection = FakeConnection(ballot)
        pool = FakePool(connection)
        ledger = PostgresInvocationLedger(pool)  # type: ignore[arg-type]
        record = invocation_record()

        async with ledger.guard(record.idempotency_key):
            stored = await ledger.get_ballot(record.idempotency_key)
            await ledger.append(record, ballot)

        self.assertEqual(stored, ballot)
        self.assertEqual(pool.checkouts, 1)
        self.assertEqual(connection.transactions, 1)
        queries = tuple(query for query, _ in connection.calls)
        self.assertTrue(any("pg_advisory_lock" in query for query in queries))
        self.assertTrue(any("pg_advisory_unlock" in query for query in queries))
        self.assertTrue(any("INSERT INTO magi_model_invocations" in query for query in queries))
        self.assertTrue(any("INSERT INTO magi_model_ballots" in query for query in queries))

    async def test_setup_executes_schema_in_one_transaction(self) -> None:
        connection = FakeConnection({})
        pool = FakePool(connection)
        ledger = PostgresInvocationLedger(pool)  # type: ignore[arg-type]

        await ledger.setup()

        self.assertEqual(pool.checkouts, 1)
        self.assertEqual(connection.transactions, 1)
        self.assertGreaterEqual(len(connection.calls), 4)

    def test_decision_thread_id_is_stable_and_bounded(self) -> None:
        case = make_case()
        thread_id = decision_thread_id(case.decision_id, case.version)
        self.assertEqual(thread_id, f"{case.decision_id}:{case.version}")
        self.assertLessEqual(len(thread_id), 255)

    def test_decision_thread_id_rejects_invalid_version(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive"):
            decision_thread_id("decision", 0)


if __name__ == "__main__":
    unittest.main()
