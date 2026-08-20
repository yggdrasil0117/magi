"""Append-only evaluation history and server-side evaluation composition."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID, uuid5

from pydantic import Field, model_validator

from magi.agents import ModelInvocationRecord
from magi.application import DecisionReportNotReady
from magi.audit import AuditDecisionState
from magi.domain.models import MagiModel, utc_now

from .core import (
    DecisionEvaluation,
    DecisionEvaluator,
    EvaluationBundle,
    EvaluationThresholds,
    MetricStatus,
    ModelPricing,
)


EVALUATION_NAMESPACE = UUID("1320eb40-963f-439e-bf54-37ad2aa71127")


class EvaluationRecord(MagiModel):
    schema_version: Literal["1.0"] = "1.0"
    evaluation_id: UUID
    decision_id: UUID
    decision_version: int = Field(ge=1)
    sequence: int = Field(ge=1)
    evaluation_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    evaluation: DecisionEvaluation
    created_at: datetime

    @model_validator(mode="after")
    def validate_envelope(self) -> EvaluationRecord:
        identity = (self.decision_id, self.decision_version)
        if (self.evaluation.decision_id, self.evaluation.version) != identity:
            raise ValueError("evaluation record identity does not match its payload")
        if self.created_at.tzinfo is None:
            raise ValueError("evaluation record time must be timezone-aware")
        digest = evaluation_digest(self.evaluation)
        if self.evaluation_digest != digest:
            raise ValueError("evaluation digest does not match its payload")
        if self.evaluation_id != evaluation_id(self.decision_id, self.decision_version, digest):
            raise ValueError("evaluation ID does not match its payload")
        return self


class EvaluationTrend(MagiModel):
    schema_version: Literal["1.0"] = "1.0"
    sample_count: int = Field(ge=0)
    pass_count: int = Field(ge=0)
    warn_count: int = Field(ge=0)
    fail_count: int = Field(ge=0)
    latest_status: MetricStatus | None = None
    mean_citation_score: float | None = Field(default=None, ge=0, le=1)
    mean_persona_score: float | None = Field(default=None, ge=0, le=1)
    mean_p95_latency_ms: int | None = Field(default=None, ge=0)
    mean_cost_microusd: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> EvaluationTrend:
        if self.pass_count + self.warn_count + self.fail_count != self.sample_count:
            raise ValueError("evaluation trend status counts do not match samples")
        if (self.sample_count == 0) != (self.latest_status is None):
            raise ValueError("evaluation trend latest status does not match samples")
        return self


class EvaluationHistory(MagiModel):
    schema_version: Literal["1.0"] = "1.0"
    decision_id: UUID
    decision_version: int = Field(ge=1)
    total_count: int = Field(ge=0)
    evaluations: tuple[EvaluationRecord, ...] = ()
    trend: EvaluationTrend

    @model_validator(mode="after")
    def validate_history(self) -> EvaluationHistory:
        if self.total_count < len(self.evaluations):
            raise ValueError("evaluation total cannot be smaller than returned records")
        previous = 0
        for record in self.evaluations:
            if (
                record.decision_id != self.decision_id
                or record.decision_version != self.decision_version
                or record.sequence <= previous
            ):
                raise ValueError("evaluation history identity or order is invalid")
            previous = record.sequence
        if self.trend.sample_count != len(self.evaluations):
            raise ValueError("evaluation trend window does not match returned records")
        return self


class EvaluationStore(Protocol):
    async def append(
        self, evaluation: DecisionEvaluation, *, created_at: datetime
    ) -> EvaluationRecord: ...

    async def history(
        self, decision_id: UUID, decision_version: int, *, limit: int
    ) -> EvaluationHistory: ...


class InMemoryEvaluationStore:
    def __init__(self) -> None:
        self._records: dict[tuple[UUID, int], list[EvaluationRecord]] = {}

    async def append(
        self, evaluation: DecisionEvaluation, *, created_at: datetime
    ) -> EvaluationRecord:
        key = (evaluation.decision_id, evaluation.version)
        records = self._records.setdefault(key, [])
        digest = evaluation_digest(evaluation)
        existing = next(
            (record for record in records if record.evaluation_digest == digest), None
        )
        if existing is not None:
            return existing
        record = build_evaluation_record(
            evaluation,
            sequence=len(records) + 1,
            created_at=created_at,
        )
        records.append(record)
        return record

    async def history(
        self, decision_id: UUID, decision_version: int, *, limit: int
    ) -> EvaluationHistory:
        if not 1 <= limit <= 100:
            raise ValueError("evaluation history limit must be between 1 and 100")
        records = self._records.get((decision_id, decision_version), [])
        selected = tuple(records[-limit:])
        return build_evaluation_history(
            decision_id,
            decision_version,
            total_count=len(records),
            records=selected,
        )


class EvaluationStateReader(Protocol):
    async def reconstruct_state(
        self, decision_id: UUID, decision_version: int
    ) -> AuditDecisionState: ...


class InvocationHistory(Protocol):
    async def records_for(
        self, decision_id: UUID, decision_version: int
    ) -> tuple[ModelInvocationRecord, ...]: ...


class DecisionEvaluationService:
    """Rebuild authoritative inputs, evaluate, and append one stable record."""

    def __init__(
        self,
        state_reader: EvaluationStateReader,
        invocation_history: InvocationHistory,
        store: EvaluationStore,
        *,
        pricing: tuple[ModelPricing, ...] = (),
        thresholds: EvaluationThresholds | None = None,
        evaluator: DecisionEvaluator | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._state_reader = state_reader
        self._invocation_history = invocation_history
        self._store = store
        self._pricing = pricing
        self._thresholds = thresholds or EvaluationThresholds()
        self._evaluator = evaluator or DecisionEvaluator()
        self._clock = clock

    async def run(self, decision_id: UUID, decision_version: int) -> EvaluationRecord:
        state = await self._state_reader.reconstruct_state(decision_id, decision_version)
        if state.result is None:
            raise DecisionReportNotReady("decision audit has no terminal result")
        ballots = state.review_ballots or state.first_ballots
        invocations = await self._invocation_history.records_for(
            decision_id, decision_version
        )
        evaluation = self._evaluator.evaluate(
            EvaluationBundle(
                case=state.case,
                snapshot=state.snapshot,
                ballots=ballots,
                result=state.result,
                validations=state.constraint_validations,
                invocations=invocations,
                pricing=self._pricing,
                thresholds=self._thresholds,
            )
        )
        return await self._store.append(evaluation, created_at=self._clock())

    async def history(
        self, decision_id: UUID, decision_version: int, *, limit: int = 20
    ) -> EvaluationHistory:
        return await self._store.history(
            decision_id, decision_version, limit=limit
        )


def evaluation_digest(evaluation: DecisionEvaluation) -> str:
    material = json.dumps(
        evaluation.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def evaluation_id(decision_id: UUID, decision_version: int, digest: str) -> UUID:
    return uuid5(
        EVALUATION_NAMESPACE,
        f"{decision_id}:{decision_version}:{digest}",
    )


def build_evaluation_record(
    evaluation: DecisionEvaluation,
    *,
    sequence: int,
    created_at: datetime,
) -> EvaluationRecord:
    digest = evaluation_digest(evaluation)
    return EvaluationRecord(
        evaluation_id=evaluation_id(evaluation.decision_id, evaluation.version, digest),
        decision_id=evaluation.decision_id,
        decision_version=evaluation.version,
        sequence=sequence,
        evaluation_digest=digest,
        evaluation=evaluation,
        created_at=created_at,
    )


def build_evaluation_history(
    decision_id: UUID,
    decision_version: int,
    *,
    total_count: int,
    records: Sequence[EvaluationRecord],
) -> EvaluationHistory:
    selected = tuple(records)
    return EvaluationHistory(
        decision_id=decision_id,
        decision_version=decision_version,
        total_count=total_count,
        evaluations=selected,
        trend=evaluation_trend(selected),
    )


def evaluation_trend(records: Sequence[EvaluationRecord]) -> EvaluationTrend:
    evaluations = tuple(record.evaluation for record in records)
    statuses = tuple(evaluation.overall_status for evaluation in evaluations)
    citation_scores = tuple(
        value
        for evaluation in evaluations
        if (value := evaluation.citation_validity.score) is not None
    )
    persona_scores = tuple(
        value
        for evaluation in evaluations
        if (value := evaluation.persona_differentiation.score) is not None
    )
    latencies = tuple(
        value
        for evaluation in evaluations
        if (value := evaluation.latency.p95_latency_ms) is not None
    )
    costs = tuple(
        value
        for evaluation in evaluations
        if (value := evaluation.cost.total_cost_microusd) is not None
    )
    return EvaluationTrend(
        sample_count=len(evaluations),
        pass_count=statuses.count(MetricStatus.PASS),
        warn_count=statuses.count(MetricStatus.WARN),
        fail_count=statuses.count(MetricStatus.FAIL),
        latest_status=statuses[-1] if statuses else None,
        mean_citation_score=_mean_float(citation_scores),
        mean_persona_score=_mean_float(persona_scores),
        mean_p95_latency_ms=_mean_int(latencies),
        mean_cost_microusd=_mean_int(costs),
    )


def _mean_float(values: Sequence[float]) -> float | None:
    return round(sum(values) / len(values), 6) if values else None


def _mean_int(values: Sequence[int]) -> int | None:
    return round(sum(values) / len(values)) if values else None
