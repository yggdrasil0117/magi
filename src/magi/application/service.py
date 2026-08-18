"""Application service coordinating LangGraph without exposing checkpoint internals."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from magi.domain import (
    ConstraintValidation,
    DecisionCase,
    DecisionState,
    EvidenceSnapshot,
    ProtocolViolation,
)
from magi.orchestration import ConfirmationPayload, RunPayload, decision_thread_id

from .models import DecisionView, DecisionViewProjector


class DecisionWorkflowNotFound(LookupError):
    """Raised when no checkpoint exists for a decision version."""


class DecisionWorkflowConflict(RuntimeError):
    """Raised when a command conflicts with the saved workflow state."""


class DecisionGraph(Protocol):
    async def ainvoke(
        self,
        input: object,
        config: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]: ...

    async def aget_state(
        self,
        config: Mapping[str, Any],
        *,
        subgraphs: bool = False,
    ) -> object: ...


class DecisionApplicationService:
    """Single execution boundary consumed later by HTTP, terminal, and Web clients."""

    def __init__(
        self,
        graph: DecisionGraph,
        *,
        projector: DecisionViewProjector | None = None,
    ) -> None:
        self._graph = graph
        self._projector = projector or DecisionViewProjector()

    async def wait_for_confirmation(
        self,
        case: DecisionCase,
        snapshot: EvidenceSnapshot,
        constraint_validations: Sequence[ConstraintValidation] = (),
    ) -> DecisionView:
        if case.confirmed_at is not None:
            raise DecisionWorkflowConflict("a prepared case must not be pre-confirmed")
        self._validate_snapshot(case, snapshot)
        config = self._config(case.decision_id, case.version)
        saved = await self._graph.aget_state(config)
        saved_values = self._values(saved)
        if saved_values:
            saved_case = DecisionCase.model_validate(saved_values["case"])
            saved_snapshot = EvidenceSnapshot.model_validate(saved_values["snapshot"])
            saved_validations = tuple(
                ConstraintValidation.model_validate(payload)
                for payload in saved_values.get("constraint_validations", ())
            )
            if (
                saved_case != case
                or saved_snapshot != snapshot
                or saved_validations != tuple(constraint_validations)
            ):
                raise DecisionWorkflowConflict(
                    "the decision version already has different prepared inputs"
                )
            return self._projector.project(saved_values)

        initial_state = {
            "case": case.model_dump(mode="json"),
            "snapshot": snapshot.model_dump(mode="json"),
            "constraint_validations": [
                validation.model_dump(mode="json")
                for validation in constraint_validations
            ],
            "first_ballots": [],
            "review_ballots": [],
        }
        state = await self._graph.ainvoke(initial_state, config=config)
        view = self._projector.project(state)
        if not view.awaiting_confirmation:
            raise ProtocolViolation("workflow did not pause for user confirmation")
        return view

    async def confirm(
        self,
        decision_id: UUID,
        version: int,
        *,
        confirmed_at: datetime,
    ) -> DecisionView:
        confirmation = ConfirmationPayload(
            confirmed=True,
            confirmed_at=confirmed_at,
        )
        saved, _, existing = await self._load(decision_id, version)
        if existing.state is DecisionState.CANCELLED:
            raise DecisionWorkflowConflict(
                "a cancelled decision cannot be confirmed"
            )
        if existing.terminal or existing.awaiting_run:
            return existing
        self._require_interrupt(saved, "confirm_case")
        return await self._invoke_resume(
            decision_id,
            version,
            confirmation.model_dump(mode="json"),
        )

    async def run(self, decision_id: UUID, version: int) -> DecisionView:
        saved, _, existing = await self._load(decision_id, version)
        if existing.state is DecisionState.CANCELLED:
            raise DecisionWorkflowConflict("a cancelled decision cannot be run")
        if existing.terminal:
            return existing
        if not existing.awaiting_run:
            raise DecisionWorkflowConflict(
                "decision workflow is not ready to run"
            )
        self._require_interrupt(saved, "await_run")
        return await self._invoke_resume(
            decision_id,
            version,
            RunPayload(start=True).model_dump(mode="json"),
        )

    async def confirm_and_run(
        self,
        decision_id: UUID,
        version: int,
        *,
        confirmed_at: datetime,
    ) -> DecisionView:
        await self.confirm(
            decision_id,
            version,
            confirmed_at=confirmed_at,
        )
        return await self.run(decision_id, version)

    async def cancel(
        self,
        decision_id: UUID,
        version: int,
        *,
        reason: str | None = None,
    ) -> DecisionView:
        saved, _, existing = await self._load(decision_id, version)
        if existing.state is DecisionState.CANCELLED:
            return existing
        if existing.terminal:
            raise DecisionWorkflowConflict(
                "a terminal decision cannot be cancelled"
            )
        next_nodes = tuple(getattr(saved, "next", ()))
        if next_nodes == ("confirm_case",):
            payload = ConfirmationPayload(
                confirmed=False,
                reason=reason,
            ).model_dump(mode="json")
        elif next_nodes == ("await_run",):
            payload = RunPayload(
                start=False,
                reason=reason,
            ).model_dump(mode="json")
        else:
            raise DecisionWorkflowConflict(
                "decision workflow cannot be cancelled at its current stage"
            )
        self._require_interrupt(saved, next_nodes[0])
        return await self._invoke_resume(decision_id, version, payload)

    async def get(self, decision_id: UUID, version: int) -> DecisionView:
        saved = await self._graph.aget_state(self._config(decision_id, version))
        values = self._values(saved)
        if not values:
            raise DecisionWorkflowNotFound(
                f"decision workflow {decision_id}:{version} was not found"
            )
        self._validate_saved_identity(values, decision_id, version)
        return self._projector.project(values)

    async def _load(
        self,
        decision_id: UUID,
        version: int,
    ) -> tuple[object, dict[str, Any], DecisionView]:
        config = self._config(decision_id, version)
        saved = await self._graph.aget_state(config)
        values = self._values(saved)
        if not values:
            raise DecisionWorkflowNotFound(
                f"decision workflow {decision_id}:{version} was not found"
            )
        self._validate_saved_identity(values, decision_id, version)
        return saved, values, self._projector.project(values)

    @staticmethod
    def _require_interrupt(saved: object, node_name: str) -> None:
        next_nodes = tuple(getattr(saved, "next", ()))
        interrupts = tuple(getattr(saved, "interrupts", ()))
        if next_nodes != (node_name,) or not interrupts:
            raise DecisionWorkflowConflict(
                f"decision workflow is not waiting at {node_name}"
            )

    async def _invoke_resume(
        self,
        decision_id: UUID,
        version: int,
        payload: Mapping[str, Any],
    ) -> DecisionView:
        from langgraph.types import Command

        state = await self._graph.ainvoke(
            Command(resume=dict(payload)),
            config=self._config(decision_id, version),
        )
        return self._projector.project(state)

    @staticmethod
    def _config(decision_id: UUID, version: int) -> dict[str, Any]:
        return {
            "configurable": {
                "thread_id": decision_thread_id(decision_id, version),
            }
        }

    @staticmethod
    def _values(snapshot: object) -> dict[str, Any]:
        values = getattr(snapshot, "values", {})
        return dict(values) if isinstance(values, Mapping) else {}

    @staticmethod
    def _validate_snapshot(case: DecisionCase, snapshot: EvidenceSnapshot) -> None:
        if (
            snapshot.decision_id != case.decision_id
            or snapshot.decision_version != case.version
        ):
            raise DecisionWorkflowConflict(
                "evidence snapshot does not match the prepared decision"
            )

    @staticmethod
    def _validate_saved_identity(
        values: dict[str, Any],
        decision_id: UUID,
        version: int,
    ) -> None:
        case = DecisionCase.model_validate(values["case"])
        if case.decision_id != decision_id or case.version != version:
            raise ProtocolViolation("checkpoint identity does not match its thread")
