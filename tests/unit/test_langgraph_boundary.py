"""Dependency boundary tests for the optional LangGraph runtime."""

import importlib.util
import unittest

from magi.agents import ScriptedPerspectiveRunner
from magi.domain import AgentName
from magi.orchestration import LangGraphUnavailable, build_langgraph_workflow
from tests.fixtures.factories import make_ballot, make_case


class LangGraphBoundaryTests(unittest.TestCase):
    def test_builder_reports_missing_runtime_clearly(self) -> None:
        if importlib.util.find_spec("langgraph") is not None:
            self.skipTest("LangGraph is installed in this environment")
        case = make_case(confirmed=False)
        runner = ScriptedPerspectiveRunner(
            {
                agent: make_ballot(case, agent, "release")
                for agent in AgentName
            }
        )
        with self.assertRaisesRegex(LangGraphUnavailable, "not installed"):
            build_langgraph_workflow(runner)


if __name__ == "__main__":
    unittest.main()

