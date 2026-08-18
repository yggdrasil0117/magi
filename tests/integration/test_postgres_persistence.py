"""Optional real PostgreSQL checkpoint and invocation-ledger integration test."""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from uuid import uuid4

from magi.agents import (
    InvocationStatus,
    ModelInvocationRecord,
    ModelTokenUsage,
    ScriptedPerspectiveRunner,
)
from magi.domain import AgentName, ArbitrationResult, ArbitrationStatus
from magi.infrastructure import PostgresPersistenceRuntime, decision_thread_id
from magi.orchestration import build_langgraph_workflow
from tests.fixtures.factories import make_ballot, make_case, make_snapshot

POSTGRES_DSN = os.getenv("MAGI_TEST_POSTGRES_DSN")


@unittest.skipUnless(POSTGRES_DSN, "MAGI_TEST_POSTGRES_DSN is not configured")
class PostgresPersistenceIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_ledger_and_interrupt_resume_after_runtime_restart(self) -> None:
        from langgraph.types import Command

        case = make_case(confirmed=False)
        snapshot = make_snapshot(case)
        runner = ScriptedPerspectiveRunner(
            {agent: make_ballot(case, agent, "release") for agent in AgentName}
        )
        canonical_ballot = make_ballot(
            case,
            AgentName.MELCHIOR,
            "release",
        ).model_dump(mode="json")
        idempotency_key = uuid4().hex + uuid4().hex
        prompt_digest = uuid4().hex + uuid4().hex
        invocation_time = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
        invocation = ModelInvocationRecord(
            idempotency_key=idempotency_key,
            prompt_digest=prompt_digest,
            decision_id=case.decision_id,
            decision_version=case.version,
            agent=AgentName.MELCHIOR,
            round=1,
            attempt=1,
            status=InvocationStatus.SUCCEEDED,
            model_name="integration-test-model",
            started_at=invocation_time,
            completed_at=invocation_time,
            latency_ms=0,
            usage=ModelTokenUsage(),
        )
        thread_id = decision_thread_id(f"{case.decision_id}-{uuid4()}", case.version)
        config = {"configurable": {"thread_id": thread_id}}
        initial_state = {
            "case": case.model_dump(mode="json"),
            "snapshot": snapshot.model_dump(mode="json"),
            "constraint_validations": [],
            "first_ballots": [],
            "review_ballots": [],
        }

        async with PostgresPersistenceRuntime(POSTGRES_DSN) as first_runtime:
            async with first_runtime.invocation_ledger.guard(idempotency_key):
                await first_runtime.invocation_ledger.append(
                    invocation,
                    canonical_ballot,
                )
            graph = build_langgraph_workflow(
                runner,
                checkpointer=first_runtime.checkpointer,
            )
            interrupted = await graph.ainvoke(initial_state, config=config)
            self.assertIn("__interrupt__", interrupted)

        async with PostgresPersistenceRuntime(POSTGRES_DSN) as second_runtime:
            async with second_runtime.invocation_ledger.guard(idempotency_key):
                stored_ballot = await second_runtime.invocation_ledger.get_ballot(
                    idempotency_key
                )
            graph = build_langgraph_workflow(
                runner,
                checkpointer=second_runtime.checkpointer,
            )
            completed = await graph.ainvoke(
                Command(
                    resume={
                        "confirmed": True,
                        "confirmed_at": datetime(
                            2026,
                            8,
                            18,
                            13,
                            0,
                            tzinfo=timezone.utc,
                        ).isoformat(),
                    }
                ),
                config=config,
            )

        result = ArbitrationResult.model_validate(completed["result"])
        self.assertEqual(stored_ballot, canonical_ballot)
        self.assertEqual(result.status, ArbitrationStatus.CONSENSUS)
        self.assertEqual(result.winning_option, "release")


if __name__ == "__main__":
    unittest.main()
