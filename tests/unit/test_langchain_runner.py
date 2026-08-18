"""Tests for the real-model boundary without making network calls."""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path

from magi.agents import (
    BallotDraft,
    InMemoryInvocationLedger,
    InvocationStatus,
    LangChainPerspectiveRunner,
    PeerBallotSummary,
    PerspectiveExecutionError,
    PerspectiveSkillLoader,
    RetryPolicy,
)
from magi.domain import AgentName, EvidenceQuality, Stance
from tests.fixtures.factories import make_ballot, make_case, make_snapshot


class FakeStructuredModel:
    def __init__(self, output: object) -> None:
        self.output = output
        self.inputs: list[object] = []

    async def ainvoke(self, input: object) -> object:
        self.inputs.append(input)
        if isinstance(self.output, Exception):
            raise self.output
        return self.output


class SequencedStructuredModel:
    def __init__(self, outputs: tuple[object, ...], *, delay: float = 0) -> None:
        self.outputs = list(outputs)
        self.delay = delay
        self.inputs: list[object] = []

    async def ainvoke(self, input: object) -> object:
        self.inputs.append(input)
        if self.delay:
            await asyncio.sleep(self.delay)
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return output


class FakeRawResponse:
    def __init__(self, usage_metadata: dict[str, int]) -> None:
        self.usage_metadata = usage_metadata


def make_draft(
    selected_option: str | None = "release",
    *,
    changed: bool = False,
    evidence_refs: tuple[str, ...] = ("E-001",),
) -> BallotDraft:
    return BallotDraft(
        selected_option=selected_option,
        stance=Stance.ABSTAIN if selected_option is None else Stance.SUPPORT,
        confidence=0.75,
        evidence_quality=EvidenceQuality.MEDIUM,
        rationale_summary=("Evidence supports this option.",),
        evidence_refs=evidence_refs,
        assumptions=(),
        risks=("A bounded execution risk remains.",),
        missing_information=(),
        constraint_claims=(),
        changed_from_previous=changed,
    )


