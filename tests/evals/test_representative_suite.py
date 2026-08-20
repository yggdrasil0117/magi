"""M5d calibration against frozen synthetic acceptance outcomes."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from magi.domain import ProtocolViolation
from magi.evaluation import DecisionEvaluator
from tests.evals.scenarios import representative_scenarios


OUTCOMES = Path(__file__).parent / "v1" / "representative-outcomes.json"
METRICS = (
    "citation_validity",
    "persona_differentiation",
    "arbitration_consistency",
    "latency",
    "cost",
)


class RepresentativeEvaluationSuiteTests(unittest.TestCase):
    def test_scenarios_match_frozen_human_review_labels(self) -> None:
        manifest = json.loads(OUTCOMES.read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema_version"], "1.0")
        scenarios = representative_scenarios()
        expected_ids = {case["id"] for case in manifest["cases"]}
        self.assertEqual(len(expected_ids), len(manifest["cases"]))
        self.assertEqual(set(scenarios), expected_ids)

        for case in manifest["cases"]:
            with self.subTest(case=case["id"]):
                bundle = scenarios[case["id"]]
                if case.get("expected_error") == "protocol_violation":
                    self.assertEqual(case["review_label"], "reject")
                    with self.assertRaises(ProtocolViolation):
                        DecisionEvaluator().evaluate(bundle)
                    continue

                first = DecisionEvaluator().evaluate(bundle)
                replay = DecisionEvaluator().evaluate(bundle)
                self.assertEqual(first, replay)
                self.assertEqual(bundle.result.status.value, case["decision_status"])
                self.assertEqual(first.overall_status.value, case["overall_status"])
                self.assertEqual(
                    {name: getattr(first, name).status.value for name in METRICS},
                    case["metrics"],
                )
                self.assertEqual(
                    _review_label(first.overall_status.value),
                    case["review_label"],
                )


def _review_label(overall_status: str) -> str:
    return {"pass": "acceptable", "warn": "advisory", "fail": "reject"}[
        overall_status
    ]


if __name__ == "__main__":
    unittest.main()
