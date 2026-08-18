"""End-to-end graph test for the model runner with no provider calls."""

from __future__ import annotations

import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path

from magi.agents import (
    BallotDraft,
    LangChainPerspectiveRunner,
    PerspectiveSkillLoader,
)
from magi.domain import (
    AgentName,
    ArbitrationResult,
    ArbitrationStatus,
    EvidenceQuality,
    Stance,
)
from magi.orchestration import build_langgraph_workflow
from tests.fixtures.factories import make_case, make_snapshot

HAS_LANGGRAPH = importlib.util.find_spec("langgraph") is not None


class SequencedStructuredModel:
    def __init__(self, outputs: tuple[BallotDraft, ...]) -> None:
        self.outputs = list(outputs)
        self.inputs: list[object] = []

    async def ainvoke(self, input: object) -> object:
        self.inputs.append(input)
        return self.outputs.pop(0)


def draft(option: str) -> BallotDraft:
    return BallotDraft(
        selected_option=option,
        stance=Stance.SUPPORT,
        confidence=0.7,
        evidence_quality=EvidenceQuality.MEDIUM,
        rationale_summary=("Structured model rationale.",),
        evidence_refs=("E-001",),
        assumptions=(),
        risks=(),
        missing_information=(),
        constraint_claims=(),
        changed_from_previous=False,
    )


@unittest.skipUnless(HAS_LANGGRAPH, "LangGraph dependency is not installed")
class ModelRunnerWorkflowIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_runner_completes_parallel_review_graph(self) -> None:
        from langgraph.types import Command

        case = make_case(confirmed=False)
        snapshot = make_snapshot(case)
        choices = {
            AgentName.MELCHIOR: "limited",
            AgentName.BALTHASAR: "limited",
            AgentName.CASPER: "delay",
        }
        models = {
            agent: SequencedStructuredModel((draft(option), draft(option)))
            for agent, option in choices.items()
        }
        skills_root = Path(__file__).resolve().parents[2] / "skills"
        runner = LangChainPerspectiveRunner(models, PerspectiveSkillLoader(skills_root))
        graph = build_langgraph_workflow(runner)
        config = {
            "configurable": {
                "thread_id": f"model:{case.decision_id}:{case.version}",
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
                        11,
                        0,
                        tzinfo=timezone.utc,
                    ).isoformat(),
                }
            ),
            config=config,
        )
        self.assertIn("__interrupt__", ready)
        completed = await graph.ainvoke(
            Command(resume={"start": True}),
            config=config,
        )

        result = ArbitrationResult.model_validate(completed["result"])
        self.assertEqual(result.status, ArbitrationStatus.MAJORITY)
        self.assertEqual(result.winning_option, "limited")
        self.assertEqual(len(completed["first_ballots"]), 3)
        self.assertEqual(len(completed["review_ballots"]), 3)
        for model in models.values():
            self.assertEqual(len(model.inputs), 2)
            self.assertNotIn('"peer_summaries"', model.inputs[0][1][1])
            self.assertIn('"peer_summaries"', model.inputs[1][1][1])


if __name__ == "__main__":
    unittest.main()
