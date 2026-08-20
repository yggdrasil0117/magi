from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from uuid import UUID

from magi.agents.invocation import (
    InvocationStatus,
    ModelInvocationRecord,
    ModelTokenUsage,
)
from magi.arbitration import arbitrate
from magi.audit import AuditDecisionState
from magi.clients import evaluation_cli
from magi.domain import AgentName, ArbitrationResult, ArbitrationStatus, ProtocolViolation
from magi.evaluation import (
    DecisionEvaluator,
    EvaluationBundle,
    DecisionEvaluationService,
    EvaluationThresholds,
    InMemoryEvaluationStore,
    MetricStatus,
    ModelPricing,
)
from tests.fixtures.factories import TIMESTAMP, make_ballot, make_case, make_snapshot


def make_bundle(*, identical_personas: bool = False) -> EvaluationBundle:
    case = make_case()
    snapshot = make_snapshot(case)
    ballots = tuple(
        make_ballot(
            case,
            agent,
            "release",
            rationale_summary=(
                ("shared rationale",)
                if identical_personas
                else (f"{agent.value} independent perspective",)
            ),
        )
        for agent in AgentName
    )
    result = arbitrate(case, snapshot, ballots)
    invocations = tuple(
        ModelInvocationRecord(
            invocation_id=UUID(f"00000000-0000-4000-8000-00000000000{index}"),
            idempotency_key=f"{index}" * 64,
            prompt_digest="a" * 64,
            decision_id=case.decision_id,
            decision_version=case.version,
            agent=agent,
            round=1,
            attempt=1,
            status=InvocationStatus.SUCCEEDED,
            model_name="test-model",
            started_at=TIMESTAMP,
            completed_at=TIMESTAMP,
            latency_ms=100 + index * 10,
            usage=ModelTokenUsage(
                input_tokens=100,
                output_tokens=50,
                total_tokens=150,
            ),
        )
        for index, agent in enumerate(AgentName, start=1)
    )
    return EvaluationBundle(
        case=case,
        snapshot=snapshot,
        ballots=ballots,
        result=result,
        invocations=invocations,
        pricing=(
            ModelPricing(
                model_name="test-model",
                input_microusd_per_million_tokens=1_000_000,
                output_microusd_per_million_tokens=2_000_000,
            ),
        ),
        thresholds=EvaluationThresholds(
            minimum_persona_distance=0.5,
            maximum_p95_latency_ms=150,
            maximum_cost_microusd=1_000,
        ),
    )


