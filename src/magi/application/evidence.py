"""Application contracts for authorized, read-only evidence retrieval."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import AnyHttpUrl, Field, model_validator

from magi.domain import DataClassification
from magi.domain.models import MagiModel


class EvidenceRetrievalError(RuntimeError):
    """Sanitized failure raised when authorized retrieval cannot complete."""


class EvidenceSourceRequest(MagiModel):
    """An explicit source locator supplied before a decision is frozen."""

    url: AnyHttpUrl
    classification: DataClassification = DataClassification.INTERNAL

    @model_validator(mode="after")
    def require_https_without_credentials(self) -> EvidenceSourceRequest:
        if self.url.scheme != "https":
            raise ValueError("evidence sources must use HTTPS")
        if self.url.username is not None or self.url.password is not None:
            raise ValueError("evidence source credentials are forbidden")
        if self.url.port not in {None, 443}:
            raise ValueError("evidence sources must use the standard HTTPS port")
        return self


class RetrievedEvidence(MagiModel):
    """Verified content returned by a gateway after policy enforcement."""

    source_type: str = Field(min_length=1, max_length=80)
    source: str = Field(min_length=1, max_length=2000)
    captured_at: datetime
    excerpt: str = Field(min_length=1, max_length=20_000)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    classification: DataClassification

    @model_validator(mode="after")
    def require_aware_capture(self) -> RetrievedEvidence:
        if self.captured_at.tzinfo is None:
            raise ValueError("retrieved evidence capture time must be timezone-aware")
        return self


class EvidenceRetrievalGateway(Protocol):
    async def retrieve(self, request: EvidenceSourceRequest) -> RetrievedEvidence: ...
