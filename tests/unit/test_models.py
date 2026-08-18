"""Validation tests for immutable M1 domain records."""

import unittest
from datetime import datetime

from pydantic import ValidationError

from magi.domain import (
    AgentName,
    Ballot,
    DataClassification,
    DecisionCase,
    DecisionOption,
    DecisionType,
    EvidenceQuality,
    ConstraintValidation,
    ConstraintValidationStatus,
    RiskLevel,
    Stance,
)
from tests.fixtures.factories import DECISION_ID, TIMESTAMP, make_ballot, make_case


class DecisionCaseTests(unittest.TestCase):
    def test_requires_unique_option_ids(self) -> None:
        with self.assertRaisesRegex(ValidationError, "option IDs must be unique"):
            DecisionCase(
                decision_id=DECISION_ID,
                title="Duplicate options",
                raw_question="Choose.",
                question="Choose.",
                decision_type=DecisionType.SINGLE_CHOICE,
                options=(
                    DecisionOption(id="same", label="A"),
                    DecisionOption(id="same", label="B"),
                ),
                risk_level=RiskLevel.LOW,
                data_classification=DataClassification.INTERNAL,
                confirmed_at=TIMESTAMP,
            )

    def test_boolean_case_requires_exactly_two_options(self) -> None:
        with self.assertRaisesRegex(ValidationError, "exactly two"):
            DecisionCase(
                decision_id=DECISION_ID,
                title="Boolean decision",
                raw_question="Proceed?",
                question="Proceed?",
                decision_type=DecisionType.BOOLEAN,
                options=(
                    DecisionOption(id="yes", label="Yes"),
                    DecisionOption(id="no", label="No"),
                    DecisionOption(id="later", label="Later"),
                ),
                risk_level=RiskLevel.LOW,
                data_classification=DataClassification.INTERNAL,
                confirmed_at=TIMESTAMP,
            )

    def test_records_are_immutable(self) -> None:
        case = make_case()
        with self.assertRaises(ValidationError):
            case.title = "Changed"  # type: ignore[misc]

    def test_confirmation_timestamp_must_be_timezone_aware(self) -> None:
        payload = make_case().model_dump()
        payload["confirmed_at"] = datetime(2026, 8, 18)
        with self.assertRaisesRegex(ValidationError, "timezone-aware"):
            DecisionCase.model_validate(payload)


class BallotTests(unittest.TestCase):
    def test_abstention_cannot_select_an_option(self) -> None:
        case = make_case()
        with self.assertRaisesRegex(ValidationError, "abstention cannot select"):
            Ballot(
                decision_id=case.decision_id,
                decision_version=case.version,
                agent=AgentName.MELCHIOR,
                round=1,
                selected_option="release",
                stance=Stance.ABSTAIN,
                confidence=0.2,
                evidence_quality=EvidenceQuality.WEAK,
                rationale_summary=("Insufficient information",),
            )

    def test_non_abstention_requires_an_option(self) -> None:
        case = make_case()
        with self.assertRaisesRegex(ValidationError, "must select an option"):
            Ballot(
                decision_id=case.decision_id,
                decision_version=case.version,
                agent=AgentName.MELCHIOR,
                round=1,
                stance=Stance.SUPPORT,
                confidence=0.2,
                evidence_quality=EvidenceQuality.WEAK,
                rationale_summary=("No selection",),
            )

    def test_second_round_requires_previous_ballot(self) -> None:
        case = make_case()
        ballot = make_ballot(case, AgentName.MELCHIOR, "release")
        payload = ballot.model_dump()
        payload.update({"round": 2, "previous_ballot_id": None})
        with self.assertRaisesRegex(ValidationError, "must reference"):
            Ballot.model_validate(payload)

    def test_accepted_constraint_requires_reconsideration_condition(self) -> None:
        with self.assertRaisesRegex(ValidationError, "reconsideration condition"):
            ConstraintValidation(
                claim_id=DECISION_ID,
                status=ConstraintValidationStatus.ACCEPTED,
                reason="The constraint is supported.",
            )


if __name__ == "__main__":
    unittest.main()
