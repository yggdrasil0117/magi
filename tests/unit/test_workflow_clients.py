from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
from uuid import UUID

from magi.clients import tui, workflow_cli


class WorkflowCliTests(unittest.TestCase):
    def test_inbox_emits_stable_sorted_json(self) -> None:
        output = io.StringIO()
        with patch.object(workflow_cli, "request_json", return_value={"z": 1, "a": 2}):
            with redirect_stdout(output):
                code = workflow_cli.main(["inbox", "--limit", "10"])
        self.assertEqual(code, workflow_cli.EXIT_OK)
        self.assertEqual(json.loads(output.getvalue()), {"a": 2, "z": 1})

    def test_create_uses_async_public_contract(self) -> None:
        with patch.object(workflow_cli, "request_json", return_value={}) as request:
            with redirect_stdout(io.StringIO()):
                workflow_cli.main(["create", "Ship now?", "--risk", "high"])
        request.assert_called_once()
        args, kwargs = request.call_args
        self.assertEqual(args[:2], ("POST", "/v1/decisions"))
        self.assertTrue(kwargs["async_preference"])
        self.assertEqual(kwargs["body"]["minimum_risk_level"], "high")

    def test_terminal_shell_is_keyboard_driven_and_sanitizes_failures(self) -> None:
        commands = iter(["inbox", "quit"])
        output: list[str] = []
        with patch.object(tui, "request_json", side_effect=RuntimeError("secret")):
            tui.run(lambda _: next(commands), output.append)
        self.assertTrue(any("Request failed" in line for line in output))
        self.assertNotIn("secret", repr(output))

    def test_audit_and_redaction_use_public_contracts(self) -> None:
        decision_id = UUID("11111111-1111-4111-8111-111111111111")
        record_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
        with patch.object(workflow_cli, "request_json", return_value={}) as request:
            with redirect_stdout(io.StringIO()):
                workflow_cli.main(["audit", str(decision_id), "--version", "2"])
                workflow_cli.main([
                    "redact", str(decision_id), str(record_id),
                    "/case/raw_question", "--reason", "Privacy request",
                    "--idempotency-key", "audit-command-1",
                ])

        audit_call, redact_call = request.call_args_list
        self.assertEqual(
            audit_call.args,
            ("GET", f"/v1/decisions/{decision_id}/audit?version=2"),
        )
        self.assertEqual(
            redact_call.args,
            ("POST", f"/v1/decisions/{decision_id}/audit/redactions"),
        )
        self.assertEqual(
            redact_call.kwargs["body"]["field_paths"],
            ["/case/raw_question"],
        )
        self.assertEqual(redact_call.kwargs["idempotency_key"], "audit-command-1")

    def test_terminal_audit_command_renders_json(self) -> None:
        decision_id = "11111111-1111-4111-8111-111111111111"
        commands = iter([f"audit {decision_id} 2", "quit"])
        output: list[str] = []
        with patch.object(
            tui,
            "request_json",
            return_value={"integrity_status": "verified"},
        ) as request:
            tui.run(lambda _: next(commands), output.append)

        request.assert_called_once_with(
            "GET", f"/v1/decisions/{decision_id}/audit?version=2"
        )
        self.assertTrue(any("verified" in line for line in output))

    def test_evaluation_commands_use_server_authoritative_contracts(self) -> None:
        decision_id = UUID("11111111-1111-4111-8111-111111111111")
        with patch.object(workflow_cli, "request_json", return_value={}) as request:
            with redirect_stdout(io.StringIO()):
                workflow_cli.main([
                    "evaluations", str(decision_id),
                    "--version", "2", "--limit", "8",
                ])
                workflow_cli.main(["evaluate", str(decision_id), "--version", "2"])

        history_call, run_call = request.call_args_list
        self.assertEqual(
            history_call.args,
            ("GET", f"/v1/decisions/{decision_id}/evaluations?version=2&limit=8"),
        )
        self.assertEqual(
            run_call.args,
            ("POST", f"/v1/decisions/{decision_id}/evaluations"),
        )
        self.assertEqual(run_call.kwargs["body"], {"version": 2})

    def test_terminal_evaluation_dashboard_uses_public_contracts(self) -> None:
        decision_id = "11111111-1111-4111-8111-111111111111"
        evaluation = {
            "overall_status": "warn",
            "citation_validity": {"status": "pass", "score": 1.0},
            "persona_differentiation": {"status": "warn", "score": 0.42},
            "arbitration_consistency": {"status": "pass", "consistent": True},
            "latency": {"status": "pass", "p95_latency_ms": 1200},
            "cost": {"status": "not_measured", "total_cost_microusd": None},
        }
        record = {
            "decision_id": decision_id,
            "decision_version": 2,
            "sequence": 101,
            "evaluation": evaluation,
        }
        history = {
            "decision_id": decision_id,
            "decision_version": 2,
            "total_count": 101,
            "evaluations": [record],
            "trend": {"pass_count": 0, "warn_count": 1, "fail_count": 0},
        }
        commands = iter(
            [f"evaluations {decision_id} 2 8", f"evaluate {decision_id} 2", "quit"]
        )
        output: list[str] = []
        with patch.object(tui, "request_json", side_effect=[history, record]) as request:
            tui.run(lambda _: next(commands), output.append)

        history_call, run_call = request.call_args_list
        self.assertEqual(
            history_call.args,
            ("GET", f"/v1/decisions/{decision_id}/evaluations?version=2&limit=8"),
        )
        self.assertEqual(
            run_call.args,
            ("POST", f"/v1/decisions/{decision_id}/evaluations"),
        )
        self.assertEqual(run_call.kwargs["body"], {"version": 2})
        dashboard = "\n".join(output)
        self.assertIn("QUALITY EVALUATION", dashboard)
        self.assertIn("E-01 CITATION", dashboard)
        self.assertIn("E-05 COST", dashboard)
        self.assertIn("NOT MEASURED", dashboard)
        self.assertIn("#101 WARN", dashboard)


if __name__ == "__main__":
    unittest.main()
