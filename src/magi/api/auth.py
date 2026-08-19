"""Authentication and per-decision authorization ports for the API adapter."""

from __future__ import annotations

import hashlib
import hmac
from pathlib import Path
from typing import Literal, Protocol
from uuid import UUID

from pydantic import Field, model_validator

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
        decision_id: UUID | None,
        action: str,
    ) -> None: ...


DecisionAction = Literal[
    "decision:create",
    "decision:read",
    "decision:confirm",
    "decision:run",
    "decision:cancel",
    "audit:read",
    "audit:redact",
]


class HashedBearerCredential(MagiModel):
    """One bearer digest and its explicit decision permissions."""

    token_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    subject: str = Field(min_length=1, max_length=200)
    actions: frozenset[DecisionAction] = Field(min_length=1)
    decision_ids: frozenset[UUID] = frozenset()
    allow_all_decisions: bool = False

    @model_validator(mode="after")
    def require_decision_scope(self) -> HashedBearerCredential:
        if "decision:create" in self.actions and not self.allow_all_decisions:
            raise ValueError(
                "static decision creation requires explicit all-decisions access"
            )
        resource_actions = self.actions - {"decision:create"}
        if resource_actions and not self.allow_all_decisions and not self.decision_ids:
            raise ValueError(
                "a bearer credential must allow all decisions or list decision IDs"
            )
        return self


class HashedBearerPolicy(MagiModel):
    """Versioned, fail-closed policy containing digests rather than raw tokens."""

    schema_version: Literal["1.0"] = "1.0"
    credentials: tuple[HashedBearerCredential, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_credentials(self) -> HashedBearerPolicy:
        digests = [credential.token_sha256 for credential in self.credentials]
        subjects = [credential.subject for credential in self.credentials]
        if len(set(digests)) != len(digests):
            raise ValueError("bearer token digests must be unique")
        if len(set(subjects)) != len(subjects):
            raise ValueError("bearer subjects must be unique")
        return self

    @classmethod
    def from_file(cls, path: str | Path) -> HashedBearerPolicy:
        policy_path = Path(path)
        try:
            if policy_path.stat().st_size > 1_000_000:
                raise ValueError("bearer policy file exceeds 1 MB")
            payload = policy_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"cannot read bearer policy file: {policy_path}") from exc
        return cls.model_validate_json(payload)


class HashedBearerAuthorizer:
    """Authenticate opaque bearer values and apply a static decision allowlist."""

    def __init__(self, policy: HashedBearerPolicy) -> None:
        self._credentials_by_subject = {
            credential.subject: credential for credential in policy.credentials
        }
        self._credentials = policy.credentials

    @classmethod
    def from_file(cls, path: str | Path) -> HashedBearerAuthorizer:
        return cls(HashedBearerPolicy.from_file(path))

    async def authenticate(self, bearer_token: str) -> ApiPrincipal:
        if not 16 <= len(bearer_token) <= 4096:
            raise ApiAuthenticationError("invalid bearer credential")
        supplied_digest = hashlib.sha256(bearer_token.encode("utf-8")).hexdigest()
        for credential in self._credentials:
            if hmac.compare_digest(supplied_digest, credential.token_sha256):
                return ApiPrincipal(subject=credential.subject)
        raise ApiAuthenticationError("invalid bearer credential")

    async def authorize(
        self,
        principal: ApiPrincipal,
        decision_id: UUID | None,
        action: str,
    ) -> None:
        credential = self._credentials_by_subject.get(principal.subject)
        if credential is None:
            raise ApiAuthorizationError("principal is not present in the policy")
        if action not in credential.actions:
            raise ApiAuthorizationError("action is not allowed by the policy")
        if action == "decision:create":
            return
        if decision_id is None:
            raise ApiAuthorizationError("decision ID is required by the policy")
        if not credential.allow_all_decisions and decision_id not in credential.decision_ids:
            raise ApiAuthorizationError("decision is not allowed by the policy")
