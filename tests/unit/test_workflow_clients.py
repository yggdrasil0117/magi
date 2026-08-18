from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
