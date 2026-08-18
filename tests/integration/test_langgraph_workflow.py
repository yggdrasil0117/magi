"""Executable LangGraph smoke test, enabled when the dependency is installed."""

from __future__ import annotations

import importlib.util
import unittest
from datetime import datetime, timezone

from magi.agents import ScriptedPerspectiveRunner
from magi.domain import AgentName, ArbitrationResult, ArbitrationStatus
from magi.orchestration import build_langgraph_workflow
from tests.fixtures.factories import make_ballot, make_case, make_snapshot

HAS_LANGGRAPH = importlib.util.find_spec("langgraph") is not None


@unittest.skipUnless(HAS_LANGGRAPH, "LangGraph dependency is not installed")
class LangGraphWorkflowIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_interrupt_resume_parallel_vote_and_arbitration(self) -> None:
        from langgraph.types import Command

        case = make_case(confirmed=False)
        snapshot = make_snapshot(case)
        runner = ScriptedPerspectiveRunner(
            {
                agent: make_ballot(case, agent, "release")
                for agent in AgentName
            }
        )
        graph = build_langgraph_workflow(runner)
        config = {
            "configurable": {
                "thread_id": f"{case.decision_id}:{case.version}",
            }
        }
        initial_state = {
            "case": case.model_dump(mode="json"),
            "snapshot": snapshot.model_dump(mode="json"),
            "constraint_validations": [],
            "first_ballots": [],
            "review_ballots": [],
        }

        interrupted = await graph.ainvoke(initial_state, config=config)
        self.assertIn("__interrupt__", interrupted)

        ready = await graph.ainvoke(
            Command(
                resume={
                    "confirmed": True,
                    "confirmed_at": datetime(
                        2026,
                        8,
                        18,
                        10,
                        0,
                        tzinfo=timezone.utc,
                    ).isoformat(),
                }
            ),
            config=config,
        )
        self.assertIn("__interrupt__", ready)
        self.assertEqual(ready["phase"], "evidence_ready")
        self.assertEqual(runner.calls, [])

        completed = await graph.ainvoke(
            Command(resume={"start": True}),
            config=config,
        )
        result = ArbitrationResult.model_validate(completed["result"])
        self.assertEqual(result.status, ArbitrationStatus.CONSENSUS)
        self.assertEqual(result.winning_option, "release")
        self.assertEqual(len(completed["first_ballots"]), 3)
        self.assertEqual(
            {agent for phase, agent in runner.calls if phase == "first"},
            set(AgentName),
        )


if __name__ == "__main__":
    unittest.main()
