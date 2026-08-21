from __future__ import annotations

import asyncio
import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from uuid import UUID

from magi.application import (
    OperationKind,
    OperationLease,
    OperationStage,
    OperationWorker,
)
from magi.domain import DataClassification

from tests.fixtures.factories import make_case, make_snapshot
from magi.application import DecisionViewProjector


NOW = datetime(2026, 8, 18, 15, 0, tzinfo=timezone.utc)


def lease() -> OperationLease:
    case = make_case()
    return OperationLease(
        operation_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        kind=OperationKind.RUN_DECISION,
        decision_id=case.decision_id,
        decision_version=case.version,
        classification=DataClassification.INTERNAL,
        request_payload={},
        fencing_token=1,
        lease_expires_at=NOW + timedelta(seconds=30),
    )


def view():
    case = make_case(confirmed=False)
    return DecisionViewProjector().project(
        {
            "case": case.model_dump(mode="json"),
            "snapshot": make_snapshot(case).model_dump(mode="json"),
            "phase": "waiting_for_user",
        }
    )


class FakeQueue:
    def __init__(self, claimed: OperationLease | None) -> None:
        self.claimed = claimed
        self.calls: list[tuple[str, object]] = []

    @asynccontextmanager
    async def claim(self, **kwargs):
        self.calls.append(("claim", kwargs))
        yield self.claimed

    async def renew(self, operation_lease, **kwargs):
        self.calls.append(("renew", kwargs))
        return operation_lease

    async def advance(self, operation_lease, **kwargs):
        self.calls.append(("advance", kwargs))

    async def succeed(self, operation_lease, **kwargs):
        self.calls.append(("succeed", kwargs))

    async def fail(self, operation_lease, **kwargs):
        self.calls.append(("fail", kwargs))


class SuccessfulExecutor:
    async def execute(self, operation_lease):
        return view()


class FailingExecutor:
    def __init__(self) -> None:
        self.recovered = False

    async def execute(self, operation_lease):
        raise RuntimeError("private model failure")

    async def recover_failure(self, operation_lease):
        self.recovered = True


class CancellingExecutor:
    async def execute(self, operation_lease):
        raise asyncio.CancelledError


class OperationWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_queue_does_no_work(self) -> None:
        queue = FakeQueue(None)
        worker = OperationWorker(
            queue, SuccessfulExecutor(), worker_id="worker-1", clock=lambda: NOW
        )

        self.assertFalse(await worker.run_once())
        self.assertEqual([name for name, _ in queue.calls], ["claim"])

    async def test_success_reports_then_completes(self) -> None:
        queue = FakeQueue(lease())
        worker = OperationWorker(
            queue, SuccessfulExecutor(), worker_id="worker-1", clock=lambda: NOW
        )

        self.assertTrue(await worker.run_once())
        self.assertEqual(
            [name for name, _ in queue.calls], ["claim", "advance", "succeed"]
        )
        advance = queue.calls[1][1]
        self.assertEqual(advance["stage"], OperationStage.REPORTING)

    async def test_failure_is_sanitized(self) -> None:
        queue = FakeQueue(lease())
        executor = FailingExecutor()
        worker = OperationWorker(
            queue, executor, worker_id="worker-1", clock=lambda: NOW
        )

        self.assertTrue(await worker.run_once())
        self.assertEqual([name for name, _ in queue.calls], ["claim", "fail"])
        failure = queue.calls[-1][1]
        self.assertEqual(failure["failure_code"], "operation_execution_failed")
        self.assertNotIn("private", repr(failure))
        self.assertTrue(executor.recovered)

    async def test_cancellation_leaves_operation_for_lease_recovery(self) -> None:
        queue = FakeQueue(lease())
        worker = OperationWorker(
            queue, CancellingExecutor(), worker_id="worker-1", clock=lambda: NOW
        )

        with self.assertRaises(asyncio.CancelledError):
            await worker.run_once()
        self.assertEqual([name for name, _ in queue.calls], ["claim"])


if __name__ == "__main__":
    unittest.main()
