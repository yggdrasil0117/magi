"""Tests for the API-consuming terminal report client."""

from __future__ import annotations

import json
import unittest
from email.message import Message
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from magi.application import DecisionReport
from magi.clients import DecisionReportTerminalRenderer, ReportClientError, fetch_report
from tests.fixtures.factories import DECISION_ID

FIXTURE = (
    Path(__file__).parents[1]
    / "fixtures"
    / "v1"
    / "decision-report-majority.json"
)


class FakeResponse:
    def __init__(self, payload: bytes, headers: dict[str, str] | None = None) -> None:
        self.payload = payload
        self.headers = headers or {}

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, limit: int) -> bytes:
        return self.payload[:limit]


class TerminalReportClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = FIXTURE.read_bytes()
        self.report = DecisionReport.model_validate_json(self.payload)

    def test_fetch_uses_authorized_report_route_and_validates_response(self) -> None:
        with patch(
            "magi.clients.report_cli.urlopen",
            return_value=FakeResponse(self.payload),
        ) as mocked:
            report = fetch_report(
                "https://magi.example/base",
                DECISION_ID,
                1,
                "private-test-token",
            )

        request = mocked.call_args.args[0]
        self.assertEqual(report, self.report)
        self.assertEqual(
            request.full_url,
            f"https://magi.example/base/v1/decisions/{DECISION_ID}/report?version=1",
        )
        self.assertEqual(request.get_header("Authorization"), "Bearer private-test-token")

    def test_fetch_rejects_credentialed_urls_and_oversized_reports(self) -> None:
        with self.assertRaisesRegex(ReportClientError, "without credentials"):
            fetch_report(
                "https://user:password@magi.example",
                DECISION_ID,
                1,
                "private-test-token",
            )

        oversized_headers = {"Content-Length": "1000001"}
        with patch(
            "magi.clients.report_cli.urlopen",
            return_value=FakeResponse(b"{}", oversized_headers),
        ):
            with self.assertRaisesRegex(ReportClientError, "too large"):
                fetch_report(
                    "https://magi.example",
                    DECISION_ID,
                    1,
                    "private-test-token",
                )

    def test_http_error_is_sanitized_and_never_echoes_token(self) -> None:
        headers = Message()
        headers["Content-Type"] = "application/json"
        body = json.dumps(
            {
                "error": {
                    "code": "report_not_ready",
                    "message": "The decision does not have a final report yet.",
                }
            }
        ).encode()
        from urllib.error import HTTPError

        error = HTTPError("https://magi.example", 409, "private detail", headers, BytesIO(body))
        with patch("magi.clients.report_cli.urlopen", side_effect=error):
            with self.assertRaisesRegex(ReportClientError, "report_not_ready") as raised:
                fetch_report(
                    "https://magi.example",
                    DECISION_ID,
                    1,
                    "private-test-token",
                )

        self.assertNotIn("private-test-token", str(raised.exception))
        self.assertNotIn("private detail", str(raised.exception))

    def test_terminal_view_preserves_dissent_and_removes_control_characters(self) -> None:
        report = self.report.model_copy(
            update={
                "majority_rationale": ("Evidence\x1b[31m remains bounded.",),
            }
        )

        plain = DecisionReportTerminalRenderer().render(report, color=False)
        colored = DecisionReportTerminalRenderer().render(report, color=True)

        self.assertNotIn("\x1b", plain)
        self.assertIn("Evidence [31m remains bounded.", plain)
        self.assertIn("MINORITY REPORT", plain)
        self.assertIn("balthasar rationale", plain)
        self.assertIn("REVIEW AUDIT", plain)
        self.assertIn("\x1b[36;1m", colored)


if __name__ == "__main__":
    unittest.main()
