"""Process-local API command idempotency tests."""

from __future__ import annotations

import asyncio
import unittest

from magi.application import (
    CommandIdempotencyConflict,
    DecisionView,
    DecisionViewProjector,
    InMemoryCommandIdempotencyStore,
)
from tests.fixtures.factories import make_case, make_snapshot


def waiting_view() -> DecisionView:
    case = make_case(confirmed=False)
    return DecisionViewProjector().project(
        {
            "case": case.model_dump(mode="json"),
            "snapshot": make_snapshot(case).model_dump(mode="json"),
            "phase": "waiting_for_user",
        }
    )


class CommandIdempotencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_duplicate_command_executes_once(self) -> None:
        store = InMemoryCommandIdempotencyStore()
        calls = 0

        async def operation() -> DecisionView:
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.01)
            return waiting_view()

        results = await asyncio.gather(
            *(
                store.execute(
                    principal="user-1",
                    idempotency_key="command-0001",
                    fingerprint="a" * 64,
                    operation=operation,
                )
                for _ in range(3)
            )
        )

        self.assertEqual(calls, 1)
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[1], results[2])

    async def test_same_key_with_different_fingerprint_conflicts(self) -> None:
        store = InMemoryCommandIdempotencyStore()

        async def operation() -> DecisionView:
            return waiting_view()

        await store.execute(
            principal="user-1",
            idempotency_key="command-0001",
            fingerprint="a" * 64,
            operation=operation,
        )

        with self.assertRaises(CommandIdempotencyConflict):
            await store.execute(
                principal="user-1",
                idempotency_key="command-0001",
                fingerprint="b" * 64,
                operation=operation,
            )

    async def test_same_key_is_scoped_by_authenticated_principal(self) -> None:
        store = InMemoryCommandIdempotencyStore()
        calls = 0

        async def operation() -> DecisionView:
            nonlocal calls
            calls += 1
            return waiting_view()

        for principal in ("user-1", "user-2"):
            await store.execute(
                principal=principal,
                idempotency_key="command-0001",
                fingerprint="a" * 64,
                operation=operation,
            )

        self.assertEqual(calls, 2)


if __name__ == "__main__":
    unittest.main()
