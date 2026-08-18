"""Command idempotency boundary used by transport adapters."""

from __future__ import annotations

import asyncio
import hashlib
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from .models import DecisionView


class CommandIdempotencyConflict(RuntimeError):
    """Raised when one key is reused for a different command payload."""


class CommandIdempotencyStore(Protocol):
    async def execute(
        self,
        *,
        principal: str,
        idempotency_key: str,
        fingerprint: str,
        operation: Callable[[], Awaitable[DecisionView]],
    ) -> DecisionView: ...


@dataclass(frozen=True, slots=True)
class _CommandResult:
    fingerprint: str
    view: DecisionView


class InMemoryCommandIdempotencyStore:
    """Bounded process-local command cache with fixed lock sharding."""

    def __init__(self, *, max_entries: int = 2048, lock_shards: int = 64) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        if lock_shards < 1:
            raise ValueError("lock_shards must be positive")
        self._max_entries = max_entries
        self._results: OrderedDict[str, _CommandResult] = OrderedDict()
        self._locks = tuple(asyncio.Lock() for _ in range(lock_shards))

    async def execute(
        self,
        *,
        principal: str,
        idempotency_key: str,
        fingerprint: str,
        operation: Callable[[], Awaitable[DecisionView]],
    ) -> DecisionView:
        storage_key = self._storage_key(principal, idempotency_key)
        lock = self._locks[int(storage_key[:8], 16) % len(self._locks)]
        async with lock:
            existing = self._results.get(storage_key)
            if existing is not None:
                if existing.fingerprint != fingerprint:
                    raise CommandIdempotencyConflict(
                        "idempotency key was already used for another command"
                    )
                self._results.move_to_end(storage_key)
                return existing.view

            view = await operation()
            self._results[storage_key] = _CommandResult(
                fingerprint=fingerprint,
                view=view,
            )
            self._results.move_to_end(storage_key)
            while len(self._results) > self._max_entries:
                self._results.popitem(last=False)
            return view

    @staticmethod
    def _storage_key(principal: str, idempotency_key: str) -> str:
        material = f"{principal}\0{idempotency_key}".encode("utf-8")
        return hashlib.sha256(material).hexdigest()
