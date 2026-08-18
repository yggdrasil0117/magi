"""Opt-in M2 acceptance over real PostgreSQL and OpenAI services."""

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


LIVE_ENABLED = os.getenv("MAGI_RUN_M2_LIVE") == "1"


@unittest.skipUnless(
    LIVE_ENABLED,
    "set MAGI_RUN_M2_LIVE=1 to permit real PostgreSQL and OpenAI calls",
)
class LiveM2AcceptanceTests(unittest.TestCase):
    def test_create_confirm_run_read_and_restart(self) -> None:
        database_url = self._required("MAGI_TEST_POSTGRES_DSN")
        api_key = self._required("OPENAI_API_KEY")
        model = self._required("MAGI_OPENAI_MODEL")
        token = secrets.token_urlsafe(48)
        suffix = secrets.token_hex(8)

        with tempfile.TemporaryDirectory() as temporary:
            policy_path = Path(temporary) / "live-auth-policy.json"
            policy = HashedBearerPolicy(
                credentials=(
                    HashedBearerCredential(
                        token_sha256=hashlib.sha256(
                            token.encode("utf-8")
                        ).hexdigest(),
                        subject=f"m2-live-{suffix}",
                        actions=frozenset(
                            {
                                "decision:create",
                                "decision:read",
                                "decision:confirm",
                                "decision:run",
                                "decision:cancel",
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
            )
            headers = {
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": f"m2-live-create-{suffix}",
            }

            app = create_production_app(settings)
            with TestClient(app) as client:
                self.assertEqual(client.get("/readyz").status_code, 200)
                created = client.post(
                    "/v1/decisions",
                    headers=headers,
                    json={
                        "raw_question": (
                            "For this synthetic acceptance test, should the "
                            "release be approved now or deferred?"
                        ),
                        "minimum_risk_level": "low",
                        "data_classification": "internal",
                        "evidence": [
                            {
                                "source_type": "acceptance_fixture",
                                "source": "M2 live acceptance harness",
                                "captured_at": datetime.now(timezone.utc).isoformat(),
                                "excerpt": (
                                    "All automated checks for the synthetic "
                                    "release completed successfully."
                                ),
                                "classification": "internal",
                            }
                        ],
                    },
                )
                self.assertEqual(created.status_code, 201, created.text)
                created_view = created.json()
                self.assertTrue(created_view["awaiting_confirmation"])
                decision_id = created_view["decision_id"]

                confirmed = client.post(
                    f"/v1/decisions/{decision_id}/confirm",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Idempotency-Key": f"m2-live-confirm-{suffix}",
                    },
                    json={
                        "version": 1,
                        "confirmed_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
                self.assertEqual(confirmed.status_code, 200, confirmed.text)
                self.assertTrue(confirmed.json()["awaiting_run"])

                completed = client.post(
                    f"/v1/decisions/{decision_id}/run",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Idempotency-Key": f"m2-live-run-{suffix}",
                    },
                    json={"version": 1},
                )
                self.assertEqual(completed.status_code, 200, completed.text)
                completed_view = completed.json()
                self.assertTrue(completed_view["terminal"])
                self.assertIsNotNone(completed_view["result"])
                self.assertEqual(len(completed_view["ballots"]), 3)

            restarted_app = create_production_app(settings)
            with TestClient(restarted_app) as restarted:
                restored = restarted.get(
                    f"/v1/decisions/{decision_id}",
                    headers={"Authorization": f"Bearer {token}"},
                )
                self.assertEqual(restored.status_code, 200, restored.text)
                self.assertEqual(restored.json(), completed_view)

    def _required(self, name: str) -> str:
        value = os.getenv(name, "").strip()
        self.assertTrue(value, f"{name} is required when MAGI_RUN_M2_LIVE=1")
        return value


if __name__ == "__main__":
    unittest.main()
