"""FastAPI adapter and transport-level contracts."""

from .app import DecisionApiService, create_app
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
    RunDecisionCommand,
)

__all__ = [
    "ApiAuthenticationError",
    "ApiAuthorizationError",
    "ApiErrorDetail",
    "ApiErrorResponse",
    "ApiPrincipal",
    "CancelDecisionCommand",
    "ConfirmDecisionCommand",
    "DecisionApiService",
    "DecisionAuthorizer",
    "RunDecisionCommand",
    "create_app",
]
