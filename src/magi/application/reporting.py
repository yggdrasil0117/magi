"""Deterministic final-report projection from authoritative MAGI records."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from magi.domain import (
    AgentName,
    ArbitrationResult,
    ArbitrationStatus,
    Ballot,
    DecisionCase,
    MinorityReport,
    ProtocolViolation,
)
from magi.domain.models import MagiModel


class ReviewAudit(MagiModel):
    """Public audit link between one perspective's first and final ballot."""

    agent: AgentName
    first_ballot_id: UUID
    final_ballot_id: UUID
    changed: bool
    reason: str = Field(min_length=1, max_length=2000)


class DecisionReport(MagiModel):
    """Immutable report rendered without another model or mutable vote fields."""

    schema_version: Literal["1.0"] = "1.0"
    decision_id: UUID
    version: int = Field(ge=1)
    status: ArbitrationStatus
    selected_option: str | None = None
    selected_option_label: str | None = None
    vote_count: dict[str, int]
    ballot_count: int = Field(ge=0, le=3)
    majority_rationale: tuple[str, ...] = ()
    minority_report: MinorityReport | None = None
    evidence_refs: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    unresolved_questions: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    conditions: tuple[str, ...] = ()
    recommended_next_step: str = Field(min_length=1, max_length=2000)
    ballot_refs: tuple[UUID, ...]
    review_audit: tuple[ReviewAudit, ...] = ()
    protocol_version: Literal["1.0"] = "1.0"
    rule_version: Literal["1.0"] = "1.0"
    generated_at: datetime

    @model_validator(mode="after")
    def validate_report_shape(self) -> DecisionReport:
        decisive = {ArbitrationStatus.CONSENSUS, ArbitrationStatus.MAJORITY}
        if self.generated_at.tzinfo is None:
            raise ValueError("generated_at must be timezone-aware")
        if self.status in decisive:
            if self.selected_option is None or self.selected_option_label is None:
                raise ValueError("a decisive report requires its selected option")
        elif self.selected_option is not None or self.selected_option_label is not None:
            raise ValueError("a non-decisive report cannot select an option")
        if len(self.ballot_refs) != self.ballot_count:
            raise ValueError("ballot_count must match ballot_refs")
        if len(set(self.ballot_refs)) != len(self.ballot_refs):
            raise ValueError("ballot_refs must be unique")
        if self.status is ArbitrationStatus.MAJORITY and self.minority_report is None:
            raise ValueError("a majority report must preserve its minority report")
        if self.status is not ArbitrationStatus.MAJORITY and self.minority_report is not None:
            raise ValueError("only a majority report can include a minority report")
        return self


