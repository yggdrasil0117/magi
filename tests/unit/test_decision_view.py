"""DecisionView projection tests for client-visible information boundaries."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from magi.arbitration import DeterministicArbiter
from magi.application import DecisionViewProjector
from magi.domain import (
    AgentName,
    DataClassification,
    DecisionState,
    EvidenceItem,
    ProtocolViolation,
    VerificationStatus,
)
from tests.fixtures.factories import make_ballot, make_case, make_snapshot


class DecisionViewProjectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.case = make_case(confirmed=False)
        base_snapshot = make_snapshot(self.case)
        restricted = EvidenceItem(
            evidence_id="E-SECRET",
            source_type="private_note",
            source="restricted.txt",
            captured_at=datetime(2026, 8, 18, 8, 0, tzinfo=timezone.utc),
            content_hash="f" * 64,
            excerpt="Restricted material must not enter DecisionView.",
            verification_status=VerificationStatus.UNVERIFIED,
            classification=DataClassification.RESTRICTED,
        )
        self.snapshot = base_snapshot.model_copy(
            update={"evidence": (*base_snapshot.evidence, restricted)}
        )
        self.projector = DecisionViewProjector()

    def state(self) -> dict[str, object]:
        return {
            "case": self.case.model_dump(mode="json"),
            "snapshot": self.snapshot.model_dump(mode="json"),
            "constraint_validations": [],
            "first_ballots": [],
            "review_ballots": [],
            "phase": "waiting_for_user",
        }

    def test_waiting_view_filters_restricted_evidence_and_offers_actions(self) -> None:
        view = self.projector.project(self.state())

        self.assertEqual(view.state, DecisionState.WAITING_FOR_USER)
        self.assertTrue(view.awaiting_confirmation)
        self.assertFalse(view.terminal)
        self.assertEqual(view.available_actions, ("confirm", "cancel"))
        self.assertEqual(tuple(item.evidence_id for item in view.evidence), ("E-001",))

    def test_partial_first_ballot_is_not_released(self) -> None:
        state = self.state()
        state["phase"] = "first_ballot"
        state["first_ballots"] = [
            make_ballot(
                self.case,
                AgentName.MELCHIOR,
                "release",
            ).model_dump(mode="json")
        ]

        view = self.projector.project(state)

        self.assertEqual(view.state, DecisionState.FIRST_BALLOT)
        self.assertEqual(view.ballots, ())
        rendered = view.model_dump_json()
        self.assertNotIn("melchior rationale", rendered)
        self.assertNotIn("ballot_id", rendered)

    def test_first_ballots_release_only_after_round_assessment(self) -> None:
        state = self.state()
        ballots = [
            make_ballot(self.case, agent, "release").model_dump(mode="json")
            for agent in AgentName
        ]
        state.update(
            {
                "phase": "cross_review",
                "first_ballots": ballots,
                "first_assessment": {
                    "action": "cross_review",
                    "vote_count": {"release": 3},
                },
            }
        )

        view = self.projector.project(state)

        self.assertEqual(view.state, DecisionState.CROSS_REVIEW)
        self.assertEqual(len(view.ballots), 3)
        self.assertIsNone(view.report)

    def test_completed_view_prefers_final_review_ballots(self) -> None:
        confirmed_case = make_case(confirmed=True)
        snapshot = make_snapshot(confirmed_case)
        first = {
            agent: make_ballot(confirmed_case, agent, "release")
            for agent in AgentName
        }
        reviews = tuple(
            make_ballot(
                confirmed_case,
                agent,
                "release",
                round_number=2,
                previous_ballot_id=first[agent].ballot_id,
            )
            for agent in AgentName
        )
        result = DeterministicArbiter().arbitrate(
            confirmed_case,
            snapshot,
            reviews,
            (),
        )
        state = {
            "case": confirmed_case.model_dump(mode="json"),
            "snapshot": snapshot.model_dump(mode="json"),
            "first_ballots": [ballot.model_dump(mode="json") for ballot in first.values()],
            "review_ballots": [ballot.model_dump(mode="json") for ballot in reviews],
            "result": result.model_dump(mode="json"),
            "phase": "completed",
        }

        view = self.projector.project(state)

        self.assertEqual(view.state, DecisionState.COMPLETED)
        self.assertTrue(view.terminal)
        self.assertEqual({ballot.round for ballot in view.ballots}, {2})
        self.assertEqual(view.result, result)
        self.assertIsNotNone(view.report)
        self.assertEqual(view.report.selected_option, "release")

    def test_mismatched_checkpoint_evidence_is_rejected(self) -> None:
        state = self.state()
        state["snapshot"] = self.snapshot.model_copy(
            update={"decision_version": 2}
        ).model_dump(mode="json")

        with self.assertRaisesRegex(ProtocolViolation, "evidence"):
            self.projector.project(state)


if __name__ == "__main__":
    unittest.main()
