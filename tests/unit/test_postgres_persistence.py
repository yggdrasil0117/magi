"""Protocol-level PostgreSQL adapter tests without a database server."""

from __future__ import annotations

import asyncio
import unittest
from contextlib import AbstractAsyncContextManager
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from magi.agents import (
    InvocationStatus,
    ModelInvocationRecord,
    ModelTokenUsage,
)
from magi.application import (
    CommandIdempotencyConflict,
    DecisionView,
    DecisionViewProjector,
    OperationEventType,
    OperationIdempotencyConflict,
    OperationKind,
    OperationStage,
    OperationStatus,
)
from magi.domain import AgentName, DataClassification, ProtocolViolation
from magi.infrastructure import (
    PostgresCommandIdempotencyStore,
    PostgresInvocationLedger,
    PostgresOperationStore,
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
    def __init__(
        self,
        row: dict[str, object] | None = None,
        rows: list[dict[str, object]] | None = None,
    ) -> None:
        self.row = row
        self.rows = rows or []

    async def fetchone(self) -> dict[str, object] | None:
        return self.row

    async def fetchall(self) -> list[dict[str, object]]:
        return self.rows


class FakeConnection:
    def __init__(
        self,
        ballot: dict[str, object],
        *,
        command_row: dict[str, object] | None = None,
        operation_row: dict[str, object] | None = None,
        event_rows: list[dict[str, object]] | None = None,
    ) -> None:
        self.ballot = ballot
        self.command_row = command_row
        self.operation_row = operation_row
        self.event_rows = event_rows or []
        self.calls: list[tuple[str, object | None]] = []
        self.transactions = 0

    async def execute(self, query: str, params: object | None = None) -> FakeCursor:
        normalized = " ".join(query.split())
        self.calls.append((normalized, params))
        if normalized.startswith("SELECT ballot FROM"):
            return FakeCursor({"ballot": self.ballot})
        if normalized.startswith("SELECT fingerprint, response FROM"):
            return FakeCursor(self.command_row)
        if normalized.startswith("SELECT * FROM magi_operations"):
            return FakeCursor(self.operation_row)
        if normalized.startswith("SELECT 1 FROM magi_operations"):
            return FakeCursor({"exists": 1} if self.operation_row is not None else None)
        if normalized.startswith("SELECT 1 FROM magi_api_command_results"):
            return FakeCursor({"exists": 1} if self.command_row is not None else None)
        if normalized.startswith("SELECT operation_id, sequence, event_type"):
            return FakeCursor(rows=self.event_rows)
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


class FailingConnection(FakeConnection):
    async def execute(self, query: str, params: object | None = None) -> FakeCursor:
        raise RuntimeError("secret database detail")


class SlowConnection(FakeConnection):
    async def execute(self, query: str, params: object | None = None) -> FakeCursor:
        await asyncio.sleep(0.05)
        return await super().execute(query, params)


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


OPERATION_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
OPERATION_TIME = datetime(2026, 8, 18, 14, 0, tzinfo=timezone.utc)


def operation_row(*, fingerprint: str = "f" * 64) -> dict[str, object]:
    case = make_case()
    return {
        "operation_id": OPERATION_ID,
        "fingerprint": fingerprint,
        "kind": OperationKind.RUN_DECISION.value,
        "status": OperationStatus.ACCEPTED.value,
        "stage": OperationStage.QUEUED.value,
        "decision_id": case.decision_id,
        "decision_version": case.version,
        "created_at": OPERATION_TIME,
        "updated_at": OPERATION_TIME,
        "completed_at": None,
        "last_event_sequence": 1,
        "failure_code": None,
    }


def operation_event(sequence: int) -> dict[str, object]:
    return {
        "operation_id": OPERATION_ID,
        "sequence": sequence,
        "event_type": (
            OperationEventType.ACCEPTED.value
            if sequence == 1
            else OperationEventType.STAGE_CHANGED.value
        ),
        "status": (
            OperationStatus.ACCEPTED.value
            if sequence == 1
            else OperationStatus.RUNNING.value
        ),
        "stage": (
            OperationStage.QUEUED.value
            if sequence == 1
            else OperationStage.FIRST_BALLOT.value
        ),
        "message_code": (
            "operation_accepted" if sequence == 1 else "first_ballot_started"
        ),
        "occurred_at": OPERATION_TIME,
    }


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


class PostgresReadinessTests(unittest.IsolatedAsyncioTestCase):
    async def test_probe_is_bounded_fail_closed_and_executes_select(self) -> None:
        runtime = object.__new__(PostgresPersistenceRuntime)
        connection = FakeConnection({})
        runtime.pool = FakePool(connection)  # type: ignore[assignment]
        runtime._opened = True

        self.assertTrue(await runtime.is_ready(timeout_seconds=0.1))
        self.assertEqual(connection.calls[-1], ("SELECT 1", None))

        runtime._opened = False
        self.assertFalse(await runtime.is_ready(timeout_seconds=0.1))
        runtime._opened = True
        runtime.pool = FakePool(FailingConnection({}))  # type: ignore[assignment]
        self.assertFalse(await runtime.is_ready(timeout_seconds=0.1))
        runtime.pool = FakePool(SlowConnection({}))  # type: ignore[assignment]
        self.assertFalse(await runtime.is_ready(timeout_seconds=0.001))
        self.assertFalse(await runtime.is_ready(timeout_seconds=0))


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

    async def test_sync_command_conflicts_with_existing_async_operation(self) -> None:
        connection = FakeConnection({}, operation_row=operation_row())
        store = PostgresCommandIdempotencyStore(
            FakePool(connection)  # type: ignore[arg-type]
        )

        async def operation() -> DecisionView:
            raise AssertionError("cross-mode conflict must not execute")

        with self.assertRaises(CommandIdempotencyConflict):
            await store.execute(
                principal="user-1",
                idempotency_key="operation-key",
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


class PostgresOperationStoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_accept_inserts_receipt_and_first_event_atomically(self) -> None:
        connection = FakeConnection({})
        store = PostgresOperationStore(FakePool(connection))  # type: ignore[arg-type]
        case = make_case()

        receipt = await store.accept(
            principal="private-user@example.test",
            idempotency_key="private-operation-key",
            fingerprint="a" * 64,
            kind=OperationKind.CREATE_DECISION,
            decision_id=case.decision_id,
            decision_version=case.version,
            classification=DataClassification.SENSITIVE,
            request_payload={"raw_question": "Should this be created?"},
            accepted_at=OPERATION_TIME,
        )

        self.assertEqual(receipt.status, OperationStatus.ACCEPTED)
        self.assertEqual(receipt.stage, OperationStage.QUEUED)
        self.assertEqual(receipt.last_event_sequence, 1)
        self.assertEqual(connection.transactions, 1)
        queries = tuple(query for query, _ in connection.calls)
        self.assertTrue(any("INSERT INTO magi_operations" in query for query in queries))
        self.assertTrue(
            any("INSERT INTO magi_operation_events" in query for query in queries)
        )
        self.assertTrue(any("pg_advisory_unlock" in query for query in queries))
        parameters = repr(tuple(params for _, params in connection.calls))
        self.assertNotIn("private-user@example.test", parameters)
        self.assertNotIn("private-operation-key", parameters)
        insert_params = next(
            params
            for query, params in connection.calls
            if "INSERT INTO magi_operations" in query
        )
        assert isinstance(insert_params, tuple)
        self.assertEqual(
            insert_params[9].obj["raw_question"],  # type: ignore[union-attr]
            "Should this be created?",
        )

    async def test_accept_replays_existing_receipt_and_rejects_conflict(self) -> None:
        existing = operation_row(fingerprint="b" * 64)
        connection = FakeConnection({}, operation_row=existing)
        store = PostgresOperationStore(FakePool(connection))  # type: ignore[arg-type]
        case = make_case()
        common = {
            "principal": "user-1",
            "idempotency_key": "operation-0001",
            "kind": OperationKind.RUN_DECISION,
            "decision_id": case.decision_id,
            "decision_version": case.version,
            "classification": DataClassification.INTERNAL,
            "request_payload": {"version": case.version},
            "accepted_at": OPERATION_TIME,
        }

        replayed = await store.accept(fingerprint="b" * 64, **common)
        self.assertEqual(replayed.operation_id, OPERATION_ID)
        self.assertFalse(any("INSERT INTO" in query for query, _ in connection.calls))

        with self.assertRaises(OperationIdempotencyConflict):
            await store.accept(fingerprint="c" * 64, **common)

    async def test_accept_conflicts_with_existing_synchronous_command(self) -> None:
        connection = FakeConnection(
            {},
            command_row={"fingerprint": "d" * 64, "response": {}},
        )
        store = PostgresOperationStore(FakePool(connection))  # type: ignore[arg-type]
        case = make_case()

        with self.assertRaises(OperationIdempotencyConflict):
            await store.accept(
                principal="user-1",
                idempotency_key="shared-command-key",
                fingerprint="e" * 64,
                kind=OperationKind.RUN_DECISION,
                decision_id=case.decision_id,
                decision_version=case.version,
                classification=DataClassification.INTERNAL,
                request_payload={"version": 1},
                accepted_at=OPERATION_TIME,
            )

    async def test_get_masks_non_owner_and_validates_receipt(self) -> None:
        owned_connection = FakeConnection({}, operation_row=operation_row())
        store = PostgresOperationStore(
            FakePool(owned_connection)  # type: ignore[arg-type]
        )

        owned = await store.get(principal="user-1", operation_id=OPERATION_ID)
        self.assertIsNotNone(owned)
        parameters = repr(tuple(params for _, params in owned_connection.calls))
        self.assertNotIn("user-1", parameters)

        missing = await PostgresOperationStore(
            FakePool(FakeConnection({}))  # type: ignore[arg-type]
        ).get(principal="user-2", operation_id=OPERATION_ID)
        self.assertIsNone(missing)

        invalid_result = operation_row()
        invalid_result.update(
            {
                "status": OperationStatus.SUCCEEDED.value,
                "stage": OperationStage.COMPLETE.value,
                "completed_at": OPERATION_TIME,
                "result": {"not": "a decision view"},
            }
        )
        invalid_store = PostgresOperationStore(
            FakePool(  # type: ignore[arg-type]
                FakeConnection({}, operation_row=invalid_result)
            )
        )
        with self.assertRaisesRegex(ProtocolViolation, "persisted operation"):
            await invalid_store.get(
                principal="user-1",
                operation_id=OPERATION_ID,
            )

    async def test_events_are_cursor_ordered_bounded_and_owner_scoped(self) -> None:
        connection = FakeConnection(
            {},
            operation_row=operation_row(),
            event_rows=[operation_event(2), operation_event(3), operation_event(4)],
        )
        store = PostgresOperationStore(FakePool(connection))  # type: ignore[arg-type]

        page = await store.events(
            principal="user-1",
            operation_id=OPERATION_ID,
            after_sequence=1,
            limit=2,
        )

        self.assertIsNotNone(page)
        assert page is not None
        self.assertEqual(tuple(item.sequence for item in page.events), (2, 3))
        self.assertEqual(page.next_after_sequence, 3)
        self.assertTrue(page.has_more)

        with self.assertRaisesRegex(ValueError, "between 1 and 100"):
            await store.events(
                principal="user-1",
                operation_id=OPERATION_ID,
                limit=101,
            )

    async def test_setup_creates_operation_schema_in_one_transaction(self) -> None:
        connection = FakeConnection({})
        store = PostgresOperationStore(FakePool(connection))  # type: ignore[arg-type]

        await store.setup()

        self.assertEqual(connection.transactions, 1)
        self.assertEqual(len(connection.calls), 4)


if __name__ == "__main__":
    unittest.main()
