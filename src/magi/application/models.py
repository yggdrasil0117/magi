"""Client-safe application projections shared by every MAGI interface."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from magi.domain import (
    ArbitrationResult,
    ArbitrationStatus,
    Ballot,
    DataClassification,
    DecisionCase,
    DecisionState,
    EvidenceItem,
    EvidenceSnapshot,
    ProtocolViolation,
)
from magi.domain.models import MagiModel

from .reporting import DecisionReport, DecisionReportProjector


class DecisionView(MagiModel):
    """Sanitized source of truth returned to Web, TUI, and CLI clients."""

    schema_version: Literal["1.0"] = "1.0"
    decision_id: UUID
    version: int
    state: DecisionState
    case: DecisionCase
    evidence: tuple[EvidenceItem, ...] = ()
    ballots: tuple[Ballot, ...] = ()
    result: ArbitrationResult | None = None
    report: DecisionReport | None = None
    awaiting_confirmation: bool = False
    awaiting_run: bool = False
    terminal: bool = False
    available_actions: tuple[str, ...] = ()


class DecisionViewProjector:
    """Project checkpoint state without leaking partial votes or restricted evidence."""

    def __init__(self, report_projector: DecisionReportProjector | None = None) -> None:
        self._report_projector = report_projector or DecisionReportProjector()

    def project(self, state: dict[str, Any]) -> DecisionView:
        if "case" not in state:
            raise ProtocolViolation("decision checkpoint does not contain a case")
        case = DecisionCase.model_validate(state["case"])
        snapshot = self._snapshot(state, case)
        result = self._result(state, case)
        ballots = self._released_ballots(state)
        report = self._report(state, case, result, ballots)
        decision_state = self._decision_state(state, result)
        awaiting_confirmation = decision_state is DecisionState.WAITING_FOR_USER
        awaiting_run = decision_state is DecisionState.EVIDENCE_READY
        terminal = decision_state in {
            DecisionState.COMPLETED,
            DecisionState.INSUFFICIENT_INFORMATION,
            DecisionState.DEGRADED,
            DecisionState.FAILED,
            DecisionState.CANCELLED,
        }
        return DecisionView(
            decision_id=case.decision_id,
            version=case.version,
            state=decision_state,
            case=case,
            evidence=self._public_evidence(snapshot),
            ballots=ballots,
            result=result,
            report=report,
            awaiting_confirmation=awaiting_confirmation,
            awaiting_run=awaiting_run,
            terminal=terminal,
            available_actions=self._available_actions(
                awaiting_confirmation,
                awaiting_run,
            ),
        )

    def _report(
        self,
        state: dict[str, Any],
        case: DecisionCase,
        result: ArbitrationResult | None,
        final_ballots: tuple[Ballot, ...],
    ) -> DecisionReport | None:
        if result is None:
            return None
        first_ballots = tuple(
            Ballot.model_validate(payload) for payload in state.get("first_ballots", ())
        )
        return self._report_projector.project(
            case,
            result,
            first_ballots,
            final_ballots,
        )

    @staticmethod
    def _available_actions(
        awaiting_confirmation: bool,
        awaiting_run: bool,
    ) -> tuple[str, ...]:
        if awaiting_confirmation:
            return ("confirm", "cancel")
        if awaiting_run:
            return ("run", "cancel")
        return ()

    @staticmethod
    def _snapshot(state: dict[str, Any], case: DecisionCase) -> EvidenceSnapshot | None:
        payload = state.get("snapshot")
        if payload is None:
            return None
        snapshot = EvidenceSnapshot.model_validate(payload)
        if (
            snapshot.decision_id != case.decision_id
            or snapshot.decision_version != case.version
        ):
            raise ProtocolViolation("checkpoint evidence does not match its decision")
        return snapshot

    @staticmethod
    def _result(
        state: dict[str, Any],
        case: DecisionCase,
    ) -> ArbitrationResult | None:
        payload = state.get("result")
        if payload is None:
            return None
        result = ArbitrationResult.model_validate(payload)
        if (
            result.decision_id != case.decision_id
            or result.decision_version != case.version
        ):
            raise ProtocolViolation("checkpoint result does not match its decision")
        return result

    @staticmethod
    def _public_evidence(
        snapshot: EvidenceSnapshot | None,
    ) -> tuple[EvidenceItem, ...]:
        if snapshot is None:
            return ()
        return tuple(
            item
            for item in snapshot.evidence
            if item.classification is not DataClassification.RESTRICTED
        )

    @staticmethod
    def _released_ballots(state: dict[str, Any]) -> tuple[Ballot, ...]:
        if state.get("result") is not None:
            payloads = state.get("review_ballots") or state.get("first_ballots", ())
        elif state.get("first_assessment") is not None:
            payloads = state.get("first_ballots", ())
        else:
            return ()
        return tuple(Ballot.model_validate(payload) for payload in payloads)

    @staticmethod
    def _decision_state(
        state: dict[str, Any],
        result: ArbitrationResult | None,
    ) -> DecisionState:
        if state.get("cancelled"):
            return DecisionState.CANCELLED
        if result is not None:
            terminal_states = {
                ArbitrationStatus.INSUFFICIENT_INFORMATION: (
                    DecisionState.INSUFFICIENT_INFORMATION
                ),
                ArbitrationStatus.DEGRADED: DecisionState.DEGRADED,
                ArbitrationStatus.FAILED: DecisionState.FAILED,
            }
            return terminal_states.get(result.status, DecisionState.COMPLETED)
        phase = state.get("phase", DecisionState.CREATED.value)
        direct = {
            DecisionState.CREATED.value: DecisionState.CREATED,
            DecisionState.NORMALIZED.value: DecisionState.NORMALIZED,
            DecisionState.WAITING_FOR_USER.value: DecisionState.WAITING_FOR_USER,
            DecisionState.EVIDENCE_READY.value: DecisionState.EVIDENCE_READY,
            DecisionState.FIRST_BALLOT.value: DecisionState.FIRST_BALLOT,
            DecisionState.CROSS_REVIEW.value: DecisionState.CROSS_REVIEW,
        }
        if str(phase) in direct:
            return direct[str(phase)]
        routing_phases = {
            "arbitrate",
            "conditional_rejection",
            "insufficient_information",
            "degraded",
            "failed",
        }
        if str(phase) in routing_phases:
            return DecisionState.FIRST_BALLOT
        raise ProtocolViolation(f"unsupported checkpoint phase: {phase}")
