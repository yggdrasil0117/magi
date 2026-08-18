"""Tests for the fail-closed hashed bearer authorization adapter."""

from __future__ import annotations

import hashlib
import unittest
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from magi.api import (
    ApiAuthenticationError,
    ApiAuthorizationError,
    ApiPrincipal,
    HashedBearerAuthorizer,
    HashedBearerCredential,
    HashedBearerPolicy,
)


TOKEN = "a-long-random-test-bearer-token"
TOKEN_DIGEST = hashlib.sha256(TOKEN.encode("utf-8")).hexdigest()


class HashedBearerAuthorizerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.decision_id = uuid4()
        self.credential = HashedBearerCredential(
            token_sha256=TOKEN_DIGEST,
            subject="operator-1",
            actions=frozenset({"decision:read", "decision:confirm"}),
            decision_ids=frozenset({self.decision_id}),
        )
        self.authorizer = HashedBearerAuthorizer(
            HashedBearerPolicy(credentials=(self.credential,))
        )

    async def test_authenticates_digest_without_retaining_raw_token(self) -> None:
        principal = await self.authorizer.authenticate(TOKEN)

        self.assertEqual(principal, ApiPrincipal(subject="operator-1"))
        self.assertNotIn(TOKEN, repr(self.authorizer.__dict__))

    async def test_rejects_invalid_token_without_echoing_it(self) -> None:
        supplied = "invalid-sensitive-bearer"

        with self.assertRaises(ApiAuthenticationError) as raised:
            await self.authorizer.authenticate(supplied)

        self.assertNotIn(supplied, str(raised.exception))

        with self.assertRaises(ApiAuthenticationError):
            await self.authorizer.authenticate("short")

    async def test_applies_action_and_decision_allowlists(self) -> None:
        principal = ApiPrincipal(subject="operator-1")
        await self.authorizer.authorize(
            principal,
            self.decision_id,
            "decision:read",
        )

        with self.assertRaises(ApiAuthorizationError):
            await self.authorizer.authorize(
                principal,
                self.decision_id,
                "decision:run",
            )
        with self.assertRaises(ApiAuthorizationError):
            await self.authorizer.authorize(
                principal,
                uuid4(),
                "decision:read",
            )

    async def test_explicit_all_decisions_still_limits_actions(self) -> None:
        credential = HashedBearerCredential(
            token_sha256=TOKEN_DIGEST,
            subject="reader",
            actions=frozenset({"decision:read"}),
            allow_all_decisions=True,
        )
        authorizer = HashedBearerAuthorizer(
            HashedBearerPolicy(credentials=(credential,))
        )
        principal = await authorizer.authenticate(TOKEN)

        await authorizer.authorize(principal, uuid4(), "decision:read")
        with self.assertRaises(ApiAuthorizationError):
            await authorizer.authorize(principal, uuid4(), "decision:cancel")

    def test_policy_rejects_unscoped_or_duplicate_credentials(self) -> None:
        with self.assertRaises(ValidationError):
            HashedBearerPolicy(credentials=())

        with self.assertRaises(ValidationError):
            HashedBearerCredential(
                token_sha256=TOKEN_DIGEST,
                subject="unscoped",
                actions=frozenset({"decision:read"}),
            )

        with self.assertRaises(ValidationError):
            HashedBearerCredential(
                token_sha256="not-a-sha256-digest",
                subject="malformed",
                actions=frozenset({"decision:delete"}),  # type: ignore[arg-type]
                allow_all_decisions=True,
            )

        with self.assertRaises(ValidationError):
            HashedBearerPolicy(credentials=(self.credential, self.credential))

        example = Path(__file__).resolve().parents[2] / "config" / "auth-policy.example.json"
        self.assertEqual(HashedBearerPolicy.from_file(example).schema_version, "1.0")