class DecisionEvaluatorTests(unittest.TestCase):
    def test_versioned_baseline_bundle_is_reproducible(self) -> None:
        path = Path("tests/evals/v1/consensus-baseline.json")
        first = evaluation_cli.evaluate_path(path)
        second = evaluation_cli.evaluate_path(path)

        self.assertEqual(first, second)
        self.assertEqual(first["overall_status"], "pass")

    def test_complete_bundle_passes_all_five_metrics(self) -> None:
        evaluation = DecisionEvaluator().evaluate(make_bundle())

        self.assertEqual(evaluation.overall_status, MetricStatus.PASS)
        self.assertEqual(evaluation.citation_validity.score, 1)
        self.assertEqual(evaluation.persona_differentiation.score, 1)
        self.assertTrue(evaluation.arbitration_consistency.consistent)
        self.assertEqual(evaluation.latency.p95_latency_ms, 130)
        self.assertEqual(evaluation.cost.total_cost_microusd, 600)

    def test_identical_personas_fail_differentiation_gate(self) -> None:
        evaluation = DecisionEvaluator().evaluate(make_bundle(identical_personas=True))

        self.assertEqual(evaluation.overall_status, MetricStatus.FAIL)
        self.assertEqual(evaluation.persona_differentiation.status, MetricStatus.FAIL)
        self.assertEqual(len(evaluation.persona_differentiation.identical_pairs), 3)

    def test_missing_operational_samples_are_explicitly_not_measured(self) -> None:
        bundle = make_bundle().model_copy(update={"invocations": (), "pricing": ()})
        evaluation = DecisionEvaluator().evaluate(bundle)

        self.assertEqual(evaluation.overall_status, MetricStatus.WARN)
        self.assertEqual(evaluation.latency.status, MetricStatus.NOT_MEASURED)
        self.assertEqual(evaluation.cost.status, MetricStatus.NOT_MEASURED)

    def test_cost_preserves_an_explicit_pricing_snapshot_digest(self) -> None:
        bundle = make_bundle()
        first = DecisionEvaluator().evaluate(bundle)
        changed_rate = bundle.pricing[0].model_copy(
            update={"input_microusd_per_million_tokens": 999_999}
        )
        second = DecisionEvaluator().evaluate(
            bundle.model_copy(update={"pricing": (changed_rate,)})
        )

        self.assertIsNotNone(first.cost.pricing_digest)
        self.assertNotEqual(first.cost.pricing_digest, second.cost.pricing_digest)

    def test_missing_persona_cannot_pass_differentiation(self) -> None:
        bundle = make_bundle()
        ballots = bundle.ballots[:2]
        result = arbitrate(bundle.case, bundle.snapshot, ballots)
        evaluation = DecisionEvaluator().evaluate(
            bundle.model_copy(
                update={
                    "ballots": ballots,
                    "result": result,
                    "invocations": bundle.invocations[:2],
                }
            )
        )

        self.assertEqual(evaluation.persona_differentiation.status, MetricStatus.NOT_MEASURED)
        self.assertEqual(evaluation.overall_status, MetricStatus.WARN)

    def test_stored_result_drift_fails_arbitration_consistency(self) -> None:
        bundle = make_bundle()
        inconsistent = ArbitrationResult(
            decision_id=bundle.case.decision_id,
            decision_version=bundle.case.version,
            status=ArbitrationStatus.CONSENSUS,
            winning_option="delay",
            vote_count={"release": 0, "delay": 3, "limited": 0},
            ballot_refs=tuple(ballot.ballot_id for ballot in bundle.ballots),
            created_at=TIMESTAMP,
        )
        evaluation = DecisionEvaluator().evaluate(
            bundle.model_copy(update={"result": inconsistent})
        )

        self.assertEqual(evaluation.overall_status, MetricStatus.FAIL)
        self.assertIn("winning_option", evaluation.arbitration_consistency.mismatch_fields)

    def test_mixed_decision_records_are_rejected(self) -> None:
        bundle = make_bundle()
        foreign = bundle.ballots[0].model_copy(
            update={"decision_id": UUID("22222222-2222-4222-8222-222222222222")}
        )
        bundle = bundle.model_copy(update={"ballots": (foreign, *bundle.ballots[1:])})

        with self.assertRaises(ProtocolViolation):
            DecisionEvaluator().evaluate(bundle)

    def test_cli_emits_stable_json_and_threshold_exit_code(self) -> None:
        bundle = make_bundle(identical_personas=True)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bundle.json"
            path.write_text(bundle.model_dump_json(), encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = evaluation_cli.main([str(path), "--fail-on-threshold"])

        self.assertEqual(code, evaluation_cli.EXIT_THRESHOLD)
        self.assertEqual(json.loads(output.getvalue())["overall_status"], "fail")

    def test_cli_rejects_bundle_over_hard_size_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "oversized.json"
            path.write_bytes(b" " * (evaluation_cli.MAX_INPUT_BYTES + 1))
            code = evaluation_cli.main([str(path)])

        self.assertEqual(code, evaluation_cli.EXIT_INVALID_INPUT)


class FakeStateReader:
    def __init__(self, bundle: EvaluationBundle) -> None:
        self.bundle = bundle
        self.calls: list[tuple[UUID, int]] = []

    async def reconstruct_state(
        self, decision_id: UUID, decision_version: int
    ) -> AuditDecisionState:
        self.calls.append((decision_id, decision_version))
        return AuditDecisionState(
            case=self.bundle.case,
            snapshot=self.bundle.snapshot,
            first_ballots=self.bundle.ballots,
            result=self.bundle.result,
            phase="complete",
        )


class FakeInvocationHistory:
    def __init__(self, bundle: EvaluationBundle) -> None:
        self.bundle = bundle

    async def records_for(self, decision_id: UUID, decision_version: int):
        return self.bundle.invocations


class EvaluationHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_service_rebuilds_authoritative_inputs_and_deduplicates(self) -> None:
        bundle = make_bundle()
        reader = FakeStateReader(bundle)
        store = InMemoryEvaluationStore()
        service = DecisionEvaluationService(
            reader,
            FakeInvocationHistory(bundle),
            store,
            pricing=bundle.pricing,
            thresholds=bundle.thresholds,
            clock=lambda: TIMESTAMP,
        )

        first = await service.run(bundle.case.decision_id, bundle.case.version)
        replay = await service.run(bundle.case.decision_id, bundle.case.version)
        history = await service.history(bundle.case.decision_id, bundle.case.version)

        self.assertEqual(first, replay)
        self.assertEqual(first.sequence, 1)
        self.assertEqual(history.total_count, 1)
        self.assertEqual(history.trend.pass_count, 1)
        self.assertEqual(len(reader.calls), 2)

    async def test_history_trend_uses_returned_chronological_window(self) -> None:
        passing = DecisionEvaluator().evaluate(make_bundle())
        failing = DecisionEvaluator().evaluate(make_bundle(identical_personas=True))
        store = InMemoryEvaluationStore()
        await store.append(passing, created_at=TIMESTAMP)
        second = await store.append(failing, created_at=TIMESTAMP)

        history = await store.history(
            passing.decision_id, passing.version, limit=1
        )

        self.assertEqual(history.total_count, 2)
        self.assertEqual(history.evaluations, (second,))
        self.assertEqual(history.trend.sample_count, 1)
        self.assertEqual(history.trend.fail_count, 1)


if __name__ == "__main__":
    unittest.main()
