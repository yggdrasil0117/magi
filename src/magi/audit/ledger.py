"""Hash-chained canonical decision audit records and reconstruction."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Literal, Protocol
from uuid import UUID, uuid5

from pydantic import Field, model_validator

from magi.application.reporting import (
    DecisionReport,
    DecisionReportNotReady,
    DecisionReportProjector,
)
from magi.domain import (
    ArbitrationResult,
    Ballot,
    ConstraintValidation,
    DataClassification,
    DecisionCase,
    EvidenceSnapshot,
    ProtocolViolation,
    RoundAssessment,
)
from magi.domain.models import MagiModel


ZERO_HASH = "0" * 64
AUDIT_NAMESPACE = UUID("d797498a-04a4-4af8-9567-78224c13da6f")


class AuditChainViolation(ProtocolViolation):
    """Raised when an audit chain is missing, reordered, or altered."""


class AuditRedactionConflict(RuntimeError):
    """Raised when one redaction command identity is reused differently."""


class AuditTrailNotFound(LookupError):
    """Raised when no canonical audit record exists for a decision version."""


class AuditDecisionState(MagiModel):
    """Canonical records required to reproduce a decision report."""

    case: DecisionCase
    snapshot: EvidenceSnapshot
    constraint_validations: tuple[ConstraintValidation, ...] = ()
    first_ballots: tuple[Ballot, ...] = ()
    review_ballots: tuple[Ballot, ...] = ()
    first_assessment: RoundAssessment | None = None
    result: ArbitrationResult | None = None
    phase: str = Field(min_length=1, max_length=80)
    cancelled: bool = False

    @model_validator(mode="after")
    def validate_identity(self) -> AuditDecisionState:
        identity = (self.case.decision_id, self.case.version)
        if (self.snapshot.decision_id, self.snapshot.decision_version) != identity:
            raise ValueError("audit snapshot identity does not match its case")
        for ballot in (*self.first_ballots, *self.review_ballots):
            if (ballot.decision_id, ballot.decision_version) != identity:
                raise ValueError("audit ballot identity does not match its case")
        if self.result is not None and (
            self.result.decision_id,
            self.result.decision_version,
        ) != identity:
            raise ValueError("audit result identity does not match its case")
        return self


class AuditRedaction(MagiModel):
    """Append-only visibility overlay; the canonical record remains unchanged."""

    target_record_id: UUID
    field_paths: tuple[str, ...] = Field(min_length=1, max_length=50)
    reason: str = Field(min_length=1, max_length=1000)
    actor: str = Field(min_length=1, max_length=120)
    command_id: UUID | None = None

    @model_validator(mode="after")
    def validate_paths(self) -> AuditRedaction:
        if any(
            not path.startswith("/")
            or path == "/"
            or "~" in path
            or any(not part for part in path.split("/")[1:])
            for path in self.field_paths
        ):
            raise ValueError("redaction paths must be simple JSON pointers")
        if len(set(self.field_paths)) != len(self.field_paths):
            raise ValueError("redaction paths must be unique")
        return self


class AuditRecord(MagiModel):
    schema_version: Literal["1.0"] = "1.0"
    record_id: UUID
    decision_id: UUID
    decision_version: int = Field(ge=1)
    sequence: int = Field(ge=1)
    kind: Literal["decision_state", "redaction"]
    classification: DataClassification
    payload: dict[str, Any]
    payload_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    previous_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    record_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    occurred_at: datetime

    @model_validator(mode="after")
    def validate_hashes(self) -> AuditRecord:
        if self.occurred_at.tzinfo is None:
            raise ValueError("audit record time must be timezone-aware")
        if self.payload_hash != _digest(self.payload):
            raise ValueError("audit payload hash does not match its payload")
        if self.record_hash != _record_hash(self):
            raise ValueError("audit record hash does not match its envelope")
        return self


class AuditRecordView(MagiModel):
    schema_version: Literal["1.0"] = "1.0"
    record_id: UUID
    decision_id: UUID
    decision_version: int = Field(ge=1)
    sequence: int = Field(ge=1)
    kind: Literal["decision_state", "redaction"]
    classification: DataClassification
    payload: dict[str, Any]
    payload_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    previous_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    record_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    occurred_at: datetime
    redacted_fields: tuple[str, ...] = ()


class DecisionAuditTrail(MagiModel):
    schema_version: Literal["1.0"] = "1.0"
    decision_id: UUID
    decision_version: int = Field(ge=1)
    integrity_status: Literal["verified"] = "verified"
    record_count: int = Field(ge=0)
    records: tuple[AuditRecordView, ...] = ()

    @model_validator(mode="after")
    def validate_count(self) -> DecisionAuditTrail:
        if self.record_count != len(self.records):
            raise ValueError("audit record count does not match records")
        for sequence, record in enumerate(self.records, start=1):
            if (
                record.decision_id != self.decision_id
                or record.decision_version != self.decision_version
                or record.sequence != sequence
            ):
                raise ValueError("audit trail record identity or sequence is invalid")
        return self


class AuditLedger(Protocol):
    async def append(
        self,
        *,
        decision_id: UUID,
        decision_version: int,
        kind: Literal["decision_state", "redaction"],
        classification: DataClassification,
        payload: Mapping[str, Any],
        occurred_at: datetime,
    ) -> AuditRecord: ...

    async def records(
        self, decision_id: UUID, decision_version: int
    ) -> tuple[AuditRecord, ...]: ...


class InMemoryAuditLedger:
    """Process-local reference adapter with the same append-only semantics."""

    def __init__(self) -> None:
        self._records: dict[tuple[UUID, int], list[AuditRecord]] = {}

    async def append(
        self,
        *,
        decision_id: UUID,
        decision_version: int,
        kind: Literal["decision_state", "redaction"],
        classification: DataClassification,
        payload: Mapping[str, Any],
        occurred_at: datetime,
    ) -> AuditRecord:
        key = (decision_id, decision_version)
        chain = self._records.setdefault(key, [])
        payload_data = copy.deepcopy(dict(payload))
        payload_hash = _digest(payload_data)
        for record in chain:
            if record.kind == kind and record.payload_hash == payload_hash:
                return record
        record = build_audit_record(
            decision_id=decision_id,
            decision_version=decision_version,
            sequence=len(chain) + 1,
            kind=kind,
            classification=classification,
            payload=payload_data,
            previous_hash=chain[-1].record_hash if chain else ZERO_HASH,
            occurred_at=occurred_at,
        )
        chain.append(record)
        return record

    async def records(
        self, decision_id: UUID, decision_version: int
    ) -> tuple[AuditRecord, ...]:
        return tuple(self._records.get((decision_id, decision_version), ()))


class DecisionAuditService:
    def __init__(self, ledger: AuditLedger) -> None:
        self._ledger = ledger
        self._report_projector = DecisionReportProjector()

    async def capture(
        self, state: Mapping[str, Any], *, occurred_at: datetime
    ) -> AuditRecord:
        snapshot = self._state(state)
        return await self._ledger.append(
            decision_id=snapshot.case.decision_id,
            decision_version=snapshot.case.version,
            kind="decision_state",
            classification=snapshot.case.data_classification,
            payload=snapshot.model_dump(mode="json"),
            occurred_at=occurred_at,
        )

    async def redact(
        self,
        decision_id: UUID,
        decision_version: int,
        redaction: AuditRedaction,
        *,
        occurred_at: datetime,
    ) -> AuditRecord:
        records = await self._verified_records(decision_id, decision_version)
        if redaction.command_id is not None:
            for record in records:
                if record.kind != "redaction":
                    continue
                stored = AuditRedaction.model_validate(record.payload)
                if stored.command_id != redaction.command_id:
                    continue
                if stored != redaction:
                    raise AuditRedactionConflict(
                        "redaction command was already used differently"
                    )
                return record
        target = next(
            (record for record in records if record.record_id == redaction.target_record_id),
            None,
        )
        if target is None or target.kind != "decision_state":
            raise AuditChainViolation("redaction target is not a decision state record")
        return await self._ledger.append(
            decision_id=decision_id,
            decision_version=decision_version,
            kind="redaction",
            classification=target.classification,
            payload=redaction.model_dump(mode="json"),
            occurred_at=occurred_at,
        )

    async def trail(
        self, decision_id: UUID, decision_version: int
    ) -> DecisionAuditTrail:
        visible = await self.visible_records(decision_id, decision_version)
        if not visible:
            raise AuditTrailNotFound("decision audit trail was not found")
        records = tuple(
            AuditRecordView.model_validate(record) for record in visible
        )
        return DecisionAuditTrail(
            decision_id=decision_id,
            decision_version=decision_version,
            record_count=len(records),
            records=records,
        )

    async def reconstruct_report(
        self, decision_id: UUID, decision_version: int
    ) -> DecisionReport:
        terminal = await self.reconstruct_state(decision_id, decision_version)
        final_ballots = terminal.review_ballots or terminal.first_ballots
        return self._report_projector.project(
            terminal.case,
            terminal.result,
            terminal.first_ballots,
            final_ballots,
        )

    async def reconstruct_state(
        self, decision_id: UUID, decision_version: int
    ) -> AuditDecisionState:
        records = await self._verified_records(decision_id, decision_version)
        states = [
            AuditDecisionState.model_validate(record.payload)
            for record in records
            if record.kind == "decision_state"
        ]
        terminal = next(
            (state for state in reversed(states) if state.result is not None), None
        )
        if terminal is None:
            raise DecisionReportNotReady("audit chain has no arbitration result")
        return terminal

    async def visible_records(
        self, decision_id: UUID, decision_version: int
    ) -> tuple[dict[str, Any], ...]:
        records = await self._verified_records(decision_id, decision_version)
        redactions: dict[UUID, list[str]] = {}
        for record in records:
            if record.kind == "redaction":
                overlay = AuditRedaction.model_validate(record.payload)
                redactions.setdefault(overlay.target_record_id, []).extend(
                    overlay.field_paths
                )
        visible: list[dict[str, Any]] = []
        for record in records:
            data = record.model_dump(mode="json")
            if record.kind == "decision_state":
                paths = tuple(redactions.get(record.record_id, ()))
                for path in paths:
                    _apply_redaction(data["payload"], path)
                if paths:
                    data["redacted_fields"] = list(paths)
            visible.append(data)
        return tuple(visible)

    async def _verified_records(
        self, decision_id: UUID, decision_version: int
    ) -> tuple[AuditRecord, ...]:
        records = await self._ledger.records(decision_id, decision_version)
        verify_audit_chain(records, decision_id, decision_version)
        return records

    @staticmethod
    def _state(state: Mapping[str, Any]) -> AuditDecisionState:
        case = DecisionCase.model_validate(state.get("case"))
        return AuditDecisionState(
            case=case,
            snapshot=EvidenceSnapshot.model_validate(state.get("snapshot")),
            constraint_validations=tuple(state.get("constraint_validations", ())),
            first_ballots=tuple(state.get("first_ballots", ())),
            review_ballots=tuple(state.get("review_ballots", ())),
            first_assessment=state.get("first_assessment"),
            result=state.get("result"),
            phase=str(state.get("phase", "created")),
            cancelled=bool(state.get("cancelled", False)),
        )


def build_audit_record(
    *,
    decision_id: UUID,
    decision_version: int,
    sequence: int,
    kind: Literal["decision_state", "redaction"],
    classification: DataClassification,
    payload: Mapping[str, Any],
    previous_hash: str,
    occurred_at: datetime,
) -> AuditRecord:
    payload_data = copy.deepcopy(dict(payload))
    payload_hash = _digest(payload_data)
    record_id = uuid5(
        AUDIT_NAMESPACE,
        f"{decision_id}:{decision_version}:{kind}:{payload_hash}",
    )
    values = {
        "record_id": record_id,
        "decision_id": decision_id,
        "decision_version": decision_version,
        "sequence": sequence,
        "kind": kind,
        "classification": classification,
        "payload": payload_data,
        "payload_hash": payload_hash,
        "previous_hash": previous_hash,
        "occurred_at": occurred_at,
    }
    provisional = AuditRecord.model_construct(**values, record_hash=ZERO_HASH)
    return AuditRecord(**values, record_hash=_record_hash(provisional))


def verify_audit_chain(
    records: tuple[AuditRecord, ...], decision_id: UUID, decision_version: int
) -> None:
    previous = ZERO_HASH
    for sequence, record in enumerate(records, start=1):
        if (
            record.decision_id != decision_id
            or record.decision_version != decision_version
            or record.sequence != sequence
            or record.previous_hash != previous
        ):
            raise AuditChainViolation("audit chain identity or sequence is invalid")
        try:
            AuditRecord.model_validate(record.model_dump())
        except ValueError as exc:
            raise AuditChainViolation("audit record integrity check failed") from exc
        previous = record.record_hash


def _digest(value: Mapping[str, Any]) -> str:
    material = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _record_hash(record: AuditRecord) -> str:
    material = {
        "record_id": str(record.record_id),
        "decision_id": str(record.decision_id),
        "decision_version": record.decision_version,
        "sequence": record.sequence,
        "kind": record.kind,
        "classification": record.classification.value,
        "payload_hash": record.payload_hash,
        "previous_hash": record.previous_hash,
        # PostgreSQL TIMESTAMPTZ preserves an instant, not the original timezone
        # representation. Canonicalize before hashing so a database round trip
        # cannot make an unchanged envelope appear tampered with.
        "occurred_at": record.occurred_at.astimezone(timezone.utc).isoformat(),
    }
    return _digest(material)


def _apply_redaction(payload: dict[str, Any], path: str) -> None:
    parts = path.split("/")[1:]
    current: Any = payload
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            raise AuditChainViolation("redaction path does not exist")
        current = current[part]
    if not isinstance(current, dict) or parts[-1] not in current:
        raise AuditChainViolation("redaction path does not exist")
    current[parts[-1]] = "[REDACTED]"
