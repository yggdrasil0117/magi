"""Pure workflow nodes used by the LangGraph builder and M2a tests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from pydantic import Field, model_validator

from magi.agents import PeerBallotSummary, PerspectiveExecutionError, PerspectiveRunner
from magi.arbitration import DeterministicArbiter
from magi.domain import (
    AgentName,
    Ballot,
    ConstraintValidation,
    DecisionCase,
    EvidenceSnapshot,
    ProtocolViolation,
    RoundAction,
)
from magi.domain.models import MagiModel

from .graph_state import MagiGraphState


def _json_record(record: MagiModel) -> dict[str, Any]:
    return record.model_dump(mode="json")


class ConfirmationPayload(MagiModel):
    confirmed: bool
    confirmed_at: datetime | None = None
    reason: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def require_confirmation_time(self) -> ConfirmationPayload:
        if self.confirmed and self.confirmed_at is None:
            raise ValueError("confirmed decisions require confirmed_at")
        if (
            self.confirmed
            and self.confirmed_at is not None
            and self.confirmed_at.tzinfo is None
        ):
            raise ValueError("confirmed_at must be timezone-aware")
        return self


class RunPayload(MagiModel):
    start: bool
    reason: str | None = Field(default=None, max_length=2000)


class MagiWorkflowNodes:
    """Keep node behavior testable without importing LangGraph."""

    def __init__(
        self,
        runner: PerspectiveRunner,
        arbiter: DeterministicArbiter | None = None,
    ) -> None:
        self.runner = runner
        self.arbiter = arbiter or DeterministicArbiter()

    def prepare_case(self, state: MagiGraphState) -> dict[str, Any]:
        case = DecisionCase.model_validate(state["case"])
        return {"case": _json_record(case), "phase": "waiting_for_user"}

    def apply_confirmation(
        self,
        state: MagiGraphState,
        resume_value: Mapping[str, Any],
    ) -> dict[str, Any]:
        confirmation = ConfirmationPayload.model_validate(resume_value)
        if not confirmation.confirmed:
            return {"cancelled": True, "phase": "cancelled"}

        case_payload = dict(state["case"])
        case_payload["confirmed_at"] = confirmation.confirmed_at
        case = DecisionCase.model_validate(case_payload)
        return {
            "case": _json_record(case),
            "cancelled": False,
            "phase": "evidence_ready",
        }

    def validate_evidence(self, state: MagiGraphState) -> dict[str, Any]:
        case = DecisionCase.model_validate(state["case"])
        snapshot = EvidenceSnapshot.model_validate(state["snapshot"])
        if case.confirmed_at is None:
            raise ProtocolViolation("evidence cannot be opened before user confirmation")
        if snapshot.decision_id != case.decision_id:
            raise ProtocolViolation("evidence snapshot belongs to another decision")
        if snapshot.decision_version != case.version:
            raise ProtocolViolation("evidence snapshot version does not match the decision")
        return {"snapshot": _json_record(snapshot), "phase": "evidence_ready"}

    @staticmethod
    def apply_run_command(
        state: MagiGraphState,
        resume_value: Mapping[str, Any],
    ) -> dict[str, Any]:
        command = RunPayload.model_validate(resume_value)
        if not command.start:
            return {"cancelled": True, "phase": "cancelled"}
        return {"cancelled": False, "phase": "evidence_ready"}

    @staticmethod
    def route_after_run(state: MagiGraphState) -> str:
        return "cancelled" if state.get("cancelled") else "continue"

    @staticmethod
    def begin_first(state: MagiGraphState) -> dict[str, Any]:
        return {"phase": "first_ballot"}

    async def run_first_ballot(
        self,
        agent: AgentName,
        state: MagiGraphState,
    ) -> dict[str, Any]:
        case = DecisionCase.model_validate(state["case"])
        snapshot = EvidenceSnapshot.model_validate(state["snapshot"])
        ballot = await self.runner.first_ballot(agent, case, snapshot)
        self._validate_runner_ballot(ballot, agent, case, expected_round=1)
        return {"first_ballots": [_json_record(ballot)]}

    def assess_first(self, state: MagiGraphState) -> dict[str, Any]:
        case, snapshot = self._case_and_snapshot(state)
        ballots = self._ballots(state.get("first_ballots", ()))
        validations = self._validations(state)
        assessment = self.arbiter.assess_first_round(
            case,
            snapshot,
            ballots,
            validations,
        )
        return {
            "first_assessment": _json_record(assessment),
            "phase": assessment.action.value,
        }

    @staticmethod
    def route_after_first(state: MagiGraphState) -> str:
        assessment = state.get("first_assessment")
        if not assessment:
            raise ProtocolViolation("first-round assessment is missing")
        action = RoundAction(assessment["action"])
        return "cross_review" if action is RoundAction.CROSS_REVIEW else "arbitrate"

    @staticmethod
    def begin_review(state: MagiGraphState) -> dict[str, Any]:
        return {"phase": "cross_review"}

    async def run_review_ballot(
        self,
        agent: AgentName,
        state: MagiGraphState,
    ) -> dict[str, Any]:
        case, snapshot = self._case_and_snapshot(state)
        first_ballots = self._ballots(state.get("first_ballots", ()))
        previous = self._ballot_for(first_ballots, agent)
        peer_summaries = tuple(
            PeerBallotSummary.from_ballot(ballot)
            for ballot in first_ballots
            if ballot.agent is not agent
        )
        ballot = await self.runner.review_ballot(
            agent,
            case,
            snapshot,
            previous,
            peer_summaries,
        )
        self._validate_runner_ballot(ballot, agent, case, expected_round=2)
        if ballot.previous_ballot_id != previous.ballot_id:
            raise PerspectiveExecutionError(
                f"{agent.value} review ballot references the wrong first ballot"
            )
        return {"review_ballots": [_json_record(ballot)]}

    def arbitrate(self, state: MagiGraphState) -> dict[str, Any]:
        case, snapshot = self._case_and_snapshot(state)
        review_payloads = state.get("review_ballots", ())
        ballot_payloads = review_payloads or state.get("first_ballots", ())
        ballots = self._ballots(ballot_payloads)
        result = self.arbiter.arbitrate(
            case,
            snapshot,
            ballots,
            self._validations(state),
        )
        return {"result": _json_record(result), "phase": "completed"}

    @staticmethod
    def route_after_confirmation(state: MagiGraphState) -> str:
        return "cancelled" if state.get("cancelled") else "continue"

    @staticmethod
    def mark_cancelled(state: MagiGraphState) -> dict[str, Any]:
        return {"cancelled": True, "phase": "cancelled"}

    @staticmethod
    def _ballots(payloads: Sequence[Mapping[str, Any]]) -> tuple[Ballot, ...]:
        return tuple(Ballot.model_validate(payload) for payload in payloads)

    @staticmethod
    def _validations(state: MagiGraphState) -> tuple[ConstraintValidation, ...]:
        return tuple(
            ConstraintValidation.model_validate(payload)
            for payload in state.get("constraint_validations", ())
        )

    @staticmethod
    def _case_and_snapshot(
        state: MagiGraphState,
    ) -> tuple[DecisionCase, EvidenceSnapshot]:
        return (
            DecisionCase.model_validate(state["case"]),
            EvidenceSnapshot.model_validate(state["snapshot"]),
        )

    @staticmethod
    def _ballot_for(ballots: Sequence[Ballot], agent: AgentName) -> Ballot:
        matches = [ballot for ballot in ballots if ballot.agent is agent]
        if len(matches) != 1:
            raise ProtocolViolation(
                f"expected one first ballot for {agent.value}, found {len(matches)}"
            )
        return matches[0]

    @staticmethod
    def _validate_runner_ballot(
        ballot: Ballot,
        agent: AgentName,
        case: DecisionCase,
        *,
        expected_round: int,
    ) -> None:
        if ballot.agent is not agent or ballot.round != expected_round:
            raise PerspectiveExecutionError(
                f"{agent.value} runner returned a ballot outside its assignment"
            )
        if ballot.decision_id != case.decision_id or ballot.decision_version != case.version:
            raise PerspectiveExecutionError(
                f"{agent.value} runner returned a ballot for another decision"
            )
