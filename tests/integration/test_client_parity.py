"""M3 acceptance: terminal and Web consume the same versioned report contract."""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

from magi.application import DecisionReport
from magi.clients import DecisionReportTerminalRenderer, tui

ROOT = Path(__file__).resolve().parents[2]
REPORT_FIXTURE = ROOT / "tests" / "fixtures" / "v1" / "decision-report-majority.json"
EVALUATION_FIXTURE = ROOT / "tests" / "fixtures" / "v1" / "evaluation-history.json"
NODE = shutil.which("node")


class ClientReportParityTests(unittest.TestCase):
    @unittest.skipUnless(NODE, "Node.js is not installed")
    def test_terminal_and_web_preserve_the_same_majority_contract(self) -> None:
        report = DecisionReport.model_validate_json(
            REPORT_FIXTURE.read_text(encoding="utf-8")
        )
        terminal = DecisionReportTerminalRenderer().render(report, color=False)

        web = subprocess.run(
            [NODE, str(ROOT / "apps" / "web" / "report.test.mjs")],
            cwd=ROOT,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )

        self.assertEqual(web.returncode, 0, web.stderr)
        self.assertIn("MAJORITY", terminal)
        self.assertIn("Release [release]", terminal)
        self.assertIn("balthasar rationale", terminal)
        self.assertIn("balthasar", terminal)
        self.assertIn("pass 2", web.stdout)

    @unittest.skipUnless(NODE, "Node.js is not installed")
    def test_terminal_and_web_preserve_the_same_evaluation_contract(self) -> None:
        history = json.loads(EVALUATION_FIXTURE.read_text(encoding="utf-8"))
        terminal = tui._render_evaluation(history)

        web = subprocess.run(
            [NODE, str(ROOT / "apps" / "web" / "evaluation.test.mjs")],
            cwd=ROOT,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )

        self.assertEqual(web.returncode, 0, web.stderr)
        for label in (
            "E-01 CITATION",
            "E-02 PERSONA",
            "E-03 ARBITRATION",
            "E-04 P95 LATENCY",
            "E-05 COST",
        ):
            self.assertIn(label, terminal)
        self.assertIn("1200 ms", terminal)
        self.assertIn("USD 0.000600", terminal)
        self.assertIn("evaluation view preserves", web.stdout)


if __name__ == "__main__":
    unittest.main()
