"""Application-owned inputs for Coordinator-backed decision preparation."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field, model_validator

from magi.domain import DataClassification, RiskLevel
from magi.domain.models import MagiModel

from .evidence import EvidenceSourceRequest


class DecisionPreparationFailed(RuntimeError):
    """Raised when a raw decision cannot be normalized safely."""


class SuppliedEvidence(MagiModel):
    """Untrusted evidence supplied at the API boundary before application sealing."""

    source_type: str = Field(min_length=1, max_length=80)
    source: str = Field(min_length=1, max_length=2000)
    captured_at: datetime
    excerpt: str = Field(min_length=1, max_length=20_000)
    classification: DataClassification

    @model_validator(mode="after")
    def require_timezone(self) -> SuppliedEvidence:
        if self.captured_at.tzinfo is None:
            raise ValueError("evidence captured_at must be timezone-aware")
        return self


class DecisionPreparationRequest(MagiModel):
    decision_id: UUID
    raw_question: str = Field(min_length=1, max_length=20_000)
    minimum_risk_level: RiskLevel = RiskLevel.LOW
    data_classification: DataClassification = DataClassification.INTERNAL
    evidence: tuple[SuppliedEvidence, ...] = Field(default=(), max_length=50)
    evidence_sources: tuple[EvidenceSourceRequest, ...] = Field(
        default=(), max_length=20
    )