class LangChainPerspectiveRunnerTests(unittest.IsolatedAsyncioTestCase):
    def make_runner(
        self,
        melchior_output: object | None = None,
    ) -> tuple[LangChainPerspectiveRunner, dict[AgentName, FakeStructuredModel]]:
        models = {
            agent: FakeStructuredModel(
                melchior_output
                if agent is AgentName.MELCHIOR and melchior_output is not None
                else make_draft()
            )
            for agent in AgentName
        }
        skills_root = Path(__file__).resolve().parents[2] / "skills"
        runner = LangChainPerspectiveRunner(models, PerspectiveSkillLoader(skills_root))
        return runner, models

    def make_controlled_runner(
        self,
        model: object,
        ledger: InMemoryInvocationLedger,
        *,
        retry_policy: RetryPolicy | None = None,
        sleep=asyncio.sleep,
    ) -> LangChainPerspectiveRunner:
        models = {
            agent: (
                model
                if agent is AgentName.MELCHIOR
                else FakeStructuredModel(make_draft())
            )
            for agent in AgentName
        }
        skills_root = Path(__file__).resolve().parents[2] / "skills"
        return LangChainPerspectiveRunner(
            models,
            PerspectiveSkillLoader(skills_root),
            model_name="test-model-v1",
            ledger=ledger,
            retry_policy=retry_policy,
            sleep=sleep,
        )

    async def test_first_ballot_uses_only_assigned_skill_and_seals_identity(self) -> None:
        case = make_case()
        snapshot = make_snapshot(case)
        runner, models = self.make_runner()

        ballot = await runner.first_ballot(AgentName.MELCHIOR, case, snapshot)

        self.assertEqual(ballot.agent, AgentName.MELCHIOR)
        self.assertEqual(ballot.decision_id, case.decision_id)
        self.assertEqual(ballot.decision_version, case.version)
        self.assertEqual(ballot.round, 1)
        messages = models[AgentName.MELCHIOR].inputs[0]
        self.assertIsInstance(messages, list)
        system_prompt = messages[0][1]
        human_prompt = messages[1][1]
        self.assertIn("# Melchior Analysis", system_prompt)
        self.assertNotIn("# Balthasar Safety", system_prompt)
        self.assertNotIn("# Casper Strategy", system_prompt)
        self.assertNotIn('"peer_summaries"', human_prompt)

    async def test_model_cannot_select_option_outside_confirmed_case(self) -> None:
        case = make_case()
        runner, _ = self.make_runner(make_draft("invented-option"))

        with self.assertRaisesRegex(PerspectiveExecutionError, "outside the confirmed case"):
            await runner.first_ballot(
                AgentName.MELCHIOR,
                case,
                make_snapshot(case),
            )

    async def test_model_cannot_cite_evidence_outside_frozen_snapshot(self) -> None:
        case = make_case()
        runner, _ = self.make_runner(make_draft(evidence_refs=("E-999",)))

        with self.assertRaisesRegex(PerspectiveExecutionError, "frozen snapshot"):
            await runner.first_ballot(
                AgentName.MELCHIOR,
                case,
                make_snapshot(case),
            )

    async def test_review_receives_only_sanitized_peer_summaries(self) -> None:
        case = make_case()
        snapshot = make_snapshot(case)
        previous = make_ballot(case, AgentName.MELCHIOR, "release")
        peer_ballots = (
            make_ballot(case, AgentName.BALTHASAR, "delay"),
            make_ballot(case, AgentName.CASPER, "limited"),
        )
        peers = tuple(PeerBallotSummary.from_ballot(ballot) for ballot in peer_ballots)
        runner, models = self.make_runner(make_draft("delay", changed=True))

        ballot = await runner.review_ballot(
            AgentName.MELCHIOR,
            case,
            snapshot,
            previous,
            peers,
        )

        self.assertEqual(ballot.round, 2)
        self.assertEqual(ballot.previous_ballot_id, previous.ballot_id)
        self.assertTrue(ballot.changed_from_previous)
        human_prompt = models[AgentName.MELCHIOR].inputs[0][1][1]
        self.assertIn('"peer_summaries"', human_prompt)
        for peer in peer_ballots:
            self.assertNotIn(str(peer.ballot_id), human_prompt)

    async def test_invocation_error_is_wrapped_without_provider_message(self) -> None:
        case = make_case()
        runner, _ = self.make_runner(RuntimeError("secret provider response"))

        with self.assertRaisesRegex(
            PerspectiveExecutionError,
            "melchior model invocation failed: RuntimeError",
        ) as raised:
            await runner.first_ballot(
                AgentName.MELCHIOR,
                case,
                make_snapshot(case),
            )
        self.assertNotIn("secret provider response", str(raised.exception))

    async def test_refusal_or_unstructured_output_becomes_execution_error(self) -> None:
        case = make_case()
        runner, _ = self.make_runner({"refusal": "cannot answer"})

        with self.assertRaisesRegex(
            PerspectiveExecutionError,
            "melchior model returned an invalid ballot draft",
        ):
            await runner.first_ballot(
                AgentName.MELCHIOR,
                case,
                make_snapshot(case),
            )

    async def test_success_records_usage_and_reuses_identical_ballot(self) -> None:
        case = make_case()
        ledger = InMemoryInvocationLedger()
        raw = FakeRawResponse(
            {"input_tokens": 12, "output_tokens": 5, "total_tokens": 17}
        )
        model = SequencedStructuredModel(
            ({"raw": raw, "parsed": make_draft(), "parsing_error": None},)
        )
        runner = self.make_controlled_runner(model, ledger)

        first = await runner.first_ballot(
            AgentName.MELCHIOR,
            case,
            make_snapshot(case),
        )
        reused = await runner.first_ballot(
            AgentName.MELCHIOR,
            case,
            make_snapshot(case),
        )

        self.assertEqual(first, reused)
        self.assertEqual(len(model.inputs), 1)
        self.assertEqual(
            tuple(record.status for record in ledger.records),
            (InvocationStatus.SUCCEEDED, InvocationStatus.REUSED),
        )
        self.assertEqual(ledger.records[0].usage.total_tokens, 17)
        self.assertEqual(ledger.records[0].idempotency_key, ledger.records[1].idempotency_key)

    async def test_concurrent_duplicate_calls_share_one_provider_invocation(self) -> None:
        case = make_case()
        ledger = InMemoryInvocationLedger()
        model = SequencedStructuredModel((make_draft(),), delay=0.01)
        runner = self.make_controlled_runner(model, ledger)

        first, second = await asyncio.gather(
            runner.first_ballot(AgentName.MELCHIOR, case, make_snapshot(case)),
            runner.first_ballot(AgentName.MELCHIOR, case, make_snapshot(case)),
        )

        self.assertEqual(first.ballot_id, second.ballot_id)
        self.assertEqual(len(model.inputs), 1)
        self.assertEqual(len(ledger.records), 2)

    async def test_shared_ledger_deduplicates_across_runner_instances(self) -> None:
        case = make_case()
        ledger = InMemoryInvocationLedger()
        model = SequencedStructuredModel((make_draft(),), delay=0.01)
        first_runner = self.make_controlled_runner(model, ledger)
        second_runner = self.make_controlled_runner(model, ledger)

        first, second = await asyncio.gather(
            first_runner.first_ballot(
                AgentName.MELCHIOR,
                case,
                make_snapshot(case),
            ),
            second_runner.first_ballot(
                AgentName.MELCHIOR,
                case,
                make_snapshot(case),
            ),
        )

        self.assertEqual(first.ballot_id, second.ballot_id)
        self.assertEqual(len(model.inputs), 1)

    async def test_transient_timeout_retries_once_and_records_both_attempts(self) -> None:
        case = make_case()
        ledger = InMemoryInvocationLedger()
        model = SequencedStructuredModel((TimeoutError("temporary"), make_draft()))
        delays: list[float] = []

        async def capture_sleep(delay: float) -> None:
            delays.append(delay)

        runner = self.make_controlled_runner(
            model,
            ledger,
            retry_policy=RetryPolicy(max_attempts=2, initial_backoff_seconds=0.1),
            sleep=capture_sleep,
        )

        ballot = await runner.first_ballot(
            AgentName.MELCHIOR,
            case,
            make_snapshot(case),
        )

        self.assertEqual(ballot.selected_option, "release")
        self.assertEqual(len(model.inputs), 2)
        self.assertEqual(delays, [0.1])
        self.assertEqual(
            tuple(record.status for record in ledger.records),
            (InvocationStatus.FAILED, InvocationStatus.SUCCEEDED),
        )
        self.assertEqual(tuple(record.attempt for record in ledger.records), (1, 2))

    async def test_authentication_failure_is_not_retried(self) -> None:
        class AuthenticationError(Exception):
            pass

        case = make_case()
        ledger = InMemoryInvocationLedger()
        model = SequencedStructuredModel((AuthenticationError("bad secret"),))
        runner = self.make_controlled_runner(model, ledger)

        with self.assertRaisesRegex(PerspectiveExecutionError, "AuthenticationError"):
            await runner.first_ballot(
                AgentName.MELCHIOR,
                case,
                make_snapshot(case),
            )

        self.assertEqual(len(model.inputs), 1)
        self.assertEqual(len(ledger.records), 1)
        self.assertEqual(ledger.records[0].error_type, "AuthenticationError")

    def test_all_three_model_boundaries_are_required(self) -> None:
        skills_root = Path(__file__).resolve().parents[2] / "skills"
        with self.assertRaisesRegex(PerspectiveExecutionError, "missing structured model"):
            LangChainPerspectiveRunner(
                {AgentName.MELCHIOR: FakeStructuredModel(make_draft())},
                PerspectiveSkillLoader(skills_root),
            )


if __name__ == "__main__":
    unittest.main()
