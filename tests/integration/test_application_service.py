"""Application service integration over real LangGraph checkpoints."""

from __future__ import annotations

import hashlib
import unittest
from collections.abc import Callable
from datetime import datetime, timezone
from uuid import UUID, uuid4

from langgraph.checkpoint.memory import InMemorySaver

from magi.agents import (
    CoordinatorExecutionError,
    NormalizationRequest,
    ScriptedPerspectiveRunner,
)
from magi.application import (
    DecisionApplicationService,
    DecisionPreparationFailed,
    DecisionPreparationRequest,
    EvidenceRetrievalError,
    EvidenceSourceRequest,
    RetrievedEvidence,
    DecisionWorkflowConflict,
    DecisionWorkflowNotFound,
    SuppliedEvidence,
)
from magi.domain import (
    AgentName,
    ArbitrationStatus,
    DataClassification,
    DecisionCase,
    DecisionState,
    VerificationStatus,
)
from magi.audit import DecisionAuditService, InMemoryAuditLedger
from magi.orchestration import build_langgraph_workflow
from tests.fixtures.factories import make_ballot, make_case, make_snapshot


class FakeNormalizer:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.requests: list[NormalizationRequest] = []

    async def normalize(self, request: NormalizationRequest) -> DecisionCase:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return make_case(confirmed=False).model_copy(
            update={
                "decision_id": request.decision_id,
                "version": request.version,
                "raw_question": request.raw_question,
                "data_classification": request.data_classification,
                "risk_level": request.minimum_risk_level,
            }
        )


class FakeEvidenceGateway:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.requests: list[EvidenceSourceRequest] = []

    async def retrieve(self, request: EvidenceSourceRequest) -> RetrievedEvidence:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        excerpt = "Retrieved release status: ready."
        return RetrievedEvidence(
            source_type="retrieved_https",
            source=str(request.url),
            captured_at=datetime(2026, 8, 18, 15, 45, tzinfo=timezone.utc),
            excerpt=excerpt,
            content_hash=hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
            classification=request.classification,
        )


