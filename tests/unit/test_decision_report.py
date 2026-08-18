"""Tests for deterministic, dissent-preserving final decision reports."""

from __future__ import annotations

import unittest

from pydantic import ValidationError

from magi.arbitration import DeterministicArbiter
from magi.application import DecisionReportProjector
from magi.domain import AgentName, ArbitrationStatus, Ballot, ProtocolViolation
from tests.fixtures.factories import make_ballot, make_case, make_snapshot, stable_id


class DecisionReportProjectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.case = make_case(confirmed=True)
        self.snapshot = make_snapshot(self.case)
        self.projector = DecisionReportProjector()

    def _first_ballots(self) -> dict[AgentName, Ballot]:
        return {
            agent: make_ballot(self.case, agent, option)
            for agent, option in {
                AgentName.MELCHIOR: "release",
                AgentName.BALTHASAR: "delay",
                AgentName.CASPER: "release",
            }.items()
        }

    def test_majority_report_preserves_dissent_and_revision_audit(self) -> None:
        first = self._first_ballots()
        reviews = (
            make_ballot(
                self.case,
                AgentName.MELCHIOR,
                "release",
                round_number=2,
                previous_ballot_id=first[AgentName.MELCHIOR].ballot_id,
                rationale_summary=("Release checks passed.",),
                assumptions=("Rollback remains available.",),
                risks=("Deployment may be slow.",),
                review_reason="Casper's timing concern did not outweigh the checks.",
            ),
            make_ballot(
                self.case,
                AgentName.BALTHASAR,
                "delay",
                round_number=2,
                previous_ballot_id=first[AgentName.BALTHASAR].ballot_id,
                rationale_summary=("User impact remains uncertain.",),
                risks=("Users could lose work.",),
                review_reason="The safeguards do not resolve the user-impact risk.",
            ),
            make_ballot(
                self.case,
                AgentName.CASPER,
                "release",
                round_number=2,
                previous_ballot_id=first[AgentName.CASPER].ballot_id,
                rationale_summary=("Release checks passed.", "Delay has opportunity cost."),
                assumptions=("Rollback remains available.",),
                changed=True,
                review_reason="Melchior's verified checks resolved the timing concern.",
            ),
        )
        result = DeterministicArbiter().arbitrate(
            self.case,
            self.snapshot,
            reviews,
        )

        report = self.projector.project(
            self.case,
            result,
            tuple(first.values()),
            tuple(reversed(reviews)),
        )
        rebuilt = self.projector.project(
            self.case,
            result,
            tuple(reversed(tuple(first.values()))),
            reviews,
        )

        self.assertEqual(report, rebuilt)
        self.assertEqual(report.status, ArbitrationStatus.MAJORITY)
        self.assertEqual(report.selected_option, "release")
        self.assertEqual(report.selected_option_label, "Release")
        self.assertEqual(
            report.majority_rationale,
            ("Release checks passed.", "Delay has opportunity cost."),
        )
        self.assertEqual(report.minority_report.agent, AgentName.BALTHASAR)
        self.assertEqual(
            report.minority_report.rationale_summary,
            ("User impact remains uncertain.",),
        )
        self.assertEqual(report.assumptions, ("Rollback remains available.",))
        self.assertEqual(len(report.review_audit), 3)
        self.assertEqual(
            tuple(item.agent for item in report.review_audit),
            tuple(sorted(AgentName, key=lambda agent: agent.value)),
        )
        casper_audit = next(
            item for item in report.review_audit if item.agent is AgentName.CASPER
        )
        self.assertTrue(casper_audit.changed)
        self.assertIn("timing concern", casper_audit.reason)

    def test_unresolved_report_does_not_invent_a_selected_option(self) -> None:
        first = self._first_ballots()
        choices = {
            AgentName.MELCHIOR: "release",
            AgentName.BALTHASAR: "delay",
            AgentName.CASPER: "limited",
        }
        reviews = tuple(
            make_ballot(
                self.case,
                agent,
                option,
                round_number=2,
                previous_ballot_id=first[agent].ballot_id,
                review_reason="Peer review did not resolve the trade-off.",
            )
            for agent, option in choices.items()
        )
        result = DeterministicArbiter().arbitrate(self.case, self.snapshot, reviews)

        report = self.projector.project(
            self.case,
            result,
            tuple(first.values()),
            reviews,
        )

        self.assertEqual(report.status, ArbitrationStatus.UNRESOLVED)
        self.assertIsNone(report.selected_option)
        self.assertIsNone(report.selected_option_label)
        self.assertEqual(report.majority_rationale, ())
        self.assertIsNone(report.minority_report)
        self.assertIn("new decision version", report.recommended_next_step)

    def test_second_round_ballot_without_reason_is_rejected(self) -> None:
        first = make_ballot(self.case, AgentName.MELCHIOR, "release")
        payload = make_ballot(
            self.case,
            AgentName.MELCHIOR,
            "delay",
            round_number=2,
            previous_ballot_id=first.ballot_id,
        ).model_dump()
        payload["review_reason"] = None

        with self.assertRaisesRegex(ValidationError, "audit reason"):
            Ballot.model_validate(payload)

    def test_result_ballot_reference_mismatch_is_rejected(self) -> None:
        ballots = tuple(
            make_ballot(self.case, agent, "release") for agent in AgentName
        )
        result = DeterministicArbiter().arbitrate(self.case, self.snapshot, ballots)
        mismatched = result.model_copy(update={"ballot_refs": (stable_id("unknown"),)})

        with self.assertRaisesRegex(ProtocolViolation, "references"):
            self.projector.project(self.case, mismatched, ballots, ballots)


if __name__ == "__main__":
    unittest.main()
