"""Agent-facing ports used by the orchestration layer."""

from __future__ import annotations

from typing import Protocol

from pydantic import Field

from magi.domain import (
    AgentName,
    Ballot,
    DecisionCase,
    EvidenceSnapshot,
    EvidenceQuality,
    MagiDomainError,
    Stance,
)
from magi.domain.models import MagiModel


class PerspectiveExecutionError(MagiDomainError):
    """Raised when a perspective runner returns a ballot outside its assignment."""


class PeerBallotSummary(MagiModel):
    """Sanitized cross-review input with no private working memory."""

    agent: AgentName
    selected_option: str | None
    stance: Stance
    confidence: float = Field(ge=0, le=1)
    evidence_quality: EvidenceQuality
    rationale_summary: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    risks: tuple[str, ...]
    constraint_claim_ids: tuple[str, ...]

    @classmethod
    def from_ballot(cls, ballot: Ballot) -> PeerBallotSummary:
        return cls(
            agent=ballot.agent,
            selected_option=ballot.selected_option,
            stance=ballot.stance,
            confidence=ballot.confidence,
            evidence_quality=ballot.evidence_quality,
            rationale_summary=ballot.rationale_summary,
            evidence_refs=ballot.evidence_refs,
            risks=ballot.risks,
            constraint_claim_ids=tuple(
                str(claim.claim_id) for claim in ballot.constraint_claims
            ),
        )


class PerspectiveRunner(Protocol):
    """Run one isolated perspective for first ballot and bounded review."""

    async def first_ballot(
        self,
        agent: AgentName,
        case: DecisionCase,
        snapshot: EvidenceSnapshot,
    ) -> Ballot: ...

    async def review_ballot(
        self,
        agent: AgentName,
        case: DecisionCase,
        snapshot: EvidenceSnapshot,
        previous_ballot: Ballot,
        peer_summaries: tuple[PeerBallotSummary, ...],
    ) -> Ballot: ...

