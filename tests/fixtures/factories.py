"""Deterministic factories for M1 domain and arbitration tests."""

from datetime import datetime, timezone
from uuid import UUID, NAMESPACE_URL, uuid5

from magi.domain import (
    AgentName,
    Ballot,
    ConstraintClaim,
    DataClassification,
    DecisionCase,
    DecisionOption,
    DecisionType,
    EvidenceItem,
    EvidenceQuality,
    EvidenceSnapshot,
    Likelihood,
    RiskLevel,
    Severity,
    Stance,
    VerificationStatus,
)

DECISION_ID = UUID("11111111-1111-4111-8111-111111111111")
TIMESTAMP = datetime(2026, 8, 18, 8, 0, tzinfo=timezone.utc)


def stable_id(value: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"https://magi.local/test/{value}")


def make_case(
    *,
    risk_level: RiskLevel = RiskLevel.LOW,
    confirmed: bool = True,
) -> DecisionCase:
    return DecisionCase(
        decision_id=DECISION_ID,
        version=1,
        title="Release decision",
        raw_question="Should we release?",
        question="Should the current build be released?",
        decision_type=DecisionType.SINGLE_CHOICE,
        options=(
            DecisionOption(id="release", label="Release"),
            DecisionOption(id="delay", label="Delay"),
            DecisionOption(id="limited", label="Limited release"),
        ),
        risk_level=risk_level,
        data_classification=DataClassification.INTERNAL,
        confirmed_at=TIMESTAMP if confirmed else None,
    )


def make_snapshot(case: DecisionCase) -> EvidenceSnapshot:
    return EvidenceSnapshot(
        snapshot_id=stable_id("snapshot"),
        decision_id=case.decision_id,
        decision_version=case.version,
        created_at=TIMESTAMP,
        frozen_at=TIMESTAMP,
        evidence=(
            EvidenceItem(
                evidence_id="E-001",
                source_type="test_fixture",
                source="release-report.txt",
                captured_at=TIMESTAMP,
                content_hash="a" * 64,
                excerpt="All required checks completed.",
                verification_status=VerificationStatus.VERIFIED,
                classification=DataClassification.INTERNAL,
            ),
        ),
    )


def make_claim(agent: AgentName = AgentName.BALTHASAR) -> ConstraintClaim:
    return ConstraintClaim(
        claim_id=stable_id(f"claim-{agent.value}"),
        category="safety",
        statement="The release can cause irreversible data loss.",
        severity=Severity.CRITICAL,
        likelihood=Likelihood.POSSIBLE,
        causal_chain=("Migration runs", "rollback fails", "data becomes unrecoverable"),
        evidence_refs=("E-001",),
        requested_action="suspend_decision",
    )


def make_ballot(
    case: DecisionCase,
    agent: AgentName,
    selected_option: str | None,
    *,
    round_number: int = 1,
    stance: Stance = Stance.SUPPORT,
    claims: tuple[ConstraintClaim, ...] = (),
    missing_information: tuple[str, ...] = (),
    confidence: float = 0.7,
    evidence_refs: tuple[str, ...] = ("E-001",),
    changed: bool = False,
    previous_ballot_id: UUID | None = None,
) -> Ballot:
    previous_id = None
    if round_number == 2:
        previous_id = previous_ballot_id or stable_id(f"{agent.value}-round-1")
    return Ballot(
        ballot_id=stable_id(f"{agent.value}-round-{round_number}-{selected_option}-{stance.value}"),
        decision_id=case.decision_id,
        decision_version=case.version,
        agent=agent,
        round=round_number,
        selected_option=selected_option,
        stance=stance,
        confidence=confidence,
        evidence_quality=EvidenceQuality.MEDIUM,
        rationale_summary=(f"{agent.value} rationale",),
        evidence_refs=evidence_refs,
        missing_information=missing_information,
        constraint_claims=claims,
        changed_from_previous=changed,
        previous_ballot_id=previous_id,
        created_at=TIMESTAMP,
    )
