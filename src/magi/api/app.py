"""FastAPI transport adapter for the MAGI decision application service."""

import hashlib
import json
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Annotated, Protocol
from uuid import UUID, uuid5

from fastapi import Depends, FastAPI, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.exceptions import HTTPException as StarletteHTTPException

from magi import __version__
from magi.application import (
    CommandIdempotencyConflict,
    CommandIdempotencyStore,
    DecisionPreparationFailed,
    DecisionPreparationRequest,
    EvidenceSourceRequest,
    DecisionCatalog,
    DecisionHistory,
    DecisionReport,
    DecisionReportMarkdownRenderer,
    DecisionReportNotReady,
    DecisionView,
    DecisionWorkflowConflict,
    DecisionWorkflowNotFound,
    InMemoryCommandIdempotencyStore,
    OperationEventPage,
    OperationIdempotencyConflict,
    OperationInbox,
    OperationKind,
    OperationReceipt,
    OperationStore,
    SuppliedEvidence,
)
from magi.domain import ProtocolViolation
from magi.domain.models import utc_now
from magi.audit import (
    AuditRecord,
    AuditRecordView,
    AuditRedaction,
    AuditRedactionConflict,
    AuditTrailNotFound,
    DecisionAuditTrail,
)

from .auth import (
    ApiAuthenticationError,
    ApiAuthorizationError,
    ApiPrincipal,
    DecisionAuthorizer,
)
from .models import (
    ApiErrorDetail,
    ApiErrorResponse,
    CancelDecisionCommand,
    ConfirmDecisionCommand,
    CreateDecisionCommand,
    RunDecisionCommand,
    RedactAuditCommand,
)


IDEMPOTENCY_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,199}$"
CREATION_NAMESPACE = UUID("7d064bfc-7ab6-4e37-a7ad-94d92b967a23")
REDACTION_NAMESPACE = UUID("ec1e035c-5ac9-47a1-950e-18e8d0702b1b")


class MarkdownResponse(Response):
    media_type = "text/markdown"


class DecisionApiService(Protocol):
    async def prepare(self, request: DecisionPreparationRequest) -> DecisionView: ...

    async def get(self, decision_id: UUID, version: int) -> DecisionView: ...

    async def confirm(
        self,
        decision_id: UUID,
        version: int,
        *,
        confirmed_at: datetime,
    ) -> DecisionView: ...

    async def run(self, decision_id: UUID, version: int) -> DecisionView: ...

    async def cancel(
        self,
        decision_id: UUID,
        version: int,
        *,
        reason: str | None = None,
    ) -> DecisionView: ...


class ReadinessProbe(Protocol):
    async def is_ready(self) -> bool: ...


class AuditApiService(Protocol):
    async def trail(
        self, decision_id: UUID, decision_version: int
    ) -> DecisionAuditTrail: ...

    async def redact(
        self,
        decision_id: UUID,
        decision_version: int,
        redaction: AuditRedaction,
        *,
        occurred_at: datetime,
    ) -> AuditRecord: ...


