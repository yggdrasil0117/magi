"""Application service integration over real LangGraph checkpoints."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver

from magi.agents import ScriptedPerspectiveRunner
from magi.application import (
    DecisionApplicationService,
    DecisionWorkflowConflict,
    DecisionWorkflowNotFound,
)
from magi.domain import AgentName, ArbitrationStatus, DecisionState
from magi.orchestration import build_langgraph_workflow
from tests.fixtures.factories import make_ballot, make_case, make_snapshot


class DecisionApplicationServiceTests(unittest.IsolatedAsyncioTestCase):
    def build_service(
        self,
        saver: InMemorySaver | None = None,
    ) -> tuple[DecisionApplicationService, ScriptedPerspectiveRunner, InMemorySaver]:
        case = make_case(confirmed=False)
        runner = ScriptedPerspectiveRunner(
            {agent: make_ballot(case, agent, "release") for agent in AgentName}
        )
        selected_saver = saver or InMemorySaver()
        graph = build_langgraph_workflow(runner, checkpointer=selected_saver)
        return DecisionApplicationService(graph), runner, selected_saver

    async def test_new_service_instance_reads_and_resumes_confirmation(self) -> None:
        case = make_case(confirmed=False)
        snapshot = make_snapshot(case)
        first_service, _, saver = self.build_service()

        waiting = await first_service.wait_for_confirmation(case, snapshot)
        self.assertEqual(waiting.state, DecisionState.WAITING_FOR_USER)
        self.assertEqual(waiting.ballots, ())

        second_service, second_runner, _ = self.build_service(saver)
        restored = await second_service.get(case.decision_id, case.version)
        self.assertEqual(restored, waiting)

        ready = await second_service.confirm(
            case.decision_id,
            case.version,
            confirmed_at=datetime(2026, 8, 18, 14, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(ready.state, DecisionState.EVIDENCE_READY)
        self.assertTrue(ready.awaiting_run)
        self.assertEqual(ready.available_actions, ("run", "cancel"))
        self.assertEqual(second_runner.calls, [])

        third_service, third_runner, _ = self.build_service(saver)
        completed = await third_service.run(case.decision_id, case.version)

        self.assertEqual(completed.state, DecisionState.COMPLETED)
        self.assertEqual(completed.result.status, ArbitrationStatus.CONSENSUS)
        self.assertEqual(completed.result.winning_option, "release")
        self.assertEqual(len(completed.ballots), 3)
        self.assertEqual(len(second_runner.calls), 0)
        self.assertEqual(len(third_runner.calls), 3)

        repeated = await third_service.confirm_and_run(
            case.decision_id,
            case.version,
            confirmed_at=datetime(2026, 8, 18, 14, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(repeated, completed)
        self.assertEqual(len(third_runner.calls), 3)

        with self.assertRaisesRegex(DecisionWorkflowConflict, "terminal"):
            await third_service.cancel(
                case.decision_id,
                case.version,
                reason="Too late to cancel.",
            )

    async def test_cancel_stops_before_any_perspective_call(self) -> None:
        case = make_case(confirmed=False)
        service, runner, _ = self.build_service()
        await service.wait_for_confirmation(case, make_snapshot(case))

        cancelled = await service.cancel(
            case.decision_id,
            case.version,
            reason="The options need revision.",
        )

        self.assertEqual(cancelled.state, DecisionState.CANCELLED)
        self.assertTrue(cancelled.terminal)
        self.assertEqual(cancelled.ballots, ())
        self.assertEqual(runner.calls, [])

    async def test_cancel_after_confirmation_stops_before_run(self) -> None:
        case = make_case(confirmed=False)
        service, runner, _ = self.build_service()
        await service.wait_for_confirmation(case, make_snapshot(case))
        ready = await service.confirm(
            case.decision_id,
            case.version,
            confirmed_at=datetime(2026, 8, 18, 14, 30, tzinfo=timezone.utc),
        )
        self.assertTrue(ready.awaiting_run)

        cancelled = await service.cancel(
            case.decision_id,
            case.version,
            reason="Do not start voting.",
        )

        self.assertEqual(cancelled.state, DecisionState.CANCELLED)
        self.assertEqual(runner.calls, [])

    async def test_wait_is_idempotent_but_rejects_different_case(self) -> None:
        case = make_case(confirmed=False)
        service, _, _ = self.build_service()
        first = await service.wait_for_confirmation(case, make_snapshot(case))
        repeated = await service.wait_for_confirmation(case, make_snapshot(case))
        self.assertEqual(repeated, first)

        changed = case.model_copy(update={"title": "A different prepared case"})
        with self.assertRaisesRegex(DecisionWorkflowConflict, "different"):
            await service.wait_for_confirmation(changed, make_snapshot(changed))

        changed_snapshot = make_snapshot(case).model_copy(
            update={"snapshot_id": uuid4()}
        )
        with self.assertRaisesRegex(DecisionWorkflowConflict, "different"):
            await service.wait_for_confirmation(case, changed_snapshot)

    async def test_missing_workflow_is_reported_without_creating_state(self) -> None:
        case = make_case(confirmed=False)
        service, _, _ = self.build_service()

        with self.assertRaises(DecisionWorkflowNotFound):
            await service.get(case.decision_id, case.version)


if __name__ == "__main__":
    unittest.main()
