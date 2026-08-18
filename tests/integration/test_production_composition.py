"""Production composition tests without PostgreSQL or model network calls."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from magi.agents import InMemoryInvocationLedger
from magi.api import (
    HashedBearerAuthorizer,
    HashedBearerCredential,
    HashedBearerPolicy,
    ProductionConfigurationError,
    ProductionSettings,
    create_production_app,
)
from magi.application import InMemoryCommandIdempotencyStore
from tests.fixtures.factories import DECISION_ID


TOKEN = "production-composition-test-token"


class FakeRuntime:
    def __init__(self) -> None:
        self.invocation_ledger = InMemoryInvocationLedger()
        self.command_idempotency_store = InMemoryCommandIdempotencyStore()
        self._checkpointer = object()
        self.open_calls: list[bool] = []
        self.closed = False

    @property
    def checkpointer(self) -> object:
        if not self.open_calls:
            raise RuntimeError("runtime is not open")
        return self._checkpointer

    async def open(self, *, setup: bool = True) -> None:
        self.open_calls.append(setup)

    async def close(self) -> None:
        self.closed = True


class EmptyGraph:
    async def aget_state(
        self,
        config: object,
        *,
        subgraphs: bool = False,
    ) -> object:
        return SimpleNamespace(values={}, next=(), interrupts=())

    async def ainvoke(
        self,
        input: object,
        config: object | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        raise AssertionError("empty graph must not be invoked")


class ProductionCompositionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.policy_file = root / "auth-policy.json"
        policy = HashedBearerPolicy(
            credentials=(
                HashedBearerCredential(
                    token_sha256=hashlib.sha256(TOKEN.encode("utf-8")).hexdigest(),
                    subject="operator-1",
                    actions=frozenset({"decision:read"}),
                    allow_all_decisions=True,
                ),
            )
        )
        self.policy_file.write_text(policy.model_dump_json(), encoding="utf-8")
        self.settings = ProductionSettings(
            database_url="postgresql://test:test@127.0.0.1/test",
            openai_api_key="test-openai-key",
            openai_model="test-model",
            skills_dir=Path(__file__).resolve().parents[2] / "skills",
            auth_policy_file=self.policy_file,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_lifespan_opens_composes_and_closes_shared_runtime(self) -> None:
        runtime = FakeRuntime()
        observed: dict[str, object] = {}

        def runner_factory(settings: ProductionSettings, ledger: object) -> object:
            observed["settings"] = settings
            observed["ledger"] = ledger
            return "runner"

        def graph_factory(runner: object, checkpointer: object) -> EmptyGraph:
            observed["runner"] = runner
            observed["checkpointer"] = checkpointer
            return EmptyGraph()

        def coordinator_factory(settings: ProductionSettings) -> object:
            observed["coordinator_settings"] = settings
            return object()

        app = create_production_app(
            self.settings,
            authorizer=HashedBearerAuthorizer.from_file(self.policy_file),
            runtime_factory=lambda settings: runtime,
            runner_factory=runner_factory,
            graph_factory=graph_factory,
            coordinator_factory=coordinator_factory,
        )

        self.assertEqual(runtime.open_calls, [])
        with TestClient(app) as client:
            self.assertEqual(runtime.open_calls, [True])
            self.assertFalse(runtime.closed)
            self.assertEqual(app.state.magi_model, "test-model")
            self.assertEqual(client.get("/healthz").json(), {"status": "ok"})
            response = client.get(
                f"/v1/decisions/{DECISION_ID}",
                headers={"Authorization": f"Bearer {TOKEN}"},
            )
            self.assertEqual(response.status_code, 404)

        self.assertTrue(runtime.closed)
        self.assertIs(observed["settings"], self.settings)
        self.assertIs(observed["ledger"], runtime.invocation_ledger)
        self.assertEqual(observed["runner"], "runner")
        self.assertIs(observed["checkpointer"], runtime._checkpointer)
        self.assertIs(observed["coordinator_settings"], self.settings)

    def test_startup_failure_closes_the_database_runtime(self) -> None:
        runtime = FakeRuntime()

        def fail_runner(settings: ProductionSettings, ledger: object) -> object:
            raise RuntimeError("runner construction failed")

        app = create_production_app(
            self.settings,
            authorizer=HashedBearerAuthorizer.from_file(self.policy_file),
            runtime_factory=lambda settings: runtime,
            runner_factory=fail_runner,
        )

        with self.assertRaisesRegex(RuntimeError, "runner construction failed"):
            with TestClient(app):
                pass
        self.assertEqual(runtime.open_calls, [True])
        self.assertTrue(runtime.closed)

    def test_settings_are_fail_closed_and_hide_secrets(self) -> None:
        with self.assertRaises(ProductionConfigurationError):
            ProductionSettings.from_mapping({})

        representation = repr(self.settings)
        self.assertNotIn("test-openai-key", representation)
        self.assertNotIn("postgresql://", representation)

        values = {
            "MAGI_DATABASE_URL": "postgresql://example",
            "OPENAI_API_KEY": "key",
            "MAGI_OPENAI_MODEL": "model",
            "MAGI_SKILLS_DIR": str(self.settings.skills_dir),
            "MAGI_AUTH_POLICY_FILE": str(self.policy_file),
            "MAGI_POSTGRES_MAX_SIZE": "1",
        }
        with self.assertRaises(ProductionConfigurationError):
            ProductionSettings.from_mapping(values)
