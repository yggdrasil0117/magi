"""Tests for deterministic and injection-safe report export."""

from __future__ import annotations

import unittest

from magi.arbitration import DeterministicArbiter
from magi.application import DecisionReportMarkdownRenderer, DecisionReportProjector
from magi.domain import AgentName
from tests.fixtures.factories import make_ballot, make_case, make_snapshot


class DecisionReportMarkdownRendererTests(unittest.TestCase):
    def test_render_is_stable_and_escapes_untrusted_markdown(self) -> None:
        case = make_case(confirmed=True)
        snapshot = make_snapshot(case)
        ballots = tuple(
            make_ballot(case, agent, "release") for agent in AgentName
        )
        result = DeterministicArbiter().arbitrate(case, snapshot, ballots)
        report = DecisionReportProjector().project(case, result, ballots, ballots)
        report = report.model_copy(
            update={
                "majority_rationale": (
                    "<script>alert(1)</script> [click](javascript:alert(1)) *bold*\nnext",
                ),
                "recommended_next_step": "Use _verified_ evidence | then proceed.",
            }
        )
        renderer = DecisionReportMarkdownRenderer()

        first = renderer.render(report)
        second = renderer.render(report)

        self.assertEqual(first, second)
        self.assertNotIn("<script>", first)
        self.assertNotIn("[click]", first)
        self.assertNotIn("*bold*", first)
        self.assertIn(r"\<script\>", first)
        self.assertIn(r"\[click\]", first)
        self.assertIn(r"\*bold\* next", first)
        self.assertIn(r"Use \_verified\_ evidence \| then proceed.", first)
        self.assertIn("- No cross-review was required.", first)


if __name__ == "__main__":
    unittest.main()
