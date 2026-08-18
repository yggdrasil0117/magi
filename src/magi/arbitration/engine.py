"""Deterministic first-round routing and final arbitration."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from uuid import UUID

from magi.domain.enums import (
    AgentName,
    ArbitrationStatus,
    ConstraintValidationStatus,
    DataClassification,
    DecisionType,
    RiskLevel,
    RoundAction,
    Stance,
)
from magi.domain.errors import (
    CrossReviewRequired,
    DuplicateBallotError,
    ProtocolViolation,
)
from magi.domain.models import (
    ArbitrationResult,
    Ballot,
    ConstraintValidation,
    DecisionCase,
    EvidenceSnapshot,
    MinorityReport,
    RoundAssessment,
)

RULE_VERSION = "1.0"
EXPECTED_AGENTS = frozenset(AgentName)


def _ordered_agents(agents: Iterable[AgentName]) -> tuple[AgentName, ...]:
    return tuple(sorted(agents, key=lambda agent: agent.value))


def _unique_strings(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _validate_context(
    case: DecisionCase,
    snapshot: EvidenceSnapshot,
) -> dict[str, DataClassification]:
    if case.confirmed_at is None:
        raise ProtocolViolation("the decision case must be user-confirmed before voting")
    if case.decision_type not in {
        DecisionType.BOOLEAN,
        DecisionType.SINGLE_CHOICE,
    }:
        raise ProtocolViolation(
            "decision protocol 1.0 arbitration supports boolean and single-choice cases only"
        )
    if snapshot.decision_id != case.decision_id:
        raise ProtocolViolation("the evidence snapshot belongs to another decision")
    if snapshot.decision_version != case.version:
        raise ProtocolViolation("the evidence snapshot version does not match the decision")
    return {item.evidence_id: item.classification for item in snapshot.evidence}


def _validate_ballots(
    case: DecisionCase,
    snapshot: EvidenceSnapshot,
    ballots: Sequence[Ballot],
    *,
    required_round: int | None = None,
) -> int | None:
    evidence_index = _validate_context(case, snapshot)
    evidence_ids = set(evidence_index)
    option_ids = {option.id for option in case.options}

    ballot_ids = [ballot.ballot_id for ballot in ballots]
    if len(ballot_ids) != len(set(ballot_ids)):
        raise DuplicateBallotError("ballot IDs must be unique")

    agent_rounds = [(ballot.agent, ballot.round) for ballot in ballots]
    if len(agent_rounds) != len(set(agent_rounds)):
        raise DuplicateBallotError("only one ballot per agent and round is allowed")

    agents = [ballot.agent for ballot in ballots]
    if len(agents) != len(set(agents)):
        raise DuplicateBallotError("a ballot set cannot mix two rounds for one agent")

    rounds = {ballot.round for ballot in ballots}
    if len(rounds) > 1:
        raise ProtocolViolation("an arbitration ballot set must contain exactly one round")
    actual_round = next(iter(rounds), None)
    if required_round is not None and actual_round not in {None, required_round}:
        raise ProtocolViolation(f"expected round {required_round} ballots")

    claim_ids: set[UUID] = set()
    for ballot in ballots:
        if ballot.decision_id != case.decision_id or ballot.decision_version != case.version:
            raise ProtocolViolation("a ballot belongs to another decision or version")
        if ballot.selected_option is not None and ballot.selected_option not in option_ids:
            raise ProtocolViolation(
                f"ballot {ballot.ballot_id} selected unknown option {ballot.selected_option}"
            )
        unknown_evidence = set(ballot.evidence_refs) - evidence_ids
        if unknown_evidence:
            raise ProtocolViolation(
                f"ballot {ballot.ballot_id} cites unknown evidence: "
                f"{', '.join(sorted(unknown_evidence))}"
            )
        restricted_evidence = {
            evidence_id
            for evidence_id in ballot.evidence_refs
            if evidence_index[evidence_id] is DataClassification.RESTRICTED
        }
        if restricted_evidence:
            raise ProtocolViolation(
                f"ballot {ballot.ballot_id} cites restricted evidence: "
                f"{', '.join(sorted(restricted_evidence))}"
            )
        for claim in ballot.constraint_claims:
            if claim.claim_id in claim_ids:
                raise ProtocolViolation("constraint claim IDs must be unique")
            claim_ids.add(claim.claim_id)
            unknown_claim_evidence = set(claim.evidence_refs) - evidence_ids
            if unknown_claim_evidence:
                raise ProtocolViolation(
                    f"constraint {claim.claim_id} cites unknown evidence: "
                    f"{', '.join(sorted(unknown_claim_evidence))}"
                )
            restricted_claim_evidence = {
                evidence_id
                for evidence_id in claim.evidence_refs
                if evidence_index[evidence_id] is DataClassification.RESTRICTED
            }
            if restricted_claim_evidence:
                raise ProtocolViolation(
                    f"constraint {claim.claim_id} cites restricted evidence: "
                    f"{', '.join(sorted(restricted_claim_evidence))}"
                )

    return actual_round


def _accepted_validations(
    ballots: Sequence[Ballot],
    validations: Sequence[ConstraintValidation],
) -> tuple[ConstraintValidation, ...]:
    submitted_ids = {
        claim.claim_id for ballot in ballots for claim in ballot.constraint_claims
    }
    validation_ids = [validation.claim_id for validation in validations]
    if len(validation_ids) != len(set(validation_ids)):
        raise ProtocolViolation("only one validation per constraint claim is allowed")
    unknown_ids = set(validation_ids) - submitted_ids
    if unknown_ids:
        rendered = ", ".join(sorted(str(claim_id) for claim_id in unknown_ids))
        raise ProtocolViolation(f"validation references unknown constraint claims: {rendered}")
    return tuple(
        validation
        for validation in validations
        if validation.status is ConstraintValidationStatus.ACCEPTED
    )


def _vote_count(case: DecisionCase, ballots: Sequence[Ballot]) -> dict[str, int]:
    counts = Counter(
        ballot.selected_option
        for ballot in ballots
        if ballot.stance is not Stance.ABSTAIN and ballot.selected_option is not None
    )
    return {option.id: counts.get(option.id, 0) for option in case.options}


def _abstentions(ballots: Sequence[Ballot]) -> tuple[AgentName, ...]:
    return _ordered_agents(
        ballot.agent for ballot in ballots if ballot.stance is Stance.ABSTAIN
    )


def assess_first_round(
    case: DecisionCase,
    snapshot: EvidenceSnapshot,
    ballots: Sequence[Ballot],
    validations: Sequence[ConstraintValidation] = (),
) -> RoundAssessment:
    """Choose the protocol route after the secret first ballot."""

    _validate_ballots(case, snapshot, ballots, required_round=1)
    accepted = _accepted_validations(ballots, validations)
    present_agents = {ballot.agent for ballot in ballots}
    missing = _ordered_agents(EXPECTED_AGENTS - present_agents)
    abstaining = _abstentions(ballots)
    counts = _vote_count(case, ballots)

    if len(missing) >= 2:
        action = RoundAction.FAILED
        reason = "two or more perspective agents are unavailable"
    elif len(missing) == 1:
        action = RoundAction.DEGRADED
        reason = "one perspective agent is unavailable; two votes are advisory only"
    elif accepted:
        action = RoundAction.CONDITIONAL_REJECTION
        reason = "a validated hard constraint suspends normal majority processing"
    elif len(abstaining) >= 2:
        action = RoundAction.INSUFFICIENT_INFORMATION
        reason = "two or more perspective agents abstained"
    else:
        nonzero_counts = [count for count in counts.values() if count > 0]
        unanimous = nonzero_counts == [3]
        if unanimous and case.risk_level is not RiskLevel.HIGH:
            action = RoundAction.ARBITRATE
            reason = "low or medium risk first-round vote is unanimous"
        else:
            action = RoundAction.CROSS_REVIEW
            if unanimous:
                reason = "high-risk decisions require cross-review despite unanimity"
            else:
                reason = "the first-round vote is not unanimous"

    return RoundAssessment(
        decision_id=case.decision_id,
        decision_version=case.version,
        action=action,
        reason=reason,
        vote_count=counts,
        missing_agents=missing,
        abstentions=abstaining,
        accepted_constraint_ids=tuple(validation.claim_id for validation in accepted),
    )


def _terminal_result(
    case: DecisionCase,
    ballots: Sequence[Ballot],
    assessment: RoundAssessment,
    accepted: Sequence[ConstraintValidation],
) -> ArbitrationResult:
    status_by_action = {
        RoundAction.CONDITIONAL_REJECTION: ArbitrationStatus.CONDITIONAL_REJECTION,
        RoundAction.INSUFFICIENT_INFORMATION: ArbitrationStatus.INSUFFICIENT_INFORMATION,
        RoundAction.DEGRADED: ArbitrationStatus.DEGRADED,
        RoundAction.FAILED: ArbitrationStatus.FAILED,
    }
    status = status_by_action[assessment.action]
    missing_agent_notes = (
        f"Missing perspective agent: {agent.value}" for agent in assessment.missing_agents
    )
    required_information = _unique_strings(
        item
        for ballot in ballots
        for item in ballot.missing_information
    )
    required_information = _unique_strings((*required_information, *missing_agent_notes))
    return ArbitrationResult(
        decision_id=case.decision_id,
        decision_version=case.version,
        status=status,
        vote_count=assessment.vote_count,
        ballot_refs=tuple(ballot.ballot_id for ballot in ballots),
        unresolved_constraints=tuple(validation.claim_id for validation in accepted),
        conditions=tuple(
            validation.condition_for_reconsideration
            for validation in accepted
            if validation.condition_for_reconsideration
        ),
        required_information=required_information,
    )


def arbitrate(
    case: DecisionCase,
    snapshot: EvidenceSnapshot,
    ballots: Sequence[Ballot],
    validations: Sequence[ConstraintValidation] = (),
) -> ArbitrationResult:
    """Return the final deterministic result or require the mandated cross-review."""

    actual_round = _validate_ballots(case, snapshot, ballots)
    accepted = _accepted_validations(ballots, validations)

    if actual_round in {None, 1}:
        assessment = assess_first_round(case, snapshot, ballots, validations)
        if assessment.action is RoundAction.CROSS_REVIEW:
            raise CrossReviewRequired(assessment.reason)
        if assessment.action is not RoundAction.ARBITRATE:
            return _terminal_result(case, ballots, assessment, accepted)

    present_agents = {ballot.agent for ballot in ballots}
    missing = _ordered_agents(EXPECTED_AGENTS - present_agents)
    abstaining = _abstentions(ballots)
    counts = _vote_count(case, ballots)

    if len(missing) >= 2:
        assessment = RoundAssessment(
            decision_id=case.decision_id,
            decision_version=case.version,
            action=RoundAction.FAILED,
            reason="two or more perspective agents are unavailable",
            vote_count=counts,
            missing_agents=missing,
            abstentions=abstaining,
        )
        return _terminal_result(case, ballots, assessment, ())
    if len(missing) == 1:
        assessment = RoundAssessment(
            decision_id=case.decision_id,
            decision_version=case.version,
            action=RoundAction.DEGRADED,
            reason="one perspective agent is unavailable",
            vote_count=counts,
            missing_agents=missing,
            abstentions=abstaining,
        )
        return _terminal_result(case, ballots, assessment, ())
    if accepted:
        assessment = RoundAssessment(
            decision_id=case.decision_id,
            decision_version=case.version,
            action=RoundAction.CONDITIONAL_REJECTION,
            reason="a validated hard constraint remains unresolved",
            vote_count=counts,
            abstentions=abstaining,
            accepted_constraint_ids=tuple(
                validation.claim_id for validation in accepted
            ),
        )
        return _terminal_result(case, ballots, assessment, accepted)
    if len(abstaining) >= 2:
        assessment = RoundAssessment(
            decision_id=case.decision_id,
            decision_version=case.version,
            action=RoundAction.INSUFFICIENT_INFORMATION,
            reason="two or more perspective agents abstained",
            vote_count=counts,
            abstentions=abstaining,
        )
        return _terminal_result(case, ballots, assessment, ())

    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    winning_option, winning_count = ranked[0]
    ballot_refs = tuple(ballot.ballot_id for ballot in ballots)
    required_information = _unique_strings(
        item for ballot in ballots for item in ballot.missing_information
    )

    if winning_count == 3:
        return ArbitrationResult(
            decision_id=case.decision_id,
            decision_version=case.version,
            status=ArbitrationStatus.CONSENSUS,
            winning_option=winning_option,
            vote_count=counts,
            ballot_refs=ballot_refs,
            required_information=required_information,
        )

    if winning_count == 2:
        dissenting = next(
            ballot
            for ballot in ballots
            if ballot.selected_option != winning_option or ballot.stance is Stance.ABSTAIN
        )
        return ArbitrationResult(
            decision_id=case.decision_id,
            decision_version=case.version,
            status=ArbitrationStatus.MAJORITY,
            winning_option=winning_option,
            vote_count=counts,
            ballot_refs=ballot_refs,
            minority_report=MinorityReport(
                agent=dissenting.agent,
                selected_option=dissenting.selected_option,
                stance=dissenting.stance,
                rationale_summary=dissenting.rationale_summary,
            ),
            required_information=required_information,
        )

    return ArbitrationResult(
        decision_id=case.decision_id,
        decision_version=case.version,
        status=ArbitrationStatus.UNRESOLVED,
        vote_count=counts,
        ballot_refs=ballot_refs,
        required_information=required_information,
    )


class DeterministicArbiter:
    """Small object facade for dependency injection and later LangGraph nodes."""

    rule_version = RULE_VERSION

    def assess_first_round(
        self,
        case: DecisionCase,
        snapshot: EvidenceSnapshot,
        ballots: Sequence[Ballot],
        validations: Sequence[ConstraintValidation] = (),
    ) -> RoundAssessment:
        return assess_first_round(case, snapshot, ballots, validations)

    def arbitrate(
        self,
        case: DecisionCase,
        snapshot: EvidenceSnapshot,
        ballots: Sequence[Ballot],
        validations: Sequence[ConstraintValidation] = (),
    ) -> ArbitrationResult:
        return arbitrate(case, snapshot, ballots, validations)