def create_app(
    service: DecisionApiService,
    authorizer: DecisionAuthorizer,
    *,
    idempotency_store: CommandIdempotencyStore | None = None,
    operation_store: OperationStore | None = None,
    audit_service: AuditApiService | None = None,
    lifespan: Callable[[FastAPI], AbstractAsyncContextManager[None]] | None = None,
    readiness_probe: ReadinessProbe | None = None,
) -> FastAPI:
    """Create an API app with mandatory authentication and authorization ports."""

    app = FastAPI(
        title="MAGI Decision API",
        version=__version__,
        docs_url="/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    security = HTTPBearer(auto_error=False)
    command_store = idempotency_store or InMemoryCommandIdempotencyStore()

    async def authenticate(
        credentials: Annotated[
            HTTPAuthorizationCredentials | None,
            Depends(security),
        ],
    ) -> ApiPrincipal:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise ApiAuthenticationError("bearer authentication is required")
        return await authorizer.authenticate(credentials.credentials)

    PrincipalDependency = Annotated[ApiPrincipal, Depends(authenticate)]
    IdempotencyDependency = Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=8,
            max_length=200,
            pattern=IDEMPOTENCY_PATTERN,
        ),
    ]

    @app.exception_handler(ApiAuthenticationError)
    async def authentication_error(
        request: Request,
        exc: ApiAuthenticationError,
    ) -> JSONResponse:
        return _error_response(
            401,
            "authentication_required",
            "Valid bearer authentication is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    @app.exception_handler(ApiAuthorizationError)
    async def authorization_error(
        request: Request,
        exc: ApiAuthorizationError,
    ) -> JSONResponse:
        return _error_response(
            403,
            "decision_access_denied",
            "The authenticated principal cannot perform this decision action.",
        )

    @app.exception_handler(DecisionWorkflowNotFound)
    async def workflow_not_found(
        request: Request,
        exc: DecisionWorkflowNotFound,
    ) -> JSONResponse:
        return _error_response(
            404,
            "decision_not_found",
            "The requested decision version was not found.",
        )

    @app.exception_handler(DecisionPreparationFailed)
    async def preparation_failed(
        request: Request,
        exc: DecisionPreparationFailed,
    ) -> JSONResponse:
        return _error_response(
            422,
            "decision_preparation_failed",
            "The decision could not be prepared from the supplied input.",
        )

    @app.exception_handler(DecisionWorkflowConflict)
    async def workflow_conflict(
        request: Request,
        exc: DecisionWorkflowConflict,
    ) -> JSONResponse:
        return _error_response(
            409,
            "decision_conflict",
            "The command conflicts with the current decision state.",
        )

    @app.exception_handler(DecisionReportNotReady)
    async def report_not_ready(
        request: Request,
        exc: DecisionReportNotReady,
    ) -> JSONResponse:
        return _error_response(
            409,
            "report_not_ready",
            "The decision does not have a final report yet.",
        )

    @app.exception_handler(CommandIdempotencyConflict)
    async def command_conflict(
        request: Request,
        exc: CommandIdempotencyConflict,
    ) -> JSONResponse:
        return _error_response(
            409,
            "idempotency_conflict",
            "The idempotency key was already used for another command.",
        )

    @app.exception_handler(OperationIdempotencyConflict)
    async def operation_conflict(
        request: Request,
        exc: OperationIdempotencyConflict,
    ) -> JSONResponse:
        return _error_response(
            409,
            "idempotency_conflict",
            "The idempotency key was already used for another command.",
        )

    @app.exception_handler(AuditRedactionConflict)
    async def audit_redaction_conflict(
        request: Request,
        exc: AuditRedactionConflict,
    ) -> JSONResponse:
        return _error_response(
            409,
            "idempotency_conflict",
            "The idempotency key was already used for another command.",
        )

    @app.exception_handler(AuditTrailNotFound)
    async def audit_not_found(
        request: Request,
        exc: AuditTrailNotFound,
    ) -> JSONResponse:
        return _error_response(
            404,
            "audit_not_found",
            "The requested decision audit trail was not found.",
        )

    @app.exception_handler(ProtocolViolation)
    async def protocol_conflict(
        request: Request,
        exc: ProtocolViolation,
    ) -> JSONResponse:
        return _error_response(
            409,
            "workflow_integrity_conflict",
            "Stored decision state failed an integrity check.",
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return _error_response(
            422,
            "request_validation_failed",
            "The request path, headers, or body are invalid.",
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        code = "route_not_found" if exc.status_code == 404 else "http_error"
        message = (
            "The requested route was not found."
            if exc.status_code == 404
            else "The HTTP request could not be completed."
        )
        return _error_response(exc.status_code, code, message, headers=exc.headers)

    @app.get("/healthz", include_in_schema=False)
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    async def readiness() -> JSONResponse:
        ready = False
        if readiness_probe is not None:
            try:
                ready = await readiness_probe.is_ready()
            except Exception:
                ready = False
        return JSONResponse(
            status_code=200 if ready else 503,
            content={"status": "ready" if ready else "not_ready"},
        )

    @app.get(
        "/v1/decisions",
        response_model=DecisionCatalog,
        responses=_error_models(401, 403, 422, 503),
    )
    async def get_decision_catalog(
        response: Response,
        principal: PrincipalDependency,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> DecisionCatalog:
        store = _require_operation_store(operation_store)
        catalog = await store.decisions(principal=principal.subject, limit=limit)
        for item in catalog.decisions:
            await authorizer.authorize(principal, item.decision_id, "decision:read")
        response.headers.update(_private_operation_headers())
        return catalog

    @app.get(
        "/v1/decisions/{decision_id}/versions",
        response_model=DecisionHistory,
        responses=_error_models(401, 403, 404, 503),
    )
    async def get_decision_versions(
        decision_id: UUID,
        response: Response,
        principal: PrincipalDependency,
    ) -> DecisionHistory | JSONResponse:
        await authorizer.authorize(principal, decision_id, "decision:read")
        store = _require_operation_store(operation_store)
        history = await store.versions(
            principal=principal.subject, decision_id=decision_id
        )
        if history is None:
            return _error_response(
                404, "decision_history_not_found", "Decision history was not found."
            )
        response.headers.update(_private_operation_headers())
        return history

    @app.post(
        "/v1/decisions",
        response_model=DecisionView | OperationReceipt,
        status_code=201,
        responses={
            202: {"model": OperationReceipt},
            **_error_models(401, 403, 409, 422, 503),
        },
    )
    async def create_decision(
        command: CreateDecisionCommand,
        idempotency_key: IdempotencyDependency,
        principal: PrincipalDependency,
        prefer: Annotated[str | None, Header()] = None,
    ) -> DecisionView | JSONResponse:
        await authorizer.authorize(principal, None, "decision:create")
        decision_id = _creation_decision_id(principal.subject, idempotency_key)
        request = DecisionPreparationRequest(
            decision_id=decision_id,
            raw_question=command.raw_question,
            minimum_risk_level=command.minimum_risk_level,
            data_classification=command.data_classification,
            evidence=tuple(
                SuppliedEvidence.model_validate(item.model_dump())
                for item in command.evidence
            ),
            evidence_sources=tuple(
                EvidenceSourceRequest.model_validate(item.model_dump())
                for item in command.evidence_sources
            ),
        )
        if _respond_async(prefer):
            store = _require_operation_store(operation_store)
            receipt = await store.accept(
                principal=principal.subject,
                idempotency_key=idempotency_key,
                fingerprint=_fingerprint("create_async", decision_id, command),
                kind=OperationKind.CREATE_DECISION,
                decision_id=decision_id,
                decision_version=1,
                classification=command.data_classification,
                request_payload=request.model_dump(mode="json"),
                accepted_at=utc_now(),
            )
            return _accepted_operation(receipt)
        return await _run_command(
            command_store,
            operation_store,
            principal,
            idempotency_key,
            "create",
            decision_id,
            command,
            lambda: service.prepare(request),
        )

    @app.get(
        "/v1/decisions/{decision_id}",
        response_model=DecisionView,
        responses=_error_models(401, 403, 404, 409, 422),
    )
    async def get_decision(
        decision_id: UUID,
        principal: PrincipalDependency,
        version: Annotated[int, Query(ge=1)] = 1,
    ) -> DecisionView:
        await authorizer.authorize(principal, decision_id, "decision:read")
        view = await service.get(decision_id, version)
        if operation_store is not None:
            await operation_store.record_decision(
                principal=principal.subject, view=view, updated_at=utc_now()
            )
        return view

    async def load_report(
        decision_id: UUID,
        version: int,
        principal: ApiPrincipal,
    ) -> DecisionReport:
        await authorizer.authorize(principal, decision_id, "decision:read")
        view = await service.get(decision_id, version)
        if view.report is None:
            raise DecisionReportNotReady("the decision report is not available")
        return view.report

    @app.get(
        "/v1/decisions/{decision_id}/report",
        response_model=DecisionReport,
        responses=_error_models(401, 403, 404, 409, 422),
    )
    async def get_decision_report(
        decision_id: UUID,
        response: Response,
        principal: PrincipalDependency,
        version: Annotated[int, Query(ge=1)] = 1,
    ) -> DecisionReport:
        response.headers.update(_private_report_headers())
        return await load_report(decision_id, version, principal)

    @app.get(
        "/v1/decisions/{decision_id}/audit",
        response_model=DecisionAuditTrail,
        responses=_error_models(401, 403, 404, 409, 422, 503),
    )
    async def get_decision_audit(
        decision_id: UUID,
        response: Response,
        principal: PrincipalDependency,
        version: Annotated[int, Query(ge=1)] = 1,
    ) -> DecisionAuditTrail:
        await authorizer.authorize(principal, decision_id, "audit:read")
        audit = _require_audit_service(audit_service)
        trail = await audit.trail(decision_id, version)
        response.headers.update(_private_report_headers())
        return trail

    @app.post(
        "/v1/decisions/{decision_id}/audit/redactions",
        response_model=AuditRecordView,
        responses=_error_models(401, 403, 409, 422, 503),
    )
    async def redact_decision_audit(
        decision_id: UUID,
        command: RedactAuditCommand,
        idempotency_key: IdempotencyDependency,
        response: Response,
        principal: PrincipalDependency,
    ) -> AuditRecordView:
        await authorizer.authorize(principal, decision_id, "audit:redact")
        audit = _require_audit_service(audit_service)
        record = await audit.redact(
            decision_id,
            command.version,
            AuditRedaction(
                target_record_id=command.target_record_id,
                field_paths=command.field_paths,
                reason=command.reason,
                actor=principal.subject,
                command_id=_redaction_command_id(
                    principal.subject,
                    decision_id,
                    idempotency_key,
                ),
            ),
            occurred_at=utc_now(),
        )
        response.headers.update(_private_report_headers())
        return AuditRecordView.model_validate(record.model_dump())

    @app.get(
        "/v1/decisions/{decision_id}/report.md",
        response_class=MarkdownResponse,
        responses=_error_models(401, 403, 404, 409, 422),
    )
    async def download_decision_report(
        decision_id: UUID,
        principal: PrincipalDependency,
        version: Annotated[int, Query(ge=1)] = 1,
    ) -> MarkdownResponse:
        report = await load_report(decision_id, version, principal)
        headers = _private_report_headers()
        headers["Content-Disposition"] = (
            f'attachment; filename="magi-{decision_id}-v{version}.md"'
        )
        return MarkdownResponse(
            DecisionReportMarkdownRenderer().render(report),
            headers=headers,
        )

    @app.post(
        "/v1/decisions/{decision_id}/confirm",
        response_model=DecisionView,
        responses=_error_models(401, 403, 404, 409, 422),
    )
    async def confirm_decision(
        decision_id: UUID,
        command: ConfirmDecisionCommand,
        idempotency_key: IdempotencyDependency,
        principal: PrincipalDependency,
    ) -> DecisionView:
        await authorizer.authorize(principal, decision_id, "decision:confirm")
        return await _run_command(
            command_store,
            operation_store,
            principal,
            idempotency_key,
            "confirm",
            decision_id,
            command,
            lambda: service.confirm(
                decision_id,
                command.version,
                confirmed_at=command.confirmed_at,
            ),
        )

    @app.post(
        "/v1/decisions/{decision_id}/run",
        response_model=DecisionView | OperationReceipt,
        responses={
            202: {"model": OperationReceipt},
            **_error_models(401, 403, 404, 409, 422, 503),
        },
    )
    async def run_decision(
        decision_id: UUID,
        command: RunDecisionCommand,
        idempotency_key: IdempotencyDependency,
        principal: PrincipalDependency,
        prefer: Annotated[str | None, Header()] = None,
    ) -> DecisionView | JSONResponse:
        await authorizer.authorize(principal, decision_id, "decision:run")
        if _respond_async(prefer):
            store = _require_operation_store(operation_store)
            current = await service.get(decision_id, command.version)
            receipt = await store.accept(
                principal=principal.subject,
                idempotency_key=idempotency_key,
                fingerprint=_fingerprint("run_async", decision_id, command),
                kind=OperationKind.RUN_DECISION,
                decision_id=decision_id,
                decision_version=command.version,
                classification=current.case.data_classification,
                request_payload={
                    "decision_id": str(decision_id),
                    "version": command.version,
                },
                accepted_at=utc_now(),
            )
            return _accepted_operation(receipt)
        return await _run_command(
            command_store,
            operation_store,
            principal,
            idempotency_key,
            "run",
            decision_id,
            command,
            lambda: service.run(decision_id, command.version),
        )

    @app.get(
        "/v1/operations",
        response_model=OperationInbox,
        responses=_error_models(401, 403, 422, 503),
    )
    async def get_operation_inbox(
        response: Response,
        principal: PrincipalDependency,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> OperationInbox:
        store = _require_operation_store(operation_store)
        inbox = await store.inbox(principal=principal.subject, limit=limit)
        for receipt in inbox.operations:
            await _authorize_operation(authorizer, principal, receipt)
        response.headers.update(_private_operation_headers())
        return inbox

    @app.get(
        "/v1/operations/{operation_id}",
        response_model=OperationReceipt,
        responses=_error_models(401, 403, 404, 503),
    )
    async def get_operation(
        operation_id: UUID,
        response: Response,
        principal: PrincipalDependency,
    ) -> OperationReceipt | JSONResponse:
        store = _require_operation_store(operation_store)
        receipt = await store.get(
            principal=principal.subject,
            operation_id=operation_id,
        )
        if receipt is None:
            return _error_response(
                404, "operation_not_found", "The requested operation was not found."
            )
        await _authorize_operation(authorizer, principal, receipt)
        response.headers.update(_private_operation_headers())
        return receipt

    @app.get(
        "/v1/operations/{operation_id}/events",
        response_model=OperationEventPage,
        responses=_error_models(401, 403, 404, 422, 503),
    )
    async def get_operation_events(
        operation_id: UUID,
        response: Response,
        principal: PrincipalDependency,
        after: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=100)] = 100,
    ) -> OperationEventPage | JSONResponse:
        store = _require_operation_store(operation_store)
        receipt = await store.get(
            principal=principal.subject,
            operation_id=operation_id,
        )
        if receipt is None:
            return _error_response(
                404, "operation_not_found", "The requested operation was not found."
            )
        await _authorize_operation(authorizer, principal, receipt)
        page = await store.events(
            principal=principal.subject,
            operation_id=operation_id,
            after_sequence=after,
            limit=limit,
        )
        if page is None:
            return _error_response(
                404, "operation_not_found", "The requested operation was not found."
            )
        response.headers.update(_private_operation_headers())
        return page

    @app.post(
        "/v1/decisions/{decision_id}/cancel",
        response_model=DecisionView,
        responses=_error_models(401, 403, 404, 409, 422),
    )
    async def cancel_decision(
        decision_id: UUID,
        command: CancelDecisionCommand,
        idempotency_key: IdempotencyDependency,
        principal: PrincipalDependency,
    ) -> DecisionView:
        await authorizer.authorize(principal, decision_id, "decision:cancel")
        return await _run_command(
            command_store,
            operation_store,
            principal,
            idempotency_key,
            "cancel",
            decision_id,
            command,
            lambda: service.cancel(
                decision_id,
                command.version,
                reason=command.reason,
            ),
        )

    return app


async def _run_command(
    store: CommandIdempotencyStore,
    catalog_store: OperationStore | None,
    principal: ApiPrincipal,
    idempotency_key: str,
    action: str,
    decision_id: UUID | None,
    command: object,
    operation: Callable[[], Awaitable[DecisionView]],
) -> DecisionView:
    view = await store.execute(
        principal=principal.subject,
        idempotency_key=idempotency_key,
        fingerprint=_fingerprint(action, decision_id, command),
        operation=operation,
    )
    if catalog_store is not None:
        await catalog_store.record_decision(
            principal=principal.subject, view=view, updated_at=utc_now()
        )
    return view


def _fingerprint(action: str, decision_id: UUID | None, command: object) -> str:
    if hasattr(command, "model_dump"):
        body = command.model_dump(mode="json")
    else:
        body = command
    material = json.dumps(
        {
            "action": action,
            "decision_id": str(decision_id) if decision_id is not None else None,
            "body": body,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _creation_decision_id(principal: str, idempotency_key: str) -> UUID:
    material = hashlib.sha256(
        f"magi-create-v1\0{principal}\0{idempotency_key}".encode("utf-8")
    ).hexdigest()
    return uuid5(CREATION_NAMESPACE, material)


def _redaction_command_id(
    principal: str, decision_id: UUID, idempotency_key: str
) -> UUID:
    material = hashlib.sha256(
        f"magi-redaction-v1\0{principal}\0{decision_id}\0{idempotency_key}".encode(
            "utf-8"
        )
    ).hexdigest()
    return uuid5(REDACTION_NAMESPACE, material)


def _error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    payload = ApiErrorResponse(
        error=ApiErrorDetail(code=code, message=message)
    ).model_dump(mode="json")
    return JSONResponse(status_code=status_code, content=payload, headers=headers)


def _error_models(*status_codes: int) -> dict[int, dict[str, object]]:
    return {
        status_code: {"model": ApiErrorResponse}
        for status_code in status_codes
    }


def _private_report_headers() -> dict[str, str]:
    return {
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    }


def _respond_async(prefer: str | None) -> bool:
    if prefer is None:
        return False
    return any(item.strip().lower() == "respond-async" for item in prefer.split(","))


def _require_operation_store(store: OperationStore | None) -> OperationStore:
    if store is None:
        raise StarletteHTTPException(status_code=503)
    return store


def _require_audit_service(service: AuditApiService | None) -> AuditApiService:
    if service is None:
        raise StarletteHTTPException(status_code=503)
    return service


def _accepted_operation(receipt: OperationReceipt) -> JSONResponse:
    return JSONResponse(
        status_code=202,
        content=receipt.model_dump(mode="json"),
        headers={
            "Preference-Applied": "respond-async",
            "Location": f"/v1/operations/{receipt.operation_id}",
            **_private_operation_headers(),
        },
    )


async def _authorize_operation(
    authorizer: DecisionAuthorizer,
    principal: ApiPrincipal,
    receipt: OperationReceipt,
) -> None:
    if receipt.kind is OperationKind.CREATE_DECISION:
        await authorizer.authorize(principal, None, "decision:create")
    else:
        await authorizer.authorize(principal, receipt.decision_id, "decision:read")


def _private_operation_headers() -> dict[str, str]:
    return {
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    }
