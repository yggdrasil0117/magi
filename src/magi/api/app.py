"""FastAPI transport adapter for the MAGI decision application service."""

import hashlib
import json
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Annotated, Protocol
from uuid import UUID, uuid5

from fastapi import Depends, FastAPI, Header, Query, Request
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
    DecisionView,
    DecisionWorkflowConflict,
    DecisionWorkflowNotFound,
    InMemoryCommandIdempotencyStore,
    SuppliedEvidence,
)
from magi.domain import ProtocolViolation

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
)


IDEMPOTENCY_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,199}$"
CREATION_NAMESPACE = UUID("7d064bfc-7ab6-4e37-a7ad-94d92b967a23")


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


def create_app(
    service: DecisionApiService,
    authorizer: DecisionAuthorizer,
    *,
    idempotency_store: CommandIdempotencyStore | None = None,
    lifespan: Callable[[FastAPI], AbstractAsyncContextManager[None]] | None = None,
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

    @app.post(
        "/v1/decisions",
        response_model=DecisionView,
        status_code=201,
        responses=_error_models(401, 403, 409, 422),
    )
    async def create_decision(
        command: CreateDecisionCommand,
        idempotency_key: IdempotencyDependency,
        principal: PrincipalDependency,
    ) -> DecisionView:
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
        )
        return await _run_command(
            command_store,
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
        return await service.get(decision_id, version)

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
        response_model=DecisionView,
        responses=_error_models(401, 403, 404, 409, 422),
    )
    async def run_decision(
        decision_id: UUID,
        command: RunDecisionCommand,
        idempotency_key: IdempotencyDependency,
        principal: PrincipalDependency,
    ) -> DecisionView:
        await authorizer.authorize(principal, decision_id, "decision:run")
        return await _run_command(
            command_store,
            principal,
            idempotency_key,
            "run",
            decision_id,
            command,
            lambda: service.run(decision_id, command.version),
        )

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
    principal: ApiPrincipal,
    idempotency_key: str,
    action: str,
    decision_id: UUID | None,
    command: object,
    operation: Callable[[], Awaitable[DecisionView]],
) -> DecisionView:
    return await store.execute(
        principal=principal.subject,
        idempotency_key=idempotency_key,
        fingerprint=_fingerprint(action, decision_id, command),
        operation=operation,
    )


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
