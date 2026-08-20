"""Idempotency, retry, and audit records for model invocations."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime
from enum import StrEnum
from typing import Any, AsyncContextManager, AsyncIterator, ClassVar, Protocol
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from magi.domain import AgentName
from magi.domain.models import MagiModel


class InvocationStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REUSED = "reused"


class ModelTokenUsage(MagiModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_total(self) -> ModelTokenUsage:
        if self.total_tokens < self.input_tokens + self.output_tokens:
            raise ValueError("total_tokens cannot be smaller than input plus output")
        return self


class ModelInvocationRecord(MagiModel):
    """Sanitized append-only record for one provider attempt or cache reuse."""

    invocation_id: UUID = Field(default_factory=uuid4)
    idempotency_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    prompt_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    decision_id: UUID
    decision_version: int = Field(ge=1)
    agent: AgentName
    round: int = Field(ge=1, le=2)
    attempt: int = Field(ge=0)
    status: InvocationStatus
    model_name: str = Field(min_length=1, max_length=200)
    started_at: datetime
    completed_at: datetime
    latency_ms: int = Field(ge=0)
    usage: ModelTokenUsage = Field(default_factory=ModelTokenUsage)
    error_type: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def validate_record(self) -> ModelInvocationRecord:
        if self.started_at.tzinfo is None or self.completed_at.tzinfo is None:
            raise ValueError("invocation timestamps must be timezone-aware")
        if self.completed_at < self.started_at:
            raise ValueError("completed_at cannot precede started_at")
        if self.status is InvocationStatus.FAILED and not self.error_type:
            raise ValueError("failed invocations require an error_type")
        if self.status is not InvocationStatus.FAILED and self.error_type is not None:
            raise ValueError("successful or reused invocations cannot contain an error_type")
        if self.status is InvocationStatus.REUSED and self.attempt != 0:
            raise ValueError("reused invocations must use attempt zero")
        return self


class InvocationLedger(Protocol):
    """Persistence boundary implemented in memory and PostgreSQL."""

    def guard(self, idempotency_key: str) -> AsyncContextManager[None]: ...

    async def get_ballot(self, idempotency_key: str) -> Mapping[str, Any] | None: ...

    async def append(
        self,
        record: ModelInvocationRecord,
        ballot: Mapping[str, Any] | None = None,
    ) -> None: ...

    async def records_for(
        self, decision_id: UUID, decision_version: int
    ) -> tuple[ModelInvocationRecord, ...]: ...


class InMemoryInvocationLedger:
    """Process-local append-only ledger for tests and development."""

    def __init__(self) -> None:
        self._records: list[ModelInvocationRecord] = []
        self._ballots: dict[str, dict[str, Any]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    @property
    def records(self) -> tuple[ModelInvocationRecord, ...]:
        return tuple(self._records)

    @asynccontextmanager
    async def guard(self, idempotency_key: str) -> AsyncIterator[None]:
        lock = self._locks.setdefault(idempotency_key, asyncio.Lock())
        async with lock:
            yield

    async def get_ballot(self, idempotency_key: str) -> Mapping[str, Any] | None:
        ballot = self._ballots.get(idempotency_key)
        return deepcopy(ballot) if ballot is not None else None

    async def append(
        self,
        record: ModelInvocationRecord,
        ballot: Mapping[str, Any] | None = None,
    ) -> None:
        self._records.append(record)
        if ballot is not None:
            if record.status is not InvocationStatus.SUCCEEDED:
                raise ValueError("only successful invocations may store a ballot")
            self._ballots.setdefault(record.idempotency_key, deepcopy(dict(ballot)))

    async def records_for(
        self, decision_id: UUID, decision_version: int
    ) -> tuple[ModelInvocationRecord, ...]:
        return tuple(
            record
            for record in self._records
            if record.decision_id == decision_id
            and record.decision_version == decision_version
        )


class RetryPolicy(MagiModel):
    """Retry only failures documented as transient provider conditions."""

    max_attempts: int = Field(default=2, ge=1, le=5)
    initial_backoff_seconds: float = Field(default=0.25, ge=0, le=30)
    multiplier: float = Field(default=2.0, ge=1, le=10)
    max_backoff_seconds: float = Field(default=8.0, ge=0, le=120)

    _TRANSIENT_NAMES: ClassVar[frozenset[str]] = frozenset(
        {
            "APIConnectionError",
            "APITimeoutError",
            "InternalServerError",
            "RateLimitError",
            "UnprocessableEntityError",
        }
    )

    def is_transient(self, error: BaseException) -> bool:
        if isinstance(error, (ConnectionError, TimeoutError)):
            return True
        return any(
            error_type.__name__ in self._TRANSIENT_NAMES
            for error_type in type(error).__mro__
        )

    def delay_seconds(self, error: BaseException, attempt: int) -> float:
        retry_after = self._retry_after(error)
        if retry_after is not None:
            return min(retry_after, self.max_backoff_seconds)
        calculated = self.initial_backoff_seconds * self.multiplier ** max(attempt - 1, 0)
        return min(calculated, self.max_backoff_seconds)

    @staticmethod
    def _retry_after(error: BaseException) -> float | None:
        response = getattr(error, "response", None)
        headers = getattr(response, "headers", None)
        if not headers:
            return None
        value = headers.get("retry-after") or headers.get("Retry-After")
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return max(parsed, 0)
