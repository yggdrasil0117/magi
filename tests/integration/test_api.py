"""FastAPI transport tests without network or external authentication."""

from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timezone
from uuid import UUID

from fastapi.testclient import TestClient

from magi.api import (
    ApiAuthenticationError,
    ApiAuthorizationError,
    ApiPrincipal,
    create_app,
)
from magi.arbitration import DeterministicArbiter
from magi.application import (
    DecisionApplicationService,
    DecisionPreparationFailed,
    DecisionPreparationRequest,
    DecisionView,
    DecisionViewProjector,
    DecisionWorkflowConflict,
    DecisionWorkflowNotFound,
)
from magi.agents import ScriptedPerspectiveRunner
from magi.domain import AgentName
from magi.orchestration import build_langgraph_workflow
from tests.fixtures.factories import (
    DECISION_ID,
    make_ballot,
    make_case,
    make_snapshot,
)


class FakeDecisionService:
    def __init__(self) -> None:
        case = make_case(confirmed=False)
        self.view = DecisionViewProjector().project(
            {
                "case": case.model_dump(mode="json"),
                "snapshot": make_snapshot(case).model_dump(mode="json"),
                "phase": "waiting_for_user",
            }
        )
        self.calls: list[tuple[str, UUID, int, object | None]] = []
        self.error: Exception | None = None

    def _result(
        self,
        action: str,
        decision_id: UUID,
        version: int,
        detail: object | None = None,
    ) -> DecisionView:
        self.calls.append((action, decision_id, version, detail))
        if self.error is not None:
            raise self.error
        return self.view

    async def get(self, decision_id: UUID, version: int) -> DecisionView:
        return self._result("get", decision_id, version)

    async def prepare(self, request: DecisionPreparationRequest) -> DecisionView:
        return self._result("prepare", self.view.decision_id, 1, request)

    async def confirm(
        self,
        decision_id: UUID,
        version: int,
        *,
        confirmed_at: datetime,
    ) -> DecisionView:
        return self._result("confirm", decision_id, version, confirmed_at)

    async def run(self, decision_id: UUID, version: int) -> DecisionView:
        return self._result("run", decision_id, version)

    async def cancel(
        self,
        decision_id: UUID,
        version: int,
        *,
        reason: str | None = None,
    ) -> DecisionView:
        return self._result("cancel", decision_id, version, reason)


class FakeAuthorizer:
    def __init__(self) -> None:
        self.denied_actions: set[str] = set()
        self.authorizations: list[tuple[str, UUID | None, str]] = []

    async def authenticate(self, bearer_token: str) -> ApiPrincipal:
        subjects = {
            "token-user-1": "user-1",
            "token-user-2": "user-2",
        }
        if bearer_token not in subjects:
            raise ApiAuthenticationError("invalid token payload")
        return ApiPrincipal(subject=subjects[bearer_token])

    async def authorize(
        self,
        principal: ApiPrincipal,
        decision_id: UUID | None,
        action: str,
    ) -> None:
        self.authorizations.append((principal.subject, decision_id, action))
        if action in self.denied_actions:
            raise ApiAuthorizationError("private policy detail")


class FakeReadinessProbe:
    def __init__(self, ready: bool = True) -> None:
        self.ready = ready
        self.error: Exception | None = None

    async def is_ready(self) -> bool:
        if self.error is not None:
            raise self.error
        return self.ready


class FastApiAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = FakeDecisionService()
        self.authorizer = FakeAuthorizer()
        self.client = TestClient(
            create_app(self.service, self.authorizer),
            raise_server_exceptions=False,
        )
        self.auth = {"Authorization": "Bearer token-user-1"}

    def path(self, command: str = "") -> str:
        suffix = f"/{command}" if command else ""
        return f"/v1/decisions/{DECISION_ID}{suffix}"

    def command_headers(
        self,
        key: str = "command-0001",
        *,
        token: str = "token-user-1",
    ) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": key,
        }

    def set_completed_view(self) -> DecisionView:
        case = make_case(confirmed=True)
        snapshot = make_snapshot(case)
        ballots = tuple(
            make_ballot(case, agent, "release") for agent in AgentName
        )
        result = DeterministicArbiter().arbitrate(case, snapshot, ballots)
        self.service.view = DecisionViewProjector().project(
            {
                "case": case.model_dump(mode="json"),
                "snapshot": snapshot.model_dump(mode="json"),
                "first_ballots": [
                    ballot.model_dump(mode="json") for ballot in ballots
                ],
                "review_ballots": [],
                "result": result.model_dump(mode="json"),
                "phase": "completed",
            }
        )
        return self.service.view

    def test_health_does_not_require_authentication(self) -> None:
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_readiness_is_fail_closed_and_sanitized(self) -> None:
        unavailable = self.client.get("/readyz")
        self.assertEqual(unavailable.status_code, 503)
        self.assertEqual(unavailable.json(), {"status": "not_ready"})

        probe = FakeReadinessProbe()
        client = TestClient(
            create_app(
                self.service,
                self.authorizer,
                readiness_probe=probe,
            ),
            raise_server_exceptions=False,
        )
        self.assertEqual(client.get("/readyz").json(), {"status": "ready"})

        probe.error = RuntimeError("secret database connection detail")
        failed = client.get("/readyz")
        self.assertEqual(failed.status_code, 503)
        self.assertEqual(failed.json(), {"status": "not_ready"})
        self.assertNotIn("secret database connection detail", failed.text)

    def test_read_requires_authentication_and_per_decision_authorization(self) -> None:
        missing = self.client.get(self.path())
        self.assertEqual(missing.status_code, 401)
        self.assertEqual(missing.json()["error"]["code"], "authentication_required")
        self.assertEqual(missing.headers["www-authenticate"], "Bearer")

        invalid = self.client.get(
            self.path(),
            headers={"Authorization": "Bearer secret-invalid-token"},
        )
        self.assertEqual(invalid.status_code, 401)
        self.assertNotIn("secret-invalid-token", invalid.text)

        self.authorizer.denied_actions.add("decision:read")
        denied = self.client.get(self.path(), headers=self.auth)
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.json()["error"]["code"], "decision_access_denied")
        self.assertNotIn("private policy detail", denied.text)

    def test_get_returns_only_decision_view(self) -> None:
        response = self.client.get(
            self.path() + "?version=2",
            headers=self.auth,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schema_version"], "1.0")
        self.assertNotIn("configurable", payload)
        self.assertNotIn("interrupts", payload)
        self.assertEqual(self.service.calls, [("get", DECISION_ID, 2, None)])
        self.assertEqual(
            self.authorizer.authorizations[-1],
            ("user-1", DECISION_ID, "decision:read"),
        )

    def test_report_requires_authentication_and_terminal_result(self) -> None:
        unauthenticated = self.client.get(self.path("report"))
        self.assertEqual(unauthenticated.status_code, 401)

        pending = self.client.get(self.path("report"), headers=self.auth)
        self.assertEqual(pending.status_code, 409)
        self.assertEqual(pending.json()["error"]["code"], "report_not_ready")

        self.authorizer.denied_actions.add("decision:read")
        denied = self.client.get(self.path("report"), headers=self.auth)
        self.assertEqual(denied.status_code, 403)

    def test_report_route_returns_authoritative_json_with_private_headers(self) -> None:
        view = self.set_completed_view()

        response = self.client.get(
            self.path("report") + "?version=1",
            headers=self.auth,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), view.report.model_dump(mode="json"))
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(self.service.calls[-1], ("get", DECISION_ID, 1, None))

    def test_markdown_report_route_returns_a_safe_attachment(self) -> None:
        self.set_completed_view()

        response = self.client.get(self.path("report.md"), headers=self.auth)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/markdown"))
        self.assertIn("attachment;", response.headers["content-disposition"])
        self.assertIn(str(DECISION_ID), response.headers["content-disposition"])
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        self.assertIn("# MAGI Decision Report", response.text)
        self.assertIn("- Status: `consensus`", response.text)

    def test_create_prepares_once_and_returns_confirmation_gate(self) -> None:
        body = {
            "raw_question": "Should this release be deployed?",
            "minimum_risk_level": "medium",
            "data_classification": "internal",
            "evidence": [
                {
                    "source_type": "user_note",
                    "source": "release checklist",
                    "captured_at": "2026-08-18T15:30:00+00:00",
                    "excerpt": "All checks passed.",
                    "classification": "internal",
                }
            ],
        }
        headers = self.command_headers("create-command-01")

        first = self.client.post("/v1/decisions", headers=headers, json=body)
        repeated = self.client.post("/v1/decisions", headers=headers, json=body)

        self.assertEqual(first.status_code, 201)
        self.assertEqual(repeated.status_code, 201)
        self.assertEqual(first.json(), repeated.json())
        self.assertEqual(tuple(call[0] for call in self.service.calls), ("prepare",))
        self.assertEqual(
            self.authorizer.authorizations[-1],
            ("user-1", None, "decision:create"),
        )
        request = self.service.calls[0][3]
        self.assertIsInstance(request, DecisionPreparationRequest)

    def test_create_failure_is_sanitized_and_not_cached(self) -> None:
        self.service.error = DecisionPreparationFailed("secret coordinator detail")
        body = {"raw_question": "Sensitive secret question"}
        headers = self.command_headers("create-command-02")

        response = self.client.post("/v1/decisions", headers=headers, json=body)
        retried = self.client.post("/v1/decisions", headers=headers, json=body)

        self.assertEqual(response.status_code, 422)
        self.assertEqual(retried.status_code, 422)
        self.assertEqual(
            response.json()["error"]["code"],
            "decision_preparation_failed",
        )
        self.assertNotIn("Sensitive secret question", response.text)
        self.assertNotIn("secret coordinator detail", response.text)
        first_request = self.service.calls[0][3]
        second_request = self.service.calls[1][3]
        self.assertIsInstance(first_request, DecisionPreparationRequest)
        self.assertIsInstance(second_request, DecisionPreparationRequest)
        self.assertEqual(first_request.decision_id, second_request.decision_id)

    def test_confirm_requires_valid_idempotency_key_and_body(self) -> None:
        body = {
            "version": 1,
            "confirmed_at": "2026-08-18T15:00:00+00:00",
        }
        missing = self.client.post(
            self.path("confirm"),
            headers=self.auth,
            json=body,
        )
        self.assertEqual(missing.status_code, 422)
        self.assertEqual(
            missing.json()["error"]["code"],
            "request_validation_failed",
        )

        invalid = self.client.post(
            self.path("confirm"),
            headers=self.command_headers(),
            json={"version": 1, "confirmed_at": "secret invalid timestamp"},
        )
        self.assertEqual(invalid.status_code, 422)
        self.assertNotIn("secret invalid timestamp", invalid.text)

    def test_duplicate_confirm_executes_service_once(self) -> None:
        body = {
            "version": 1,
            "confirmed_at": "2026-08-18T15:00:00+00:00",
        }
        first = self.client.post(
            self.path("confirm"),
            headers=self.command_headers(),
            json=body,
        )
        repeated = self.client.post(
            self.path("confirm"),
            headers=self.command_headers(),
            json=body,
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(first.json(), repeated.json())
        self.assertEqual(
            tuple(call[0] for call in self.service.calls),
            ("confirm",),
        )

    def test_reusing_key_for_different_payload_returns_conflict(self) -> None:
        first = self.client.post(
            self.path("cancel"),
            headers=self.command_headers(),
            json={"version": 1, "reason": "First reason"},
        )
        conflict = self.client.post(
            self.path("cancel"),
            headers=self.command_headers(),
            json={"version": 1, "reason": "Different reason"},
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["error"]["code"], "idempotency_conflict")
        self.assertNotIn("Different reason", conflict.text)
        self.assertEqual(len(self.service.calls), 1)

    def test_idempotency_key_is_scoped_by_principal(self) -> None:
        body = {"version": 1}
        for token in ("token-user-1", "token-user-2"):
            response = self.client.post(
                self.path("run"),
                headers=self.command_headers(token=token),
                json=body,
            )
            self.assertEqual(response.status_code, 200)

        self.assertEqual(tuple(call[0] for call in self.service.calls), ("run", "run"))

    def test_run_and_cancel_route_to_application_service(self) -> None:
        run = self.client.post(
            self.path("run"),
            headers=self.command_headers("command-run1"),
            json={"version": 3},
        )
        cancel = self.client.post(
            self.path("cancel"),
            headers=self.command_headers("command-stop1"),
            json={"version": 4, "reason": "Pause this decision."},
        )

        self.assertEqual(run.status_code, 200)
        self.assertEqual(cancel.status_code, 200)
        self.assertEqual(
            self.service.calls,
            [
                ("run", DECISION_ID, 3, None),
                ("cancel", DECISION_ID, 4, "Pause this decision."),
            ],
        )

    def test_application_errors_map_to_stable_http_errors(self) -> None:
        self.service.error = DecisionWorkflowNotFound("private database detail")
        missing = self.client.get(self.path(), headers=self.auth)
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()["error"]["code"], "decision_not_found")
        self.assertNotIn("private database detail", missing.text)

        self.service.error = DecisionWorkflowConflict("decision is already complete")
        conflict = self.client.post(
            self.path("run"),
            headers=self.command_headers("command-run2"),
            json={"version": 1},
        )
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["error"]["code"], "decision_conflict")

    def test_unknown_route_uses_stable_error_envelope(self) -> None:
        response = self.client.get("/v1/not-a-route")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "route_not_found")

    def test_openapi_declares_bearer_security(self) -> None:
        response = self.client.get("/openapi.json")
        self.assertEqual(response.status_code, 200)
        document = response.json()
        security_schemes = document["components"]["securitySchemes"]
        self.assertEqual(security_schemes["HTTPBearer"]["type"], "http")
        self.assertEqual(security_schemes["HTTPBearer"]["scheme"], "bearer")
        report_path = f"/v1/decisions/{{decision_id}}/report"
        markdown_path = f"/v1/decisions/{{decision_id}}/report.md"
        self.assertIn(report_path, document["paths"])
        self.assertIn(markdown_path, document["paths"])
        report_schema = document["paths"][report_path]["get"]["responses"]["200"]
        self.assertIn("application/json", report_schema["content"])
        markdown_schema = document["paths"][markdown_path]["get"]["responses"]["200"]
        self.assertIn("text/markdown", markdown_schema["content"])


