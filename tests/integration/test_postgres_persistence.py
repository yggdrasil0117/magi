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
from magi.application import DecisionView, DecisionViewProjector, OperationKind
from magi.audit import DecisionAuditService
from magi.domain import (
    AgentName,
    ArbitrationResult,
    ArbitrationStatus,
    DataClassification,
)
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
        command_key = "integration-" + uuid4().hex
        command_fingerprint = uuid4().hex + uuid4().hex
        operation_key = "operation-" + uuid4().hex
        operation_fingerprint = uuid4().hex + uuid4().hex
        command_calls = 0
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
            waiting_view = DecisionViewProjector().project(interrupted)

            async def persist_command_view() -> DecisionView:
                nonlocal command_calls
                command_calls += 1
                return waiting_view

            stored_command_view = await first_runtime.command_idempotency_store.execute(
                principal="integration-user",
                idempotency_key=command_key,
                fingerprint=command_fingerprint,
                operation=persist_command_view,
            )
            accepted_operation = await first_runtime.operation_store.accept(
                principal="integration-user",
                idempotency_key=operation_key,
                fingerprint=operation_fingerprint,
                kind=OperationKind.RUN_DECISION,
                decision_id=case.decision_id,
                decision_version=case.version,
                classification=DataClassification.INTERNAL,
                request_payload={"version": case.version},
                accepted_at=invocation_time,
            )

        async with PostgresPersistenceRuntime(POSTGRES_DSN) as second_runtime:
            async with second_runtime.invocation_ledger.guard(idempotency_key):
                stored_ballot = await second_runtime.invocation_ledger.get_ballot(
                    idempotency_key
                )

            async def reject_duplicate_execution() -> DecisionView:
                raise AssertionError("persisted command must not execute again")

            reused_command_view = (
                await second_runtime.command_idempotency_store.execute(
                    principal="integration-user",
                    idempotency_key=command_key,
                    fingerprint=command_fingerprint,
                    operation=reject_duplicate_execution,
                )
            )
            reused_operation = await second_runtime.operation_store.accept(
                principal="integration-user",
                idempotency_key=operation_key,
                fingerprint=operation_fingerprint,
                kind=OperationKind.RUN_DECISION,
                decision_id=case.decision_id,
                decision_version=case.version,
                classification=DataClassification.INTERNAL,
                request_payload={"version": case.version},
                accepted_at=invocation_time,
            )
            operation_events = await second_runtime.operation_store.events(
                principal="integration-user",
                operation_id=accepted_operation.operation_id,
            )
            graph = build_langgraph_workflow(
                runner,
                checkpointer=second_runtime.checkpointer,
            )
            ready = await graph.ainvoke(
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
            self.assertIn("__interrupt__", ready)

        async with PostgresPersistenceRuntime(POSTGRES_DSN) as third_runtime:
            graph = build_langgraph_workflow(
                runner,
                checkpointer=third_runtime.checkpointer,
            )
            completed = await graph.ainvoke(
                Command(resume={"start": True}),
                config=config,
            )
            await DecisionAuditService(third_runtime.audit_ledger).capture(
                completed,
                occurred_at=invocation_time,
            )

        async with PostgresPersistenceRuntime(POSTGRES_DSN) as fourth_runtime:
            reconstructed_report = await DecisionAuditService(
                fourth_runtime.audit_ledger
            ).reconstruct_report(case.decision_id, case.version)

        result = ArbitrationResult.model_validate(completed["result"])
        self.assertEqual(stored_ballot, canonical_ballot)
        self.assertEqual(stored_command_view, waiting_view)
        self.assertEqual(reused_command_view, waiting_view)
        self.assertEqual(command_calls, 1)
        self.assertEqual(reused_operation, accepted_operation)
        self.assertIsNotNone(operation_events)
        assert operation_events is not None
        self.assertEqual(len(operation_events.events), 1)
        self.assertEqual(operation_events.events[0].message_code, "operation_accepted")
        self.assertEqual(result.status, ArbitrationStatus.CONSENSUS)
        self.assertEqual(result.winning_option, "release")
        self.assertEqual(reconstructed_report.selected_option, "release")


if __name__ == "__main__":
    unittest.main()
