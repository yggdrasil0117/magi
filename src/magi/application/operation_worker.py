"""Recoverable background execution for durable decision operations."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from magi.domain.models import utc_now

from .models import DecisionView
from .operations import (
    OperationKind,
    OperationLease,
    OperationLeaseLost,
    OperationQueue,
    OperationStage,
)
from .preparation import DecisionPreparationRequest
from .service import DecisionApplicationService


class OperationExecutor(Protocol):
    async def execute(self, lease: OperationLease) -> DecisionView: ...


class DecisionOperationExecutor:
    """Translate durable payloads into the existing application service boundary."""

    def __init__(self, service: DecisionApplicationService) -> None:
        self._service = service

    async def execute(self, lease: OperationLease) -> DecisionView:
        if lease.kind is OperationKind.CREATE_DECISION:
            request = DecisionPreparationRequest.model_validate(lease.request_payload)
            if request.decision_id != lease.decision_id:
                raise ValueError("operation payload decision identity does not match")
            return await self._service.prepare(request)
        return await self._service.run(lease.decision_id, lease.decision_version)


class OperationWorker:
    """Claim at most one operation and keep its execution capability alive."""

    def __init__(
        self,
        queue: OperationQueue,
        executor: OperationExecutor,
        *,
        worker_id: str,
        lease_seconds: int = 60,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if not worker_id.strip():
            raise ValueError("operation worker id is required")
        if lease_seconds < 3:
            raise ValueError("operation lease must be at least three seconds")
        self._queue = queue
        self._executor = executor
        self._worker_id = worker_id
        self._lease_seconds = lease_seconds
        self._clock = clock

    async def run_once(self) -> bool:
        async with self._queue.claim(
            worker_id=self._worker_id,
            claimed_at=self._clock(),
            lease_seconds=self._lease_seconds,
        ) as lease:
            if lease is None:
                return False
            heartbeat = asyncio.create_task(self._heartbeat(lease))
            try:
                result = await self._executor.execute(lease)
                await self._queue.advance(
                    lease,
                    worker_id=self._worker_id,
                    stage=OperationStage.REPORTING,
                    message_code="operation_reporting",
                    occurred_at=self._clock(),
                )
                await self._queue.succeed(
                    lease,
                    worker_id=self._worker_id,
                    result=result,
                    completed_at=self._clock(),
                )
            except (asyncio.CancelledError, OperationLeaseLost):
                raise
            except Exception:
                await self._queue.fail(
                    lease,
                    worker_id=self._worker_id,
                    failure_code="operation_execution_failed",
                    completed_at=self._clock(),
                )
            finally:
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)
            return True

    async def run_forever(self, *, idle_seconds: float = 0.5) -> None:
        if idle_seconds <= 0:
            raise ValueError("operation worker idle interval must be positive")
        while True:
            worked = await self.run_once()
            if not worked:
                await asyncio.sleep(idle_seconds)

    async def _heartbeat(self, lease: OperationLease) -> None:
        while True:
            await asyncio.sleep(self._lease_seconds / 3)
            await self._queue.renew(
                lease,
                worker_id=self._worker_id,
                renewed_at=self._clock(),
                lease_seconds=self._lease_seconds,
            )
