"""Client-safe contracts for durable asynchronous decision operations."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Any, AsyncContextManager, Literal, Protocol
from uuid import UUID

from pydantic import Field, model_validator

from magi.domain.models import MagiModel
from magi.domain import DataClassification
from .models import DecisionView


class OperationIdempotencyConflict(RuntimeError):
    """Raised when an operation key is reused with another request."""


class OperationLeaseLost(RuntimeError):
    """Raised when a stale worker attempts to mutate an operation."""


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

    async def inbox(
        self,
        *,
        principal: str,
        limit: int = 50,
    ) -> OperationInbox: ...

    async def decisions(self, *, principal: str, limit: int = 50) -> DecisionCatalog: ...

    async def versions(
        self, *, principal: str, decision_id: UUID
    ) -> DecisionHistory | None: ...

    async def record_decision(
        self, *, principal: str, view: DecisionView, updated_at: datetime
    ) -> None: ...


class OperationQueue(Protocol):
    def claim(
        self,
        *,
        worker_id: str,
        claimed_at: datetime,
        lease_seconds: int,
    ) -> AsyncContextManager[OperationLease | None]: ...

    async def renew(
        self,
        lease: OperationLease,
        *,
        worker_id: str,
        renewed_at: datetime,
        lease_seconds: int,
    ) -> OperationLease: ...

    async def advance(
        self,
        lease: OperationLease,
        *,
        worker_id: str,
        stage: OperationStage,
        message_code: str,
        occurred_at: datetime,
    ) -> OperationReceipt: ...

    async def succeed(
        self,
        lease: OperationLease,
        *,
        worker_id: str,
        result: Any,
        completed_at: datetime,
    ) -> OperationReceipt: ...

    async def fail(
        self,
        lease: OperationLease,
        *,
        worker_id: str,
        failure_code: str,
        completed_at: datetime,
    ) -> OperationReceipt: ...


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


class OperationLease(MagiModel):
    """Private execution capability protected by a monotonically increasing token."""

    operation_id: UUID
    kind: OperationKind
    decision_id: UUID
    decision_version: int = Field(ge=1)
    classification: DataClassification
    request_payload: dict[str, Any]
    fencing_token: int = Field(ge=1)
    lease_expires_at: datetime

    @model_validator(mode="after")
    def require_aware_expiry(self) -> OperationLease:
        if self.lease_expires_at.tzinfo is None:
            raise ValueError("operation lease expiry must be timezone-aware")
        return self


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


class OperationInbox(MagiModel):
    """Principal-scoped recent operations and actionable counts."""

    schema_version: Literal["1.0"] = "1.0"
    operations: tuple[OperationReceipt, ...] = ()
    active_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_order(self) -> OperationInbox:
        previous: datetime | None = None
        identities: set[UUID] = set()
        for operation in self.operations:
            if operation.operation_id in identities:
                raise ValueError("operation inbox contains duplicate identities")
            identities.add(operation.operation_id)
            if previous is not None and operation.updated_at > previous:
                raise ValueError("operation inbox must be newest first")
            previous = operation.updated_at
        return self


class DecisionCatalogEntry(MagiModel):
    decision_id: UUID
    version: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)
    state: str = Field(min_length=1, max_length=80)
    risk_level: str = Field(min_length=1, max_length=40)
    data_classification: DataClassification
    available_actions: tuple[str, ...] = ()
    updated_at: datetime


class DecisionCatalog(MagiModel):
    schema_version: Literal["1.0"] = "1.0"
    decisions: tuple[DecisionCatalogEntry, ...] = ()
    required_action_count: int = Field(ge=0)


class DecisionHistory(MagiModel):
    schema_version: Literal["1.0"] = "1.0"
    decision_id: UUID
    versions: tuple[DecisionView, ...] = ()

    @model_validator(mode="after")
    def validate_versions(self) -> DecisionHistory:
        previous: int | None = None
        for view in self.versions:
            if view.decision_id != self.decision_id:
                raise ValueError("decision history contains another decision")
            if previous is not None and view.version >= previous:
                raise ValueError("decision history must be newest first")
            previous = view.version
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
