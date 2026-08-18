"""HTTP request and error models for API contract 1.0."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, model_validator

from magi.domain.models import MagiModel


class ConfirmDecisionCommand(MagiModel):
    version: int = Field(default=1, ge=1)
    confirmed_at: datetime

    @model_validator(mode="after")
    def require_timezone(self) -> ConfirmDecisionCommand:
        if self.confirmed_at.tzinfo is None:
            raise ValueError("confirmed_at must be timezone-aware")
        return self


class RunDecisionCommand(MagiModel):
    version: int = Field(default=1, ge=1)


class CancelDecisionCommand(MagiModel):
    version: int = Field(default=1, ge=1)
    reason: str | None = Field(default=None, max_length=2000)


class ApiErrorDetail(MagiModel):
    code: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=500)


class ApiErrorResponse(MagiModel):
    error: ApiErrorDetail
