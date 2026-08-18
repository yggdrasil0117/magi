"""Ensure checked-in M1 fixtures conform to data-contract version 1.0."""

import unittest
from pathlib import Path

from pydantic import TypeAdapter

from magi.domain import Ballot, DecisionCase, EvidenceSnapshot

FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "v1"


class VersionedFixtureTests(unittest.TestCase):
    def test_decision_case_fixture(self) -> None:
        case = DecisionCase.model_validate_json(
            (FIXTURE_ROOT / "decision-case.json").read_text(encoding="utf-8")
        )
        self.assertEqual(case.schema_version, "1.0")
        self.assertEqual(case.version, 1)

    def test_evidence_snapshot_fixture(self) -> None:
        snapshot = EvidenceSnapshot.model_validate_json(
            (FIXTURE_ROOT / "evidence-snapshot.json").read_text(encoding="utf-8")
        )
        self.assertEqual(snapshot.decision_version, 1)
        self.assertEqual(len(snapshot.evidence), 1)

    def test_ballot_fixture(self) -> None:
        adapter = TypeAdapter(list[Ballot])
        ballots = adapter.validate_json(
            (FIXTURE_ROOT / "ballots-round1.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(ballots), 3)
        self.assertEqual({ballot.round for ballot in ballots}, {1})


if __name__ == "__main__":
    unittest.main()

