"""M2a workflow-node tests that do not require the LangGraph package."""

from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timezone

from pydantic import ValidationError

from magi.agents import ScriptedPerspectiveRunner
from magi.domain import (
    AgentName,
    ArbitrationResult,
    ArbitrationStatus,
    RoundAction,
)
from magi.orchestration import (
    ConfirmationPayload,
    MagiWorkflowNodes,
    PublicEventProjector,
)
from tests.fixtures.factories import make_ballot, make_case, make_snapshot


AGENTS = (
    AgentName.MELCHIOR,
    AgentName.BALTHASAR,
    AgentName.CASPER,
)
CONFIRMED_AT = datetime(2026, 8, 18, 9, 0, tzinfo=timezone.utc)


def merge_state(state, *updates):
    merged = dict(state)
    for update in updates:
        for key, value in update.items():
            if key in {"first_ballots", "review_ballots"}:
                merged[key] = [*merged.get(key, []), *value]
            else:
                merged[key] = value
    return merged


class WorkflowNodeTests(unittest.IsolatedAsyncioTestCase):
    def make_nodes(self):
        case = make_case(confirmed=False)
        snapshot = make_snapshot(case)
        first = {
            AgentName.MELCHIOR: make_ballot(case, AgentName.MELCHIOR, "limited"),
            AgentName.BALTHASAR: make_ballot(case, AgentName.BALTHASAR, "limited"),
            AgentName.CASPER: make_ballot(case, AgentName.CASPER, "delay"),
        }
        review = {
            agent: make_ballot(
                case,
                agent,
                first[agent].selected_option,
                round_number=2,
                previous_ballot_id=first[agent].ballot_id,
            )
            for agent in AGENTS
        }
        runner = ScriptedPerspectiveRunner(first, review)
        nodes = MagiWorkflowNodes(runner)
        state = {
            "case": case.model_dump(mode="json"),
            "snapshot": snapshot.model_dump(mode="json"),
            "constraint_validations": [],
        }
        return case, runner, nodes, state

    async def prepare_confirm_and_validate(self, nodes, state):
        state = merge_state(state, nodes.prepare_case(state))
        state = merge_state(
            state,
            nodes.apply_confirmation(
                state,
                {
                    "confirmed": True,
                    "confirmed_at": CONFIRMED_AT.isoformat(),
                },
            ),
        )
        return merge_state(state, nodes.validate_evidence(state))

    async def test_full_cross_review_path_returns_majority(self) -> None:
        case, runner, nodes, state = self.make_nodes()
        state = await self.prepare_confirm_and_validate(nodes, state)

        first_updates = await asyncio.gather(
            *(nodes.run_first_ballot(agent, state) for agent in AGENTS)
        )
        state = merge_state(state, *first_updates)
        assessment_update = nodes.assess_first(state)
        state = merge_state(state, assessment_update)
        self.assertEqual(
            state["first_assessment"]["action"],
            RoundAction.CROSS_REVIEW.value,
        )
        self.assertEqual(nodes.route_after_first(state), "cross_review")

        state = merge_state(state, nodes.begin_review(state))
        review_updates = await asyncio.gather(
            *(nodes.run_review_ballot(agent, state) for agent in AGENTS)
        )
        state = merge_state(state, *review_updates)
        state = merge_state(state, nodes.arbitrate(state))

        result = ArbitrationResult.model_validate(state["result"])
        self.assertEqual(result.status, ArbitrationStatus.MAJORITY)
        self.assertEqual(result.winning_option, "limited")
        self.assertEqual(len(state["first_ballots"]), 3)
        self.assertEqual(len(state["review_ballots"]), 3)
        self.assertEqual(len(runner.calls), 6)
        self.assertEqual(result.decision_id, case.decision_id)

    async def test_rejected_confirmation_cancels_without_agent_calls(self) -> None:
        _, runner, nodes, state = self.make_nodes()
        state = merge_state(state, nodes.prepare_case(state))
        update = nodes.apply_confirmation(
            state,
            {"confirmed": False, "reason": "Question needs revision"},
        )
        state = merge_state(state, update)
        self.assertEqual(nodes.route_after_confirmation(state), "cancelled")
        self.assertEqual(nodes.mark_cancelled(state)["phase"], "cancelled")
        self.assertEqual(runner.calls, [])

    async def test_confirmation_time_is_required(self) -> None:
        with self.assertRaisesRegex(ValidationError, "confirmed_at"):
            ConfirmationPayload(confirmed=True)

    async def test_first_ballot_events_do_not_disclose_votes(self) -> None:
        case, _, nodes, state = self.make_nodes()
        state = await self.prepare_confirm_and_validate(nodes, state)
        update = await nodes.run_first_ballot(AgentName.MELCHIOR, state)
        projector = PublicEventProjector(case.decision_id, case.version)
        event = projector.project("first_melchior", update)
        self.assertIsNotNone(event)
        self.assertEqual(event.type, "agent.completed")
        self.assertEqual(event.public_payload, {"agent": "melchior", "round": 1})
        rendered = event.model_dump_json()
        self.assertNotIn("selected_option", rendered)
        self.assertNotIn("rationale_summary", rendered)
        self.assertNotIn("first_ballots", rendered)

    async def test_vote_count_is_released_only_after_first_round_closes(self) -> None:
        case, _, nodes, state = self.make_nodes()
        state = await self.prepare_confirm_and_validate(nodes, state)
        updates = await asyncio.gather(
            *(nodes.run_first_ballot(agent, state) for agent in AGENTS)
        )
        state = merge_state(state, *updates)
        assessment_update = nodes.assess_first(state)
        projector = PublicEventProjector(case.decision_id, case.version)
        event = projector.project("assess_first", assessment_update)
        self.assertIsNotNone(event)
        self.assertEqual(event.type, "first_ballot.completed")
        self.assertEqual(event.public_payload["vote_count"]["limited"], 2)

    async def test_evidence_event_is_emitted_after_evidence_validation(self) -> None:
        case, _, nodes, state = self.make_nodes()
        state = merge_state(state, nodes.prepare_case(state))
        confirmation_update = nodes.apply_confirmation(
            state,
            {
                "confirmed": True,
                "confirmed_at": CONFIRMED_AT.isoformat(),
            },
        )
        projector = PublicEventProjector(case.decision_id, case.version)
        confirmation_event = projector.project("confirm_case", confirmation_update)
        self.assertEqual(confirmation_event.type, "case.confirmed")

        state = merge_state(state, confirmation_update)
        evidence_update = nodes.validate_evidence(state)
        evidence_event = projector.project("validate_evidence", evidence_update)
        self.assertEqual(evidence_event.type, "evidence.snapshot_created")


if __name__ == "__main__":
    unittest.main()
