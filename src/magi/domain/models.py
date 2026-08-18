"""Immutable Pydantic records for the MAGI decision domain."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import (
    AgentName,
    ArbitrationStatus,
    ConstraintStrength,
    ConstraintValidationStatus,
    DataClassification,
    DecisionType,
    EvidenceQuality,
    Likelihood,
    RiskLevel,
    RoundAction,
    Severity,
    Stance,
    VerificationStatus,
)


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(timezone.utc)


class MagiModel(BaseModel):
    """Strict immutable base model used by all canonical domain records."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        use_enum_values=False,
    )


class DecisionOption(MagiModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")
    label: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class UserConstraint(MagiModel):
    id: str = Field(min_length=1, max_length=80)
    strength: ConstraintStrength
    statement: str = Field(min_length=1, max_length=2000)
    source: str | None = Field(default=None, max_length=500)


class ContextClaim(MagiModel):
    id: str = Field(min_length=1, max_length=80)
    statement: str = Field(min_length=1, max_length=4000)
    verification_status: VerificationStatus
    evidence_refs: tuple[str, ...] = ()


class DecisionCase(MagiModel):
    schema_version: Literal["1.0"] = "1.0"
    decision_id: UUID = Field(default_factory=uuid4)
    version: int = Field(default=1, ge=1)
    title: str = Field(min_length=1, max_length=200)
    raw_question: str = Field(min_length=1, max_length=20_000)
    question: str = Field(min_length=1, max_length=10_000)
    decision_type: DecisionType
    options: tuple[DecisionOption, ...]
    user_constraints: tuple[UserConstraint, ...] = ()
    context_claims: tuple[ContextClaim, ...] = ()
    unknowns: tuple[str, ...] = ()
    risk_level: RiskLevel
    data_classification: DataClassification
    confirmed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_options_and_confirmation(self) -> DecisionCase:
        if len(self.options) < 2:
            raise ValueError("a decision case requires at least two explicit options")
        option_ids = [option.id for option in self.options]
        if len(set(option_ids)) != len(option_ids):
            raise ValueError("decision option IDs must be unique")
        constraint_ids = [constraint.id for constraint in self.user_constraints]
        if len(set(constraint_ids)) != len(constraint_ids):
            raise ValueError("user constraint IDs must be unique")
        claim_ids = [claim.id for claim in self.context_claims]
        if len(set(claim_ids)) != len(claim_ids):
            raise ValueError("context claim IDs must be unique")
        if self.decision_type is DecisionType.BOOLEAN and len(self.options) != 2:
            raise ValueError("a boolean decision requires exactly two options")
        if self.confirmed_at is not None and self.confirmed_at.tzinfo is None:
            raise ValueError("confirmed_at must be timezone-aware")
        return self


class EvidenceItem(MagiModel):
    evidence_id: str = Field(min_length=1, max_length=80)
    source_type: str = Field(min_length=1, max_length=80)
    source: str = Field(min_length=1, max_length=2000)
    captured_at: datetime
    content_hash: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    excerpt: str = Field(min_length=1, max_length=20_000)
    verification_status: VerificationStatus
    classification: DataClassification

    @model_validator(mode="after")
    def validate_timestamp(self) -> EvidenceItem:
        if self.captured_at.tzinfo is None:
            raise ValueError("captured_at must be timezone-aware")
        return self


class EvidenceSnapshot(MagiModel):
    snapshot_id: UUID = Field(default_factory=uuid4)
    decision_id: UUID
    decision_version: int = Field(ge=1)
    created_at: datetime = Field(default_factory=utc_now)
    frozen_at: datetime
    evidence: tuple[EvidenceItem, ...] = ()

    @model_validator(mode="after")
    def validate_snapshot(self) -> EvidenceSnapshot:
        if self.created_at.tzinfo is None or self.frozen_at.tzinfo is None:
            raise ValueError("snapshot timestamps must be timezone-aware")
        if self.frozen_at < self.created_at:
            raise ValueError("frozen_at cannot precede created_at")
        ids = [item.evidence_id for item in self.evidence]
        if len(set(ids)) != len(ids):
            raise ValueError("evidence IDs must be unique within a snapshot")
        return self


class ConstraintClaim(MagiModel):
    claim_id: UUID = Field(default_factory=uuid4)
    category: str = Field(min_length=1, max_length=80)
    statement: str = Field(min_length=1, max_length=4000)
    severity: Severity
    likelihood: Likelihood
    causal_chain: tuple[str, ...] = Field(min_length=1)
    evidence_refs: tuple[str, ...] = ()
    requested_action: str = Field(min_length=1, max_length=200)


class ConstraintValidation(MagiModel):
    claim_id: UUID
    status: ConstraintValidationStatus
    reason: str = Field(min_length=1, max_length=4000)
    condition_for_reconsideration: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def require_condition_for_accepted_claim(self) -> ConstraintValidation:
        if (
            self.status is ConstraintValidationStatus.ACCEPTED
            and not self.condition_for_reconsideration
        ):
            raise ValueError("accepted constraints require a reconsideration condition")
        return self


class Ballot(MagiModel):
    ballot_id: UUID = Field(default_factory=uuid4)
    decision_id: UUID
    decision_version: int = Field(ge=1)
    agent: AgentName
    round: Literal[1, 2]
    selected_option: str | None = Field(default=None, min_length=1, max_length=80)
    stance: Stance
    confidence: float = Field(ge=0, le=1)
    evidence_quality: EvidenceQuality
    rationale_summary: tuple[str, ...] = Field(min_length=1)
    evidence_refs: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    missing_information: tuple[str, ...] = ()
    constraint_claims: tuple[ConstraintClaim, ...] = ()
    changed_from_previous: bool = False
    previous_ballot_id: UUID | None = None
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_ballot_shape(self) -> Ballot:
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        if self.stance is Stance.ABSTAIN and self.selected_option is not None:
            raise ValueError("an abstention cannot select an option")
        if self.stance is not Stance.ABSTAIN and self.selected_option is None:
            raise ValueError("a non-abstaining ballot must select an option")
        if self.round == 1 and (self.changed_from_previous or self.previous_ballot_id is not None):
            raise ValueError("a first-round ballot cannot reference or change a previous ballot")
        if self.round == 2 and self.previous_ballot_id is None:
            raise ValueError("a second-round ballot must reference its first-round ballot")
        return self


class MinorityReport(MagiModel):
    agent: AgentName
    selected_option: str | None
    stance: Stance
    rationale_summary: tuple[str, ...]


class RoundAssessment(MagiModel):
    decision_id: UUID
    decision_version: int
    action: RoundAction
    reason: str
    vote_count: dict[str, int]
    missing_agents: tuple[AgentName, ...] = ()
    abstentions: tuple[AgentName, ...] = ()
    accepted_constraint_ids: tuple[UUID, ...] = ()


class ArbitrationResult(MagiModel):
    arbitration_id: UUID = Field(default_factory=uuid4)
    decision_id: UUID
    decision_version: int
    status: ArbitrationStatus
    winning_option: str | None = None
    vote_count: dict[str, int]
    ballot_refs: tuple[UUID, ...]
    minority_report: MinorityReport | None = None
    unresolved_constraints: tuple[UUID, ...] = ()
    conditions: tuple[str, ...] = ()
    required_information: tuple[str, ...] = ()
    rule_version: Literal["1.0"] = "1.0"
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_result_shape(self) -> ArbitrationResult:
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        if any(count < 0 for count in self.vote_count.values()):
            raise ValueError("vote counts cannot be negative")
        if len(self.ballot_refs) != len(set(self.ballot_refs)):
            raise ValueError("ballot references must be unique")
        decisive = {ArbitrationStatus.CONSENSUS, ArbitrationStatus.MAJORITY}
        if self.status in decisive and self.winning_option is None:
            raise ValueError("a decisive result requires a winning option")
        if self.status not in decisive and self.winning_option is not None:
            raise ValueError("a non-decisive result cannot declare a winning option")
        if self.status is ArbitrationStatus.MAJORITY and self.minority_report is None:
            raise ValueError("a majority result requires a minority report")
        if self.status is ArbitrationStatus.CONSENSUS and self.minority_report is not None:
            raise ValueError("a consensus result cannot include a minority report")
        if (
            self.status is ArbitrationStatus.CONSENSUS
            and self.vote_count.get(self.winning_option or "", 0) != 3
        ):
            raise ValueError("a consensus result requires three matching votes")
        if (
            self.status is ArbitrationStatus.MAJORITY
            and self.vote_count.get(self.winning_option or "", 0) != 2
        ):
            raise ValueError("a majority result requires two matching votes")
        if self.status is ArbitrationStatus.CONDITIONAL_REJECTION and not self.conditions:
            raise ValueError("a conditional rejection requires reconsideration conditions")
        return self


class DecisionEvent(MagiModel):
    event_id: UUID = Field(default_factory=uuid4)
    decision_id: UUID
    decision_version: int = Field(ge=1)
    sequence: int = Field(ge=0)
    type: str = Field(min_length=1, max_length=120)
    timestamp: datetime = Field(default_factory=utc_now)
    actor: str = Field(min_length=1, max_length=120)
    public_payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_event_timestamp(self) -> DecisionEvent:
        if self.timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        return self
