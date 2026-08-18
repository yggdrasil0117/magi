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
from magi.application import (
    CommandIdempotencyConflict,
    DecisionView,
    DecisionViewProjector,
)
from magi.domain import AgentName, ProtocolViolation
from magi.infrastructure import (
    PostgresCommandIdempotencyStore,
    PostgresInvocationLedger,
    PostgresPersistenceRuntime,
    decision_thread_id,
)
from tests.fixtures.factories import make_ballot, make_case, make_snapshot


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
    def __init__(
        self,
        ballot: dict[str, object],
        *,
        command_row: dict[str, object] | None = None,
    ) -> None:
        self.ballot = ballot
        self.command_row = command_row
        self.calls: list[tuple[str, object | None]] = []
        self.transactions = 0

    async def execute(self, query: str, params: object | None = None) -> FakeCursor:
        normalized = " ".join(query.split())
        self.calls.append((normalized, params))
        if normalized.startswith("SELECT ballot FROM"):
            return FakeCursor({"ballot": self.ballot})
        if normalized.startswith("SELECT fingerprint, response FROM"):
            return FakeCursor(self.command_row)
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


def command_view() -> DecisionView:
    case = make_case(confirmed=False)
    return DecisionViewProjector().project(
        {
            "case": case.model_dump(mode="json"),
            "snapshot": make_snapshot(case).model_dump(mode="json"),
            "phase": "waiting_for_user",
        }
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

    def test_runtime_requires_pool_capacity_beyond_guard_connection(self) -> None:
        with self.assertRaisesRegex(ValueError, "max_size >= 2"):
            PostgresPersistenceRuntime(
                "postgresql://magi:example@127.0.0.1:5432/magi",
                max_size=1,
            )


class PostgresCommandIdempotencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_cache_miss_executes_and_persists_without_raw_keys(self) -> None:
        connection = FakeConnection({})
        pool = FakePool(connection)
        store = PostgresCommandIdempotencyStore(pool)  # type: ignore[arg-type]
        calls = 0

        async def operation() -> DecisionView:
            nonlocal calls
            calls += 1
            return command_view()

        view = await store.execute(
            principal="private-user@example.test",
            idempotency_key="private-command-key",
            fingerprint="c" * 64,
            operation=operation,
        )

        self.assertEqual(view, command_view())
        self.assertEqual(calls, 1)
        self.assertEqual(pool.checkouts, 1)
        self.assertEqual(connection.transactions, 1)
        queries = tuple(query for query, _ in connection.calls)
        self.assertTrue(any("pg_advisory_lock" in query for query in queries))
        self.assertTrue(any("INSERT INTO magi_api_command_results" in query for query in queries))
        self.assertTrue(any("pg_advisory_unlock" in query for query in queries))
        parameters = repr(tuple(params for _, params in connection.calls))
        self.assertNotIn("private-user@example.test", parameters)
        self.assertNotIn("private-command-key", parameters)

    async def test_cache_hit_returns_persisted_view_without_operation(self) -> None:
        expected = command_view()
        connection = FakeConnection(
            {},
            command_row={
                "fingerprint": "d" * 64,
                "response": expected.model_dump(mode="json"),
            },
        )
        store = PostgresCommandIdempotencyStore(
            FakePool(connection)  # type: ignore[arg-type]
        )

        async def operation() -> DecisionView:
            raise AssertionError("cached command must not execute")

        actual = await store.execute(
            principal="user-1",
            idempotency_key="command-0001",
            fingerprint="d" * 64,
            operation=operation,
        )

        self.assertEqual(actual, expected)
        self.assertFalse(
            any("INSERT INTO" in query for query, _ in connection.calls)
        )

    async def test_cache_hit_with_different_fingerprint_conflicts(self) -> None:
        connection = FakeConnection(
            {},
            command_row={
                "fingerprint": "e" * 64,
                "response": command_view().model_dump(mode="json"),
            },
        )
        store = PostgresCommandIdempotencyStore(
            FakePool(connection)  # type: ignore[arg-type]
        )

        async def operation() -> DecisionView:
            raise AssertionError("conflicting command must not execute")

        with self.assertRaises(CommandIdempotencyConflict):
            await store.execute(
                principal="user-1",
                idempotency_key="command-0001",
                fingerprint="f" * 64,
                operation=operation,
            )

        self.assertTrue(
            any("pg_advisory_unlock" in query for query, _ in connection.calls)
        )

    async def test_invalid_persisted_view_is_an_integrity_failure(self) -> None:
        connection = FakeConnection(
            {},
            command_row={
                "fingerprint": "a" * 64,
                "response": {"not": "a decision view"},
            },
        )
        store = PostgresCommandIdempotencyStore(
            FakePool(connection)  # type: ignore[arg-type]
        )

        async def operation() -> DecisionView:
            raise AssertionError("invalid persisted response must not execute")

        with self.assertRaisesRegex(ProtocolViolation, "persisted"):
            await store.execute(
                principal="user-1",
                idempotency_key="command-0001",
                fingerprint="a" * 64,
                operation=operation,
            )

    async def test_setup_creates_command_schema_in_one_transaction(self) -> None:
        connection = FakeConnection({})
        store = PostgresCommandIdempotencyStore(
            FakePool(connection)  # type: ignore[arg-type]
        )

        await store.setup()

        self.assertEqual(connection.transactions, 1)
        self.assertGreaterEqual(len(connection.calls), 2)


if __name__ == "__main__":
    unittest.main()