class FastApiApplicationStackTests(unittest.TestCase):
    def test_confirm_and_run_drive_real_langgraph_service(self) -> None:
        case = make_case(confirmed=False)
        runner = ScriptedPerspectiveRunner(
            {agent: make_ballot(case, agent, "release") for agent in AgentName}
        )
        service = DecisionApplicationService(build_langgraph_workflow(runner))
        asyncio.run(
            service.wait_for_confirmation(
                case,
                make_snapshot(case),
            )
        )
        client = TestClient(
            create_app(service, FakeAuthorizer()),
            raise_server_exceptions=False,
        )
        base_path = f"/v1/decisions/{case.decision_id}"
        confirmed = client.post(
            base_path + "/confirm",
            headers={
                "Authorization": "Bearer token-user-1",
                "Idempotency-Key": "stack-confirm-1",
            },
            json={
                "version": case.version,
                "confirmed_at": "2026-08-18T16:00:00+00:00",
            },
        )
        self.assertEqual(confirmed.status_code, 200)
        self.assertEqual(confirmed.json()["state"], "evidence_ready")
        self.assertEqual(runner.calls, [])

        completed = client.post(
            base_path + "/run",
            headers={
                "Authorization": "Bearer token-user-1",
                "Idempotency-Key": "stack-run-0001",
            },
            json={"version": case.version},
        )
        self.assertEqual(completed.status_code, 200)
        self.assertEqual(completed.json()["state"], "completed")
        self.assertEqual(completed.json()["result"]["winning_option"], "release")
        self.assertEqual(len(runner.calls), 3)

        report = client.get(
            base_path + "/report",
            headers={"Authorization": "Bearer token-user-1"},
        )
        self.assertEqual(report.status_code, 200)
        self.assertEqual(report.json()["selected_option"], "release")
        self.assertEqual(report.json()["status"], "consensus")


if __name__ == "__main__":
    unittest.main()
