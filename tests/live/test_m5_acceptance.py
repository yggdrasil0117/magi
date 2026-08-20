"""Opt-in M5 evaluation acceptance over real PostgreSQL and OpenAI services."""

from __future__ import annotations

import hashlib
import os
import secrets
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from magi.api import (
    HashedBearerCredential,
    HashedBearerPolicy,
    ProductionSettings,
    create_production_app,
)


LIVE_ENABLED = os.getenv("MAGI_RUN_M5_LIVE") == "1"


@unittest.skipUnless(
    LIVE_ENABLED,
    "set MAGI_RUN_M5_LIVE=1 to permit real PostgreSQL and OpenAI calls",
)
class LiveM5AcceptanceTests(unittest.TestCase):
    def test_live_decision_appends_and_restores_evaluation_history(self) -> None:
        database_url = self._required("MAGI_TEST_POSTGRES_DSN")
        api_key = self._required("OPENAI_API_KEY")
        model = self._required("MAGI_OPENAI_MODEL")
        input_price = self._required_nonnegative_int(
            "MAGI_MODEL_INPUT_MICROUSD_PER_MILLION_TOKENS"
        )
        output_price = self._required_nonnegative_int(
            "MAGI_MODEL_OUTPUT_MICROUSD_PER_MILLION_TOKENS"
        )
        token = secrets.token_urlsafe(48)
        suffix = secrets.token_hex(8)

        with tempfile.TemporaryDirectory() as temporary:
            policy_path = Path(temporary) / "m5-live-auth-policy.json"
            policy = HashedBearerPolicy(
                credentials=(
                    HashedBearerCredential(
                        token_sha256=hashlib.sha256(token.encode("utf-8")).hexdigest(),
                        subject=f"m5-live-{suffix}",
                        actions=frozenset(
                            {
                                "decision:create",
                                "decision:read",
                                "decision:confirm",
                                "decision:run",
                                "evaluation:read",
                                "evaluation:run",
                            }
                        ),
                        allow_all_decisions=True,
                    ),
                )
            )
            policy_path.write_text(policy.model_dump_json(), encoding="utf-8")
            settings = ProductionSettings(
                database_url=database_url,
                openai_api_key=api_key,
                openai_model=model,
                skills_dir=Path(__file__).resolve().parents[2] / "skills",
                auth_policy_file=policy_path,
                postgres_min_size=1,
                postgres_max_size=6,
                model_max_attempts=2,
                model_input_microusd_per_million_tokens=input_price,
                model_output_microusd_per_million_tokens=output_price,
            )
            authorization = {"Authorization": f"Bearer {token}"}

            app = create_production_app(settings)
            with TestClient(app) as client:
                decision_id = self._complete_decision(
                    client,
                    authorization,
                    suffix,
                )
                endpoint = f"/v1/decisions/{decision_id}/evaluations"
                first = client.post(
                    endpoint,
                    headers=authorization,
                    json={"version": 1},
                )
                replay = client.post(
                    endpoint,
                    headers=authorization,
                    json={"version": 1},
                )
                history = client.get(
                    endpoint + "?version=1&limit=20",
                    headers=authorization,
                )

                self.assertEqual(first.status_code, 200, first.text)
                self.assertEqual(replay.status_code, 200, replay.text)
                self.assertEqual(history.status_code, 200, history.text)
                self.assertEqual(first.json(), replay.json())
                document = history.json()
                self.assertEqual(document["total_count"], 1)
                self.assertEqual(document["trend"]["sample_count"], 1)
                evaluation = document["evaluations"][0]["evaluation"]
                self.assertEqual(evaluation["schema_version"], "1.0")
                self.assertEqual(evaluation["evaluator_version"], "1.0")
                self.assertGreaterEqual(evaluation["latency"]["sample_count"], 3)
                self.assertIsNotNone(evaluation["cost"]["total_cost_microusd"])

            restarted_app = create_production_app(settings)
            with TestClient(restarted_app) as restarted:
                restored = restarted.get(
                    f"/v1/decisions/{decision_id}/evaluations?version=1&limit=20",
                    headers=authorization,
                )
                self.assertEqual(restored.status_code, 200, restored.text)
                self.assertEqual(restored.json(), document)

    def _complete_decision(
        self,
        client: TestClient,
        authorization: dict[str, str],
        suffix: str,
    ) -> str:
        created = client.post(
            "/v1/decisions",
            headers={
                **authorization,
                "Idempotency-Key": f"m5-live-create-{suffix}",
            },
            json={
                "raw_question": (
                    "For this synthetic quality test, should the release proceed "
                    "now, be limited, or be deferred?"
                ),
                "minimum_risk_level": "low",
                "data_classification": "internal",
                "evidence": [
                    {
                        "source_type": "acceptance_fixture",
                        "source": "M5 live quality harness",
                        "captured_at": datetime.now(timezone.utc).isoformat(),
                        "excerpt": (
                            "Automated checks passed and rollback was verified in "
                            "the synthetic staging environment."
                        ),
                        "classification": "internal",
                    }
                ],
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        decision_id = created.json()["decision_id"]

        confirmed = client.post(
            f"/v1/decisions/{decision_id}/confirm",
            headers={
                **authorization,
                "Idempotency-Key": f"m5-live-confirm-{suffix}",
            },
            json={
                "version": 1,
                "confirmed_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.text)

        completed = client.post(
            f"/v1/decisions/{decision_id}/run",
            headers={
                **authorization,
                "Idempotency-Key": f"m5-live-run-{suffix}",
            },
            json={"version": 1},
        )
        self.assertEqual(completed.status_code, 200, completed.text)
        self.assertTrue(completed.json()["terminal"])
        return decision_id

    def _required(self, name: str) -> str:
        value = os.getenv(name, "").strip()
        self.assertTrue(value, f"{name} is required when MAGI_RUN_M5_LIVE=1")
        return value

    def _required_nonnegative_int(self, name: str) -> int:
        raw = self._required(name)
        try:
            value = int(raw)
        except ValueError:
            self.fail(f"{name} must be an integer")
        self.assertGreaterEqual(value, 0, f"{name} must be nonnegative")
        return value


if __name__ == "__main__":
    unittest.main()
