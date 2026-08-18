"""Authentication and per-decision authorization ports for the API adapter."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from pydantic import Field

from magi.domain.models import MagiModel


class ApiAuthenticationError(RuntimeError):
    """Raised when bearer credentials are missing or invalid."""


class ApiAuthorizationError(RuntimeError):
    """Raised when a principal cannot perform an action on a decision."""


class ApiPrincipal(MagiModel):
    subject: str = Field(min_length=1, max_length=200)


class DecisionAuthorizer(Protocol):
    async def authenticate(self, bearer_token: str) -> ApiPrincipal: ...

    async def authorize(
        self,
        principal: ApiPrincipal,
        decision_id: UUID,
        action: str,
    ) -> None: ...
