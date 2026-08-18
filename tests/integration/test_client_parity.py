"""M3 acceptance: terminal and Web consume the same versioned report contract."""

from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

from magi.application import DecisionReport
from magi.clients import DecisionReportTerminalRenderer

ROOT = Path(__file__).resolve().parents[2]
REPORT_FIXTURE = ROOT / "tests" / "fixtures" / "v1" / "decision-report-majority.json"
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


if __name__ == "__main__":
    unittest.main()
