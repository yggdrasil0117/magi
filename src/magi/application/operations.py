"""Client-safe contracts for durable asynchronous decision operations."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import Field, model_validator

from magi.domain.models import MagiModel
from magi.domain import DataClassification


class OperationIdempotencyConflict(RuntimeError):
    """Raised when an operation key is reused with another request."""


class OperationStore(Protocol):
    async def accept(
        self,
        *,
        principal: str,
        idempotency_key: str,
        fingerprint: str,
        kind: OperationKind,
        decision_id: UUID,
        decision_version: int,
        classification: DataClassification,
        request_payload: Mapping[str, Any],
        accepted_at: datetime,
    ) -> OperationReceipt: ...

    async def get(
        self,
        *,
        principal: str,
        operation_id: UUID,
    ) -> OperationReceipt | None: ...

    async def events(
        self,
        *,
        principal: str,
        operation_id: UUID,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> OperationEventPage | None: ...


class OperationKind(StrEnum):
    CREATE_DECISION = "create_decision"
    RUN_DECISION = "run_decision"


class OperationStatus(StrEnum):
    ACCEPTED = "accepted"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class OperationStage(StrEnum):
    QUEUED = "queued"
    COORDINATOR = "coordinator"
    FIRST_BALLOT = "first_ballot"
    CROSS_REVIEW = "cross_review"
    ARBITRATION = "arbitration"
    REPORTING = "reporting"
    COMPLETE = "complete"


class OperationEventType(StrEnum):
    ACCEPTED = "accepted"
    STARTED = "started"
    STAGE_CHANGED = "stage_changed"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class OperationReceipt(MagiModel):
    """Sanitized polling projection returned after durable acceptance."""

    schema_version: Literal["1.0"] = "1.0"
    operation_id: UUID
    kind: OperationKind
    status: OperationStatus
    stage: OperationStage
    decision_id: UUID
    decision_version: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    last_event_sequence: int = Field(ge=1)
    next_poll_after_ms: int | None = Field(default=None, ge=250, le=10_000)
    result_available: bool = False
    failure_code: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        pattern=r"^[a-z][a-z0-9_]*$",
    )

    @model_validator(mode="after")
    def validate_lifecycle(self) -> OperationReceipt:
        for timestamp in (self.created_at, self.updated_at, self.completed_at):
            if timestamp is not None and timestamp.tzinfo is None:
                raise ValueError("operation timestamps must be timezone-aware")
        if self.updated_at < self.created_at:
            raise ValueError("operation update cannot precede creation")
        if self.completed_at is not None and self.completed_at < self.created_at:
            raise ValueError("operation completion cannot precede creation")

        terminal = self.status in {OperationStatus.SUCCEEDED, OperationStatus.FAILED}
        if terminal:
            if self.completed_at is None or self.next_poll_after_ms is not None:
                raise ValueError("terminal operations require completion and no polling hint")
        elif self.completed_at is not None or self.next_poll_after_ms is None:
            raise ValueError("active operations require polling and no completion")

        if self.status is OperationStatus.SUCCEEDED:
            if not self.result_available or self.failure_code is not None:
                raise ValueError("successful operations require a result and no failure")
            if self.stage is not OperationStage.COMPLETE:
                raise ValueError("successful operations must be complete")
        elif self.result_available:
            raise ValueError("only successful operations may publish a result")

        if self.status is OperationStatus.FAILED:
            if self.failure_code is None:
                raise ValueError("failed operations require a sanitized failure code")
        elif self.failure_code is not None:
            raise ValueError("only failed operations may publish a failure code")
        return self


class OperationEvent(MagiModel):
    """Append-only public event without prompts, ballots, or private reasoning."""

    schema_version: Literal["1.0"] = "1.0"
    operation_id: UUID
    sequence: int = Field(ge=1)
    event_type: OperationEventType
    status: OperationStatus
    stage: OperationStage
    occurred_at: datetime
    message_code: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[a-z][a-z0-9_]*$",
    )

    @model_validator(mode="after")
    def validate_event(self) -> OperationEvent:
        if self.occurred_at.tzinfo is None:
            raise ValueError("operation event time must be timezone-aware")
        expected = {
            OperationEventType.ACCEPTED: OperationStatus.ACCEPTED,
            OperationEventType.STARTED: OperationStatus.RUNNING,
            OperationEventType.SUCCEEDED: OperationStatus.SUCCEEDED,
            OperationEventType.FAILED: OperationStatus.FAILED,
        }.get(self.event_type)
        if expected is not None and self.status is not expected:
            raise ValueError("operation event does not match its status")
        if (
            self.event_type is OperationEventType.SUCCEEDED
            and self.stage is not OperationStage.COMPLETE
        ):
            raise ValueError("successful operation event must be complete")
        return self


class OperationEventPage(MagiModel):
    schema_version: Literal["1.0"] = "1.0"
    operation_id: UUID
    after_sequence: int = Field(ge=0)
    events: tuple[OperationEvent, ...] = ()
    next_after_sequence: int = Field(ge=0)
    has_more: bool = False

    @model_validator(mode="after")
    def validate_page(self) -> OperationEventPage:
        previous = self.after_sequence
        for event in self.events:
            if event.operation_id != self.operation_id:
                raise ValueError("operation event identity does not match the page")
            if event.sequence <= previous:
                raise ValueError("operation events must be strictly ordered")
            previous = event.sequence
        if self.next_after_sequence != previous:
            raise ValueError("operation event cursor does not match the page")
        return self


def validate_operation_transition(
    current: OperationStatus,
    target: OperationStatus,
) -> None:
    allowed = {
        OperationStatus.ACCEPTED: {OperationStatus.RUNNING, OperationStatus.FAILED},
        OperationStatus.RUNNING: {
            OperationStatus.RUNNING,
            OperationStatus.SUCCEEDED,
            OperationStatus.FAILED,
        },
        OperationStatus.SUCCEEDED: set(),
        OperationStatus.FAILED: set(),
    }
    if target not in allowed[current]:
        raise ValueError(f"illegal operation transition: {current} -> {target}")
