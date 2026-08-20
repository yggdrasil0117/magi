"""Deterministic, provider-neutral evaluation for completed MAGI decisions."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from enum import StrEnum
from itertools import combinations
from math import ceil
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from magi.agents.invocation import InvocationStatus, ModelInvocationRecord
from magi.arbitration import DeterministicArbiter
from magi.domain import (
    ArbitrationResult,
    Ballot,
    ConstraintValidation,
    DecisionCase,
    EvidenceSnapshot,
    ProtocolViolation,
)
from magi.domain.models import MagiModel


class MetricStatus(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    NOT_MEASURED = "not_measured"


class EvaluationThresholds(MagiModel):
    minimum_citation_validity: float = Field(default=1.0, ge=0, le=1)
    minimum_persona_distance: float = Field(default=0.35, ge=0, le=1)
    maximum_p95_latency_ms: int = Field(default=30_000, ge=1)
    maximum_cost_microusd: int | None = Field(default=None, ge=0)


class ModelPricing(MagiModel):
    """Explicit price snapshot; one micro-USD equals 0.000001 USD."""

    model_name: str = Field(min_length=1, max_length=200)
    input_microusd_per_million_tokens: int = Field(ge=0)
    output_microusd_per_million_tokens: int = Field(ge=0)


class CitationMetric(MagiModel):
    status: MetricStatus
    score: float | None = Field(default=None, ge=0, le=1)
    reference_count: int = Field(ge=0)
    valid_reference_count: int = Field(ge=0)
    invalid_references: tuple[str, ...] = ()
    threshold: float = Field(ge=0, le=1)


class PersonaMetric(MagiModel):
    status: MetricStatus
    score: float | None = Field(default=None, ge=0, le=1)
    pair_count: int = Field(ge=0)
    minimum_pair_distance: float | None = Field(default=None, ge=0, le=1)
    identical_pairs: tuple[str, ...] = ()
    threshold: float = Field(ge=0, le=1)


class ArbitrationMetric(MagiModel):
    status: MetricStatus
    score: Literal[0.0, 1.0]
    consistent: bool
    mismatch_fields: tuple[str, ...] = ()
    rule_version: str


class LatencyMetric(MagiModel):
    status: MetricStatus
    sample_count: int = Field(ge=0)
    mean_latency_ms: int | None = Field(default=None, ge=0)
    p95_latency_ms: int | None = Field(default=None, ge=0)
    maximum_p95_latency_ms: int = Field(ge=1)


class CostMetric(MagiModel):
    status: MetricStatus
    priced_invocation_count: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_cost_microusd: int | None = Field(default=None, ge=0)
    maximum_cost_microusd: int | None = Field(default=None, ge=0)
    unpriced_models: tuple[str, ...] = ()


class DecisionEvaluation(MagiModel):
    schema_version: Literal["1.0"] = "1.0"
    decision_id: UUID
    version: int = Field(ge=1)
    overall_status: MetricStatus
    citation_validity: CitationMetric
    persona_differentiation: PersonaMetric
    arbitration_consistency: ArbitrationMetric
    latency: LatencyMetric
    cost: CostMetric
    evaluated_at: datetime

    @model_validator(mode="after")
    def validate_timestamp(self) -> DecisionEvaluation:
        if self.evaluated_at.tzinfo is None:
            raise ValueError("evaluated_at must be timezone-aware")
        return self


class EvaluationBundle(MagiModel):
    """Portable input contract for offline and CI evaluation."""

    schema_version: Literal["1.0"] = "1.0"
    case: DecisionCase
    snapshot: EvidenceSnapshot
    ballots: tuple[Ballot, ...]
    result: ArbitrationResult
    validations: tuple[ConstraintValidation, ...] = ()
    invocations: tuple[ModelInvocationRecord, ...] = ()
    pricing: tuple[ModelPricing, ...] = ()
    thresholds: EvaluationThresholds = Field(default_factory=EvaluationThresholds)

    @model_validator(mode="after")
    def validate_pricing(self) -> EvaluationBundle:
        names = [rate.model_name for rate in self.pricing]
        if len(names) != len(set(names)):
            raise ValueError("pricing model names must be unique")
        return self


class DecisionEvaluator:
    """Compute metrics without model calls or mutable external state."""

    def __init__(self, arbiter: DeterministicArbiter | None = None) -> None:
        self._arbiter = arbiter or DeterministicArbiter()

    def evaluate(self, bundle: EvaluationBundle) -> DecisionEvaluation:
        self._validate_identity(bundle)
        citations = self._citations(bundle)
        personas = self._personas(bundle)
        arbitration = self._arbitration(bundle)
        latency = self._latency(bundle)
        cost = self._cost(bundle)
        statuses = (
            citations.status,
            personas.status,
            arbitration.status,
            latency.status,
            cost.status,
        )
        overall = (
            MetricStatus.FAIL
            if MetricStatus.FAIL in statuses
            else MetricStatus.WARN
            if any(status is not MetricStatus.PASS for status in statuses)
            else MetricStatus.PASS
        )
        return DecisionEvaluation(
            decision_id=bundle.case.decision_id,
            version=bundle.case.version,
            overall_status=overall,
            citation_validity=citations,
            persona_differentiation=personas,
            arbitration_consistency=arbitration,
            latency=latency,
            cost=cost,
            evaluated_at=bundle.result.created_at,
        )

    @staticmethod
    def _validate_identity(bundle: EvaluationBundle) -> None:
        identity = (bundle.case.decision_id, bundle.case.version)
        records: Iterable[tuple[object, int]] = (
            (bundle.snapshot.decision_id, bundle.snapshot.decision_version),
            (bundle.result.decision_id, bundle.result.decision_version),
            *((ballot.decision_id, ballot.decision_version) for ballot in bundle.ballots),
            *((record.decision_id, record.decision_version) for record in bundle.invocations),
        )
        if any(record != identity for record in records):
            raise ProtocolViolation("evaluation records do not share one decision identity")

    @staticmethod
    def _citations(bundle: EvaluationBundle) -> CitationMetric:
        known = {item.evidence_id for item in bundle.snapshot.evidence}
        references = tuple(
            reference
            for ballot in bundle.ballots
            for reference in (
                *ballot.evidence_refs,
                *(ref for claim in ballot.constraint_claims for ref in claim.evidence_refs),
            )
        )
        if not references:
            return CitationMetric(
                status=MetricStatus.NOT_MEASURED,
                reference_count=0,
                valid_reference_count=0,
                threshold=bundle.thresholds.minimum_citation_validity,
            )
        invalid = tuple(sorted(set(references) - known))
        valid_count = sum(reference in known for reference in references)
        score = valid_count / len(references)
        return CitationMetric(
            status=(
                MetricStatus.PASS
                if score >= bundle.thresholds.minimum_citation_validity
                else MetricStatus.FAIL
            ),
            score=score,
            reference_count=len(references),
            valid_reference_count=valid_count,
            invalid_references=invalid,
            threshold=bundle.thresholds.minimum_citation_validity,
        )

    @staticmethod
    def _personas(bundle: EvaluationBundle) -> PersonaMetric:
        pairs = tuple(combinations(sorted(bundle.ballots, key=lambda item: item.agent.value), 2))
        if len(bundle.ballots) < 3:
            return PersonaMetric(
                status=MetricStatus.NOT_MEASURED,
                pair_count=len(pairs),
                threshold=bundle.thresholds.minimum_persona_distance,
            )
        distances: list[float] = []
        identical: list[str] = []
        for left, right in pairs:
            left_features = _ballot_features(left)
            right_features = _ballot_features(right)
            union = left_features | right_features
            distance = 0.0 if not union else 1 - len(left_features & right_features) / len(union)
            distances.append(distance)
            if distance == 0:
                identical.append(f"{left.agent.value}:{right.agent.value}")
        score = sum(distances) / len(distances)
        minimum_distance = min(distances)
        return PersonaMetric(
            status=(
                MetricStatus.PASS
                if minimum_distance >= bundle.thresholds.minimum_persona_distance
                else MetricStatus.FAIL
            ),
            score=score,
            pair_count=len(pairs),
            minimum_pair_distance=minimum_distance,
            identical_pairs=tuple(identical),
            threshold=bundle.thresholds.minimum_persona_distance,
        )

    def _arbitration(self, bundle: EvaluationBundle) -> ArbitrationMetric:
        expected = self._arbiter.arbitrate(
            bundle.case,
            bundle.snapshot,
            bundle.ballots,
            bundle.validations,
        )
        fields = (
            "status",
            "winning_option",
            "vote_count",
            "ballot_refs",
            "minority_report",
            "unresolved_constraints",
            "conditions",
            "required_information",
            "rule_version",
        )
        mismatches = tuple(
            field for field in fields if getattr(expected, field) != getattr(bundle.result, field)
        )
        consistent = not mismatches
        return ArbitrationMetric(
            status=MetricStatus.PASS if consistent else MetricStatus.FAIL,
            score=1.0 if consistent else 0.0,
            consistent=consistent,
            mismatch_fields=mismatches,
            rule_version=expected.rule_version,
        )

    @staticmethod
    def _latency(bundle: EvaluationBundle) -> LatencyMetric:
        samples = sorted(
            record.latency_ms
            for record in bundle.invocations
            if record.status is not InvocationStatus.REUSED
        )
        if not samples:
            return LatencyMetric(
                status=MetricStatus.NOT_MEASURED,
                sample_count=0,
                maximum_p95_latency_ms=bundle.thresholds.maximum_p95_latency_ms,
            )
        p95 = samples[max(ceil(len(samples) * 0.95) - 1, 0)]
        return LatencyMetric(
            status=(
                MetricStatus.PASS
                if p95 <= bundle.thresholds.maximum_p95_latency_ms
                else MetricStatus.FAIL
            ),
            sample_count=len(samples),
            mean_latency_ms=round(sum(samples) / len(samples)),
            p95_latency_ms=p95,
            maximum_p95_latency_ms=bundle.thresholds.maximum_p95_latency_ms,
        )

    @staticmethod
    def _cost(bundle: EvaluationBundle) -> CostMetric:
        attempts = tuple(
            record
            for record in bundle.invocations
            if record.status is not InvocationStatus.REUSED
        )
        input_tokens = sum(record.usage.input_tokens for record in attempts)
        output_tokens = sum(record.usage.output_tokens for record in attempts)
        prices = {rate.model_name: rate for rate in bundle.pricing}
        unpriced = tuple(sorted({record.model_name for record in attempts} - prices.keys()))
        if not attempts or unpriced:
            return CostMetric(
                status=MetricStatus.NOT_MEASURED,
                priced_invocation_count=sum(record.model_name in prices for record in attempts),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                maximum_cost_microusd=bundle.thresholds.maximum_cost_microusd,
                unpriced_models=unpriced,
            )
        numerator = sum(
            record.usage.input_tokens * prices[record.model_name].input_microusd_per_million_tokens
            + record.usage.output_tokens
            * prices[record.model_name].output_microusd_per_million_tokens
            for record in attempts
        )
        total = ceil(numerator / 1_000_000)
        maximum = bundle.thresholds.maximum_cost_microusd
        status = (
            MetricStatus.PASS
            if maximum is None or total <= maximum
            else MetricStatus.FAIL
        )
        return CostMetric(
            status=status,
            priced_invocation_count=len(attempts),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_cost_microusd=total,
            maximum_cost_microusd=maximum,
        )


def _ballot_features(ballot: Ballot) -> set[str]:
    values: Sequence[str] = (
        *ballot.rationale_summary,
        *ballot.assumptions,
        *ballot.risks,
        *ballot.missing_information,
        *(claim.statement for claim in ballot.constraint_claims),
    )
    return {" ".join(value.casefold().split()) for value in values if value.strip()}