class DecisionReportProjector:
    """Build one reproducible report from a case, result, and sealed ballots."""

    def project(
        self,
        case: DecisionCase,
        result: ArbitrationResult,
        first_ballots: Sequence[Ballot],
        final_ballots: Sequence[Ballot],
    ) -> DecisionReport:
        self._validate_identity(case, result, first_ballots, final_ballots)
        ordered_final = tuple(sorted(final_ballots, key=lambda ballot: ballot.agent.value))
        option_labels = {option.id: option.label for option in case.options}
        winner = result.winning_option
        if winner is not None and winner not in option_labels:
            raise ProtocolViolation("arbitration result selected an unknown option")

        winner_ballots = (
            tuple(ballot for ballot in ordered_final if ballot.selected_option == winner)
            if winner is not None
            else ()
        )
        majority_rationale = _unique(
            item for ballot in winner_ballots for item in ballot.rationale_summary
        )
        evidence_refs = _unique(
            item for ballot in ordered_final for item in ballot.evidence_refs
        )
        assumptions = _unique(
            item for ballot in ordered_final for item in ballot.assumptions
        )
        risks = _unique(item for ballot in ordered_final for item in ballot.risks)
        unresolved_questions = _unique(
            (
                *(item for ballot in ordered_final for item in ballot.missing_information),
                *result.required_information,
            )
        )

        return DecisionReport(
            decision_id=case.decision_id,
            version=case.version,
            status=result.status,
            selected_option=winner,
            selected_option_label=option_labels.get(winner),
            vote_count=result.vote_count,
            ballot_count=len(ordered_final),
            majority_rationale=majority_rationale,
            minority_report=result.minority_report,
            evidence_refs=evidence_refs,
            assumptions=assumptions,
            unresolved_questions=unresolved_questions,
            risks=risks,
            conditions=result.conditions,
            recommended_next_step=self._recommended_next_step(
                result,
                option_labels.get(winner),
            ),
            ballot_refs=tuple(ballot.ballot_id for ballot in ordered_final),
            review_audit=self._review_audit(first_ballots, ordered_final),
            rule_version=result.rule_version,
            generated_at=result.created_at,
        )

    @staticmethod
    def _validate_identity(
        case: DecisionCase,
        result: ArbitrationResult,
        first_ballots: Sequence[Ballot],
        final_ballots: Sequence[Ballot],
    ) -> None:
        if result.decision_id != case.decision_id or result.decision_version != case.version:
            raise ProtocolViolation("report result belongs to another decision or version")
        for ballot in (*first_ballots, *final_ballots):
            if ballot.decision_id != case.decision_id or ballot.decision_version != case.version:
                raise ProtocolViolation("report ballot belongs to another decision or version")
        final_refs = tuple(ballot.ballot_id for ballot in final_ballots)
        if len(final_refs) != len(set(final_refs)):
            raise ProtocolViolation("report final ballot IDs must be unique")
        if set(final_refs) != set(result.ballot_refs):
            raise ProtocolViolation("report ballots do not match arbitration ballot references")

    @staticmethod
    def _review_audit(
        first_ballots: Sequence[Ballot],
        final_ballots: Sequence[Ballot],
    ) -> tuple[ReviewAudit, ...]:
        if not final_ballots or final_ballots[0].round == 1:
            if any(ballot.round != 1 for ballot in final_ballots):
                raise ProtocolViolation("final report cannot mix ballot rounds")
            return ()
        if any(ballot.round != 2 for ballot in final_ballots):
            raise ProtocolViolation("final report cannot mix ballot rounds")

        first_by_id = {ballot.ballot_id: ballot for ballot in first_ballots}
        if len(first_by_id) != len(first_ballots):
            raise ProtocolViolation("first-round report ballot IDs must be unique")
        audits: list[ReviewAudit] = []
        for ballot in final_ballots:
            previous = first_by_id.get(ballot.previous_ballot_id)
            if previous is None or previous.agent is not ballot.agent:
                raise ProtocolViolation("review ballot does not match its first-round ballot")
            if not ballot.review_reason:
                raise ProtocolViolation("review ballot is missing its audit reason")
            audits.append(
                ReviewAudit(
                    agent=ballot.agent,
                    first_ballot_id=previous.ballot_id,
                    final_ballot_id=ballot.ballot_id,
                    changed=ballot.changed_from_previous,
                    reason=ballot.review_reason,
                )
            )
        return tuple(audits)

    @staticmethod
    def _recommended_next_step(
        result: ArbitrationResult,
        selected_label: str | None,
    ) -> str:
        if result.status in {ArbitrationStatus.CONSENSUS, ArbitrationStatus.MAJORITY}:
            suffix = " after satisfying the recorded conditions" if result.conditions else ""
            return f"Proceed with {selected_label}{suffix}."
        if result.status is ArbitrationStatus.CONDITIONAL_REJECTION:
            return "Resolve the recorded conditions before reconsidering this decision."
        if result.status is ArbitrationStatus.INSUFFICIENT_INFORMATION:
            return "Collect the required information and create a new decision version."
        if result.status is ArbitrationStatus.UNRESOLVED:
            return "Review the unresolved trade-offs and create a new decision version."
        if result.status is ArbitrationStatus.DEGRADED:
            return "Restore all three perspectives before rerunning a new decision version."
        return "Resolve the failed run before starting a new decision version."


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))
