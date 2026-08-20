"""Deterministic representative evaluation scenarios for M5 acceptance."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from uuid import UUID

from magi.agents import InvocationStatus, ModelInvocationRecord, ModelTokenUsage
from magi.arbitration import arbitrate
from magi.domain import AgentName, Stance
from magi.evaluation import EvaluationBundle, EvaluationThresholds, ModelPricing
from tests.fixtures.factories import TIMESTAMP, make_ballot, make_case, make_snapshot, stable_id


PRICING = (
    ModelPricing(
        model_name="benchmark-model",
        input_microusd_per_million_tokens=1_000_000,
        output_microusd_per_million_tokens=2_000_000,
    ),
)


def representative_scenarios() -> dict[str, EvaluationBundle]:
    baseline = _consensus()
    invalid_ballot = baseline.ballots[0].model_copy(
        update={"evidence_refs": ("E-MISSING",)}
    )
    return {
        "consensus_baseline": baseline,
        "cross_review_revision": _cross_review_revision(),
        "insufficient_information": _insufficient_information(),
        "degraded_missing_persona": _degraded(),
        "performance_budget_failure": _performance_failure(),
        "invalid_citation_rejected": baseline.model_copy(
            update={"ballots": (invalid_ballot, *baseline.ballots[1:])}
        ),
    }


def _consensus() -> EvaluationBundle:
    case = make_case()
    snapshot = make_snapshot(case)
    ballots = tuple(
        make_ballot(
            case,
            agent,
            "limited",
            rationale_summary=(rationale,),
        )
        for agent, rationale in (
            (AgentName.MELCHIOR, "Technical checks bound release risk."),
            (AgentName.BALTHASAR, "A limited release remains reversible."),
            (AgentName.CASPER, "Staging preserves strategic flexibility."),
        )
    )
    return _bundle(ballots, latencies=(1_000, 1_100, 1_200))


def _cross_review_revision() -> EvaluationBundle:
    case = make_case()
    first = {
        agent: make_ballot(case, agent, option)
        for agent, option in (
            (AgentName.MELCHIOR, "release"),
            (AgentName.BALTHASAR, "delay"),
            (AgentName.CASPER, "delay"),
        )
    }
    final = tuple(
        make_ballot(
            case,
            agent,
            option,
            round_number=2,
            previous_ballot_id=first[agent].ballot_id,
            changed=option != first[agent].selected_option,
            review_reason=reason,
            rationale_summary=(rationale,),
        )
        for agent, option, reason, rationale in (
            (
                AgentName.MELCHIOR,
                "release",
                "Peer review confirmed the verified technical checks.",
                "Verified checks support release readiness.",
            ),
            (
                AgentName.BALTHASAR,
                "delay",
                "Residual support risk remains difficult to reverse.",
                "Human support risk favors a delay.",
            ),
            (
                AgentName.CASPER,
                "release",
                "Monitoring resolves the earlier strategic uncertainty.",
                "Staged monitoring preserves strategic options.",
            ),
        )
    )
    return _bundle(
        final,
        latencies=(900, 1_000, 1_100, 1_200, 1_300, 1_400),
        invocation_agents=(*AgentName, *AgentName),
        maximum_cost=2_000,
    )


def _insufficient_information() -> EvaluationBundle:
    case = make_case()
    ballots = (
        make_ballot(
            case,
            AgentName.MELCHIOR,
            None,
            stance=Stance.ABSTAIN,
            missing_information=("Load-test evidence is missing.",),
            rationale_summary=("Technical evidence is incomplete.",),
        ),
        make_ballot(
            case,
            AgentName.BALTHASAR,
            None,
            stance=Stance.ABSTAIN,
            missing_information=("Support staffing is unconfirmed.",),
            rationale_summary=("Human impact cannot yet be bounded.",),
        ),
        make_ballot(
            case,
            AgentName.CASPER,
            "limited",
            rationale_summary=("A limited path preserves future choices.",),
        ),
    )
    return _bundle(ballots, latencies=(800, 900, 1_000))


def _degraded() -> EvaluationBundle:
    case = make_case()
    ballots = tuple(
        make_ballot(case, agent, "release", rationale_summary=(rationale,))
        for agent, rationale in (
            (AgentName.MELCHIOR, "Technical verification supports release."),
            (AgentName.BALTHASAR, "Rollback limits human impact."),
        )
    )
    return _bundle(
        ballots,
        latencies=(700, 850),
        invocation_agents=(AgentName.MELCHIOR, AgentName.BALTHASAR),
    )


def _performance_failure() -> EvaluationBundle:
    case = make_case()
    ballots = tuple(
        make_ballot(case, agent, "limited", rationale_summary=(f"{agent.value} view",))
        for agent in AgentName
    )
    return _bundle(
        ballots,
        latencies=(1_000, 1_200, 5_000),
        input_tokens=1_000,
        output_tokens=500,
        maximum_latency=2_000,
        maximum_cost=1_000,
    )


def _bundle(
    ballots,
    *,
    latencies: Sequence[int],
    invocation_agents: Sequence[AgentName] = tuple(AgentName),
    input_tokens: int = 100,
    output_tokens: int = 50,
    maximum_latency: int = 2_000,
    maximum_cost: int = 1_000,
) -> EvaluationBundle:
    case = make_case()
    snapshot = make_snapshot(case)
    result = arbitrate(case, snapshot, ballots)
    invocations = tuple(
        _invocation(
            case.decision_id,
            agent,
            index,
            latency,
            input_tokens,
            output_tokens,
        )
        for index, (agent, latency) in enumerate(
            zip(invocation_agents, latencies, strict=True), start=1
        )
    )
    return EvaluationBundle(
        case=case,
        snapshot=snapshot,
        ballots=ballots,
        result=result,
        invocations=invocations,
        pricing=PRICING,
        thresholds=EvaluationThresholds(
            minimum_citation_validity=1,
            minimum_persona_distance=0.35,
            maximum_p95_latency_ms=maximum_latency,
            maximum_cost_microusd=maximum_cost,
        ),
    )


def _invocation(
    decision_id: UUID,
    agent: AgentName,
    index: int,
    latency: int,
    input_tokens: int,
    output_tokens: int,
) -> ModelInvocationRecord:
    material = f"representative-{agent.value}-{index}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return ModelInvocationRecord(
        invocation_id=stable_id(material),
        idempotency_key=digest,
        prompt_digest=digest,
        decision_id=decision_id,
        decision_version=1,
        agent=agent,
        round=1 if index <= 3 else 2,
        attempt=1,
        status=InvocationStatus.SUCCEEDED,
        model_name="benchmark-model",
        started_at=TIMESTAMP,
        completed_at=TIMESTAMP,
        latency_ms=latency,
        usage=ModelTokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        ),
    )
