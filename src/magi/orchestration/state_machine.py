"""Framework-independent lifecycle state machine for a MAGI decision."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from magi.domain.enums import DecisionState
from magi.domain.errors import InvalidStateTransition


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


TERMINAL_STATES = frozenset(
    {
        DecisionState.COMPLETED,
        DecisionState.INSUFFICIENT_INFORMATION,
        DecisionState.DEGRADED,
        DecisionState.FAILED,
        DecisionState.CANCELLED,
    }
)


ALLOWED_TRANSITIONS: dict[DecisionState, frozenset[DecisionState]] = {
    DecisionState.CREATED: frozenset(
        {DecisionState.NORMALIZED, DecisionState.CANCELLED}
    ),
    DecisionState.NORMALIZED: frozenset(
        {DecisionState.WAITING_FOR_USER, DecisionState.CANCELLED}
    ),
    DecisionState.WAITING_FOR_USER: frozenset(
        {DecisionState.EVIDENCE_READY, DecisionState.CANCELLED}
    ),
    DecisionState.EVIDENCE_READY: frozenset(
        {DecisionState.FIRST_BALLOT, DecisionState.CANCELLED}
    ),
    DecisionState.FIRST_BALLOT: frozenset(
        {
            DecisionState.CROSS_REVIEW,
            DecisionState.ARBITRATED,
            DecisionState.INSUFFICIENT_INFORMATION,
            DecisionState.DEGRADED,
            DecisionState.FAILED,
            DecisionState.CANCELLED,
        }
    ),
    DecisionState.CROSS_REVIEW: frozenset(
        {
            DecisionState.ARBITRATED,
            DecisionState.INSUFFICIENT_INFORMATION,
            DecisionState.DEGRADED,
            DecisionState.FAILED,
            DecisionState.CANCELLED,
        }
    ),
    DecisionState.ARBITRATED: frozenset({DecisionState.COMPLETED}),
    DecisionState.COMPLETED: frozenset(),
    DecisionState.INSUFFICIENT_INFORMATION: frozenset(),
    DecisionState.DEGRADED: frozenset(),
    DecisionState.FAILED: frozenset(),
    DecisionState.CANCELLED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class TransitionRecord:
    decision_id: UUID
    from_state: DecisionState
    to_state: DecisionState
    occurred_at: datetime
    reason: str


class DecisionStateMachine:
    """Apply legal lifecycle transitions and retain an in-memory transition record."""

    def __init__(
        self,
        decision_id: UUID,
        initial_state: DecisionState = DecisionState.CREATED,
    ) -> None:
        self.decision_id = decision_id
        self._state = initial_state
        self._history: list[TransitionRecord] = []

    @property
    def state(self) -> DecisionState:
        return self._state

    @property
    def history(self) -> tuple[TransitionRecord, ...]:
        return tuple(self._history)

    @property
    def is_terminal(self) -> bool:
        return self._state in TERMINAL_STATES

    def can_transition(self, target: DecisionState) -> bool:
        return target in ALLOWED_TRANSITIONS[self._state]

    def transition(
        self,
        target: DecisionState,
        *,
        reason: str,
        occurred_at: datetime | None = None,
    ) -> TransitionRecord:
        if not reason.strip():
            raise ValueError("a state transition requires a reason")
        if not self.can_transition(target):
            raise InvalidStateTransition(
                f"cannot transition decision {self.decision_id} "
                f"from {self._state.value} to {target.value}"
            )
        timestamp = occurred_at or _utc_now()
        if timestamp.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        record = TransitionRecord(
            decision_id=self.decision_id,
            from_state=self._state,
            to_state=target,
            occurred_at=timestamp,
            reason=reason.strip(),
        )
        self._history.append(record)
        self._state = target
        return record

