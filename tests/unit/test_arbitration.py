"""Protocol routing and deterministic arbitration tests."""

import unittest

from magi.arbitration import DeterministicArbiter
from magi.domain import (
    AgentName,
    ArbitrationStatus,
    ConstraintValidation,
    ConstraintValidationStatus,
    CrossReviewRequired,
    DataClassification,
    DecisionCase,
    DecisionType,
    DuplicateBallotError,
    EvidenceSnapshot,
    ProtocolViolation,
    RiskLevel,
    RoundAction,
    Stance,
)
from tests.fixtures.factories import (
    make_ballot,
    make_case,
    make_claim,
    make_snapshot,
)


AGENTS = (
    AgentName.MELCHIOR,
    AgentName.BALTHASAR,
    AgentName.CASPER,
)


class ArbitrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.arbiter = DeterministicArbiter()

    def ballots(self, case, options, *, round_number=1, **kwargs):
        return tuple(
            make_ballot(
                case,
                agent,
                option,
                round_number=round_number,
                **kwargs,
            )
            for agent, option in zip(AGENTS, options, strict=True)
        )

    def test_low_risk_unanimous_first_round_is_consensus(self) -> None:
        case = make_case(risk_level=RiskLevel.LOW)
        snapshot = make_snapshot(case)
        ballots = self.ballots(case, ("release", "release", "release"))
        assessment = self.arbiter.assess_first_round(case, snapshot, ballots)
        self.assertEqual(assessment.action, RoundAction.ARBITRATE)
        result = self.arbiter.arbitrate(case, snapshot, ballots)
        self.assertEqual(result.status, ArbitrationStatus.CONSENSUS)
        self.assertEqual(result.winning_option, "release")
        self.assertIsNone(result.minority_report)

    def test_high_risk_unanimous_first_round_requires_review(self) -> None:
        case = make_case(risk_level=RiskLevel.HIGH)
        snapshot = make_snapshot(case)
        ballots = self.ballots(case, ("release", "release", "release"))
        assessment = self.arbiter.assess_first_round(case, snapshot, ballots)
        self.assertEqual(assessment.action, RoundAction.CROSS_REVIEW)
        with self.assertRaises(CrossReviewRequired):
            self.arbiter.arbitrate(case, snapshot, ballots)

    def test_first_round_two_to_one_requires_review(self) -> None:
        case = make_case()
        snapshot = make_snapshot(case)
        ballots = self.ballots(case, ("limited", "limited", "delay"))
        with self.assertRaises(CrossReviewRequired):
            self.arbiter.arbitrate(case, snapshot, ballots)

    def test_second_round_two_to_one_preserves_minority(self) -> None:
        case = make_case()
        snapshot = make_snapshot(case)
        ballots = self.ballots(
            case,
            ("limited", "limited", "delay"),
            round_number=2,
        )
        result = self.arbiter.arbitrate(case, snapshot, ballots)
        self.assertEqual(result.status, ArbitrationStatus.MAJORITY)
        self.assertEqual(result.winning_option, "limited")
        self.assertIsNotNone(result.minority_report)
        self.assertEqual(result.minority_report.agent, AgentName.CASPER)
        self.assertEqual(result.minority_report.selected_option, "delay")

    def test_confidence_does_not_weight_votes(self) -> None:
        case = make_case()
        snapshot = make_snapshot(case)
        ballots = (
            make_ballot(
                case,
                AgentName.MELCHIOR,
                "limited",
                round_number=2,
                confidence=0.1,
            ),
            make_ballot(
                case,
                AgentName.BALTHASAR,
                "limited",
                round_number=2,
                confidence=0.1,
            ),
            make_ballot(
                case,
                AgentName.CASPER,
                "delay",
                round_number=2,
                confidence=1.0,
            ),
        )
        result = self.arbiter.arbitrate(case, snapshot, ballots)
        self.assertEqual(result.status, ArbitrationStatus.MAJORITY)
        self.assertEqual(result.winning_option, "limited")

    def test_second_round_three_way_split_is_unresolved(self) -> None:
        case = make_case()
        snapshot = make_snapshot(case)
        ballots = self.ballots(
            case,
            ("release", "delay", "limited"),
            round_number=2,
        )
        result = self.arbiter.arbitrate(case, snapshot, ballots)
        self.assertEqual(result.status, ArbitrationStatus.UNRESOLVED)
        self.assertIsNone(result.winning_option)

    def test_two_abstentions_are_insufficient_information(self) -> None:
        case = make_case()
        snapshot = make_snapshot(case)
        ballots = (
            make_ballot(
                case,
                AgentName.MELCHIOR,
                None,
                stance=Stance.ABSTAIN,
                missing_information=("Performance test results",),
            ),
            make_ballot(
                case,
                AgentName.BALTHASAR,
                None,
                stance=Stance.ABSTAIN,
                missing_information=("Rollback plan",),
            ),
            make_ballot(case, AgentName.CASPER, "limited"),
        )
        result = self.arbiter.arbitrate(case, snapshot, ballots)
        self.assertEqual(result.status, ArbitrationStatus.INSUFFICIENT_INFORMATION)
        self.assertIn("Performance test results", result.required_information)
        self.assertIn("Rollback plan", result.required_information)

    def test_one_missing_agent_is_degraded(self) -> None:
        case = make_case()
        snapshot = make_snapshot(case)
        ballots = (
            make_ballot(case, AgentName.MELCHIOR, "release"),
            make_ballot(case, AgentName.BALTHASAR, "release"),
        )
        result = self.arbiter.arbitrate(case, snapshot, ballots)
        self.assertEqual(result.status, ArbitrationStatus.DEGRADED)
        self.assertIn("Missing perspective agent: casper", result.required_information)

    def test_two_missing_agents_fail(self) -> None:
        case = make_case()
        snapshot = make_snapshot(case)
        ballots = (make_ballot(case, AgentName.MELCHIOR, "release"),)
        result = self.arbiter.arbitrate(case, snapshot, ballots)
        self.assertEqual(result.status, ArbitrationStatus.FAILED)

    def test_accepted_constraint_conditionally_rejects(self) -> None:
        case = make_case()
        snapshot = make_snapshot(case)
        claim = make_claim()
        ballots = (
            make_ballot(case, AgentName.MELCHIOR, "release"),
            make_ballot(
                case,
                AgentName.BALTHASAR,
                "delay",
                claims=(claim,),
            ),
            make_ballot(case, AgentName.CASPER, "release"),
        )
        validation = ConstraintValidation(
            claim_id=claim.claim_id,
            status=ConstraintValidationStatus.ACCEPTED,
            reason="The hard safety constraint is supported.",
            condition_for_reconsideration="Provide a tested rollback and restore plan.",
        )
        result = self.arbiter.arbitrate(case, snapshot, ballots, (validation,))
        self.assertEqual(result.status, ArbitrationStatus.CONDITIONAL_REJECTION)
        self.assertEqual(result.unresolved_constraints, (claim.claim_id,))
        self.assertIn("tested rollback", result.conditions[0])

    def test_rejected_constraint_does_not_create_veto(self) -> None:
        case = make_case()
        snapshot = make_snapshot(case)
        claim = make_claim()
        ballots = (
            make_ballot(
                case,
                AgentName.MELCHIOR,
                "release",
                claims=(claim,),
            ),
            make_ballot(case, AgentName.BALTHASAR, "release"),
            make_ballot(case, AgentName.CASPER, "release"),
        )
        validation = ConstraintValidation(
            claim_id=claim.claim_id,
            status=ConstraintValidationStatus.REJECTED,
            reason="The submitted evidence does not support the causal chain.",
        )
        result = self.arbiter.arbitrate(case, snapshot, ballots, (validation,))
        self.assertEqual(result.status, ArbitrationStatus.CONSENSUS)

    def test_duplicate_agent_ballot_is_rejected(self) -> None:
        case = make_case()
        snapshot = make_snapshot(case)
        ballots = (
            make_ballot(case, AgentName.MELCHIOR, "release"),
            make_ballot(case, AgentName.MELCHIOR, "delay"),
            make_ballot(case, AgentName.CASPER, "release"),
        )
        with self.assertRaises(DuplicateBallotError):
            self.arbiter.assess_first_round(case, snapshot, ballots)

    def test_unknown_evidence_reference_is_rejected(self) -> None:
        case = make_case()
        snapshot = make_snapshot(case)
        ballots = (
            make_ballot(
                case,
                AgentName.MELCHIOR,
                "release",
                evidence_refs=("E-404",),
            ),
            make_ballot(case, AgentName.BALTHASAR, "release"),
            make_ballot(case, AgentName.CASPER, "release"),
        )
        with self.assertRaisesRegex(ProtocolViolation, "unknown evidence"):
            self.arbiter.assess_first_round(case, snapshot, ballots)

    def test_unconfirmed_case_is_rejected(self) -> None:
        case = make_case(confirmed=False)
        snapshot = make_snapshot(case)
        ballots = self.ballots(case, ("release", "release", "release"))
        with self.assertRaisesRegex(ProtocolViolation, "user-confirmed"):
            self.arbiter.assess_first_round(case, snapshot, ballots)

    def test_protocol_1_rejects_non_single_choice_arbitration(self) -> None:
        original = make_case()
        payload = original.model_dump()
        payload["decision_type"] = DecisionType.MULTIPLE_CHOICE
        case = DecisionCase.model_validate(payload)
        snapshot = make_snapshot(case)
        ballots = self.ballots(case, ("release", "release", "release"))
        with self.assertRaisesRegex(ProtocolViolation, "single-choice"):
            self.arbiter.assess_first_round(case, snapshot, ballots)

    def test_restricted_evidence_cannot_be_cited(self) -> None:
        case = make_case()
        snapshot_payload = make_snapshot(case).model_dump()
        evidence = list(snapshot_payload["evidence"])
        evidence[0] = {
            **evidence[0],
            "classification": DataClassification.RESTRICTED,
        }
        snapshot_payload["evidence"] = evidence
        snapshot = EvidenceSnapshot.model_validate(snapshot_payload)
        ballots = self.ballots(case, ("release", "release", "release"))
        with self.assertRaisesRegex(ProtocolViolation, "restricted evidence"):
            self.arbiter.assess_first_round(case, snapshot, ballots)

    def test_snapshot_version_must_match_case(self) -> None:
        case = make_case()
        snapshot_payload = make_snapshot(case).model_dump()
        snapshot_payload["decision_version"] = 2
        snapshot = EvidenceSnapshot.model_validate(snapshot_payload)
        ballots = self.ballots(case, ("release", "release", "release"))
        with self.assertRaisesRegex(ProtocolViolation, "version does not match"):
            self.arbiter.assess_first_round(case, snapshot, ballots)


if __name__ == "__main__":
    unittest.main()