class DecisionApplicationServiceTests(unittest.IsolatedAsyncioTestCase):
    def build_service(
        self,
        saver: InMemorySaver | None = None,
        *,
        auditor: DecisionAuditService | None = None,
    ) -> tuple[DecisionApplicationService, ScriptedPerspectiveRunner, InMemorySaver]:
        case = make_case(confirmed=False)
        runner = ScriptedPerspectiveRunner(
            {agent: make_ballot(case, agent, "release") for agent in AgentName}
        )
        selected_saver = saver or InMemorySaver()
        graph = build_langgraph_workflow(runner, checkpointer=selected_saver)
        return DecisionApplicationService(
            graph, auditor=auditor
        ), runner, selected_saver

    def build_preparation_service(
        self,
        normalizer: FakeNormalizer,
        *,
        clock: Callable[[], datetime] | None = None,
        evidence_gateway: FakeEvidenceGateway | None = None,
    ) -> tuple[DecisionApplicationService, ScriptedPerspectiveRunner]:
        case = make_case(confirmed=False)
        runner = ScriptedPerspectiveRunner(
            {agent: make_ballot(case, agent, "release") for agent in AgentName}
        )
        graph = build_langgraph_workflow(runner, checkpointer=InMemorySaver())
        if clock is None:
            return DecisionApplicationService(
                graph,
                normalizer=normalizer,
                evidence_gateway=evidence_gateway,
            ), runner
        return (
            DecisionApplicationService(
                graph,
                normalizer=normalizer,
                evidence_gateway=evidence_gateway,
                clock=clock,
            ),
            runner,
        )

    async def test_new_service_instance_reads_and_resumes_confirmation(self) -> None:
        case = make_case(confirmed=False)
        snapshot = make_snapshot(case)
        first_service, _, saver = self.build_service()

        waiting = await first_service.wait_for_confirmation(case, snapshot)
        self.assertEqual(waiting.state, DecisionState.WAITING_FOR_USER)
        self.assertEqual(waiting.ballots, ())

        second_service, second_runner, _ = self.build_service(saver)
        restored = await second_service.get(case.decision_id, case.version)
        self.assertEqual(restored, waiting)

        ready = await second_service.confirm(
            case.decision_id,
            case.version,
            confirmed_at=datetime(2026, 8, 18, 14, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(ready.state, DecisionState.EVIDENCE_READY)
        self.assertTrue(ready.awaiting_run)
        self.assertEqual(ready.available_actions, ("run", "cancel"))
        self.assertEqual(second_runner.calls, [])

        third_service, third_runner, _ = self.build_service(saver)
        completed = await third_service.run(case.decision_id, case.version)

        self.assertEqual(completed.state, DecisionState.COMPLETED)
        self.assertEqual(completed.result.status, ArbitrationStatus.CONSENSUS)
        self.assertEqual(completed.result.winning_option, "release")
        self.assertEqual(len(completed.ballots), 3)
        self.assertEqual(len(second_runner.calls), 0)
        self.assertEqual(len(third_runner.calls), 3)

        repeated = await third_service.confirm_and_run(
            case.decision_id,
            case.version,
            confirmed_at=datetime(2026, 8, 18, 14, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(repeated, completed)
        self.assertEqual(len(third_runner.calls), 3)

        with self.assertRaisesRegex(DecisionWorkflowConflict, "terminal"):
            await third_service.cancel(
                case.decision_id,
                case.version,
                reason="Too late to cancel.",
            )

    async def test_cancel_stops_before_any_perspective_call(self) -> None:
        case = make_case(confirmed=False)
        service, runner, _ = self.build_service()
        await service.wait_for_confirmation(case, make_snapshot(case))

        cancelled = await service.cancel(
            case.decision_id,
            case.version,
            reason="The options need revision.",
        )

        self.assertEqual(cancelled.state, DecisionState.CANCELLED)
        self.assertTrue(cancelled.terminal)
        self.assertEqual(cancelled.ballots, ())
        self.assertEqual(runner.calls, [])

    async def test_completed_workflow_is_reconstructable_from_audit(self) -> None:
        ledger = InMemoryAuditLedger()
        auditor = DecisionAuditService(ledger)
        case = make_case(confirmed=False)
        service, _, _ = self.build_service(auditor=auditor)
        await service.wait_for_confirmation(case, make_snapshot(case))
        await service.confirm(
            case.decision_id,
            case.version,
            confirmed_at=datetime(2026, 8, 18, 14, 0, tzinfo=timezone.utc),
        )
        completed = await service.run(case.decision_id, case.version)

        reconstructed = await auditor.reconstruct_report(
            case.decision_id, case.version
        )
        records = await ledger.records(case.decision_id, case.version)

        self.assertEqual(reconstructed, completed.report)
        self.assertEqual(len(records), 3)
        self.assertEqual(tuple(record.sequence for record in records), (1, 2, 3))

    async def test_cancel_after_confirmation_stops_before_run(self) -> None:
        case = make_case(confirmed=False)
        service, runner, _ = self.build_service()
        await service.wait_for_confirmation(case, make_snapshot(case))
        ready = await service.confirm(
            case.decision_id,
            case.version,
            confirmed_at=datetime(2026, 8, 18, 14, 30, tzinfo=timezone.utc),
        )
        self.assertTrue(ready.awaiting_run)

        cancelled = await service.cancel(
            case.decision_id,
            case.version,
            reason="Do not start voting.",
        )

        self.assertEqual(cancelled.state, DecisionState.CANCELLED)
        self.assertEqual(runner.calls, [])

    async def test_wait_is_idempotent_but_rejects_different_case(self) -> None:
        case = make_case(confirmed=False)
        service, _, _ = self.build_service()
        first = await service.wait_for_confirmation(case, make_snapshot(case))
        repeated = await service.wait_for_confirmation(case, make_snapshot(case))
        self.assertEqual(repeated, first)

        changed = case.model_copy(update={"title": "A different prepared case"})
        with self.assertRaisesRegex(DecisionWorkflowConflict, "different"):
            await service.wait_for_confirmation(changed, make_snapshot(changed))

        changed_snapshot = make_snapshot(case).model_copy(
            update={"snapshot_id": uuid4()}
        )
        with self.assertRaisesRegex(DecisionWorkflowConflict, "different"):
            await service.wait_for_confirmation(case, changed_snapshot)

    async def test_prepare_seals_identity_evidence_and_waits_for_confirmation(self) -> None:
        decision_id = UUID("33333333-3333-4333-8333-333333333333")
        prepared_at = datetime(2026, 8, 18, 16, 0, tzinfo=timezone.utc)
        captured_at = datetime(2026, 8, 18, 15, 30, tzinfo=timezone.utc)
        normalizer = FakeNormalizer()
        service, runner = self.build_preparation_service(
            normalizer,
            clock=lambda: prepared_at,
        )

        view = await service.prepare(
            DecisionPreparationRequest(
                decision_id=decision_id,
                raw_question="Should this release be deployed?",
                data_classification=DataClassification.SENSITIVE,
                evidence=(
                    SuppliedEvidence(
                        source_type="user_note",
                        source="release checklist",
                        captured_at=captured_at,
                        excerpt="All pre-release checks passed.",
                        classification=DataClassification.INTERNAL,
                    ),
                ),
            )
        )

        self.assertEqual(view.decision_id, decision_id)
        self.assertTrue(view.awaiting_confirmation)
        self.assertEqual(view.case.raw_question, "Should this release be deployed?")
        self.assertEqual(view.case.data_classification, DataClassification.SENSITIVE)
        self.assertEqual(view.evidence[0].evidence_id, "E-001")
        self.assertEqual(
            view.evidence[0].content_hash,
            hashlib.sha256(b"All pre-release checks passed.").hexdigest(),
        )
        self.assertEqual(
            view.evidence[0].verification_status,
            VerificationStatus.USER_ASSERTED,
        )
        self.assertEqual(normalizer.requests[0].decision_id, decision_id)
        self.assertEqual(runner.calls, [])

        repeated = await service.prepare(
            DecisionPreparationRequest(
                decision_id=decision_id,
                raw_question="Should this release be deployed?",
                data_classification=DataClassification.SENSITIVE,
                evidence=(
                    SuppliedEvidence(
                        source_type="user_note",
                        source="release checklist",
                        captured_at=captured_at,
                        excerpt="All pre-release checks passed.",
                        classification=DataClassification.INTERNAL,
                    ),
                ),
            )
        )
        self.assertEqual(repeated, view)
        self.assertEqual(len(normalizer.requests), 1)

        with self.assertRaisesRegex(DecisionWorkflowConflict, "different"):
            await service.prepare(
                DecisionPreparationRequest(
                    decision_id=decision_id,
                    raw_question="A changed question must conflict.",
                )
            )
        self.assertEqual(len(normalizer.requests), 1)

    async def test_prepare_freezes_verified_retrieval_once(self) -> None:
        gateway = FakeEvidenceGateway()
        normalizer = FakeNormalizer()
        service, _ = self.build_preparation_service(
            normalizer,
            evidence_gateway=gateway,
        )
        request = DecisionPreparationRequest(
            decision_id=uuid4(),
            raw_question="Should we deploy?",
            evidence_sources=(
                EvidenceSourceRequest(url="https://evidence.example/status"),
            ),
        )

        first = await service.prepare(request)
        repeated = await service.prepare(request)

        self.assertEqual(first, repeated)
        self.assertEqual(len(gateway.requests), 1)
        self.assertEqual(first.evidence[0].evidence_id, "E-001")
        self.assertEqual(
            first.evidence[0].verification_status,
            VerificationStatus.VERIFIED,
        )
        self.assertEqual(
            first.evidence[0].content_hash,
            hashlib.sha256(first.evidence[0].excerpt.encode("utf-8")).hexdigest(),
        )

    async def test_prepare_fails_closed_and_sanitizes_retrieval_error(self) -> None:
        request = DecisionPreparationRequest(
            decision_id=uuid4(),
            raw_question="Should we deploy?",
            evidence_sources=(
                EvidenceSourceRequest(url="https://evidence.example/status"),
            ),
        )
        missing, _ = self.build_preparation_service(FakeNormalizer())
        with self.assertRaisesRegex(DecisionPreparationFailed, "not configured"):
            await missing.prepare(request)

        gateway = FakeEvidenceGateway(
            EvidenceRetrievalError("private upstream response and secret URL")
        )
        configured, _ = self.build_preparation_service(
            FakeNormalizer(), evidence_gateway=gateway
        )
        with self.assertRaises(DecisionPreparationFailed) as raised:
            await configured.prepare(request.model_copy(update={"decision_id": uuid4()}))
        self.assertEqual(str(raised.exception), "evidence retrieval failed")
        self.assertNotIn("secret URL", str(raised.exception))

    async def test_prepare_sanitizes_coordinator_failure(self) -> None:
        normalizer = FakeNormalizer(
            CoordinatorExecutionError("secret model-provider response")
        )
        service, _ = self.build_preparation_service(normalizer)

        with self.assertRaises(DecisionPreparationFailed) as raised:
            await service.prepare(
                DecisionPreparationRequest(
                    decision_id=uuid4(),
                    raw_question="Should we deploy?",
                )
            )

        self.assertNotIn("secret model-provider response", str(raised.exception))

    async def test_missing_workflow_is_reported_without_creating_state(self) -> None:
        case = make_case(confirmed=False)
        service, _, _ = self.build_service()

        with self.assertRaises(DecisionWorkflowNotFound):
            await service.get(case.decision_id, case.version)


if __name__ == "__main__":
    unittest.main()
