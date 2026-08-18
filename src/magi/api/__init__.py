"""FastAPI adapter and transport-level contracts."""

from .app import DecisionApiService, create_app
from .auth import (
    ApiAuthenticationError,
    ApiAuthorizationError,
    ApiPrincipal,
    HashedBearerAuthorizer,
    HashedBearerCredential,
    HashedBearerPolicy,
    DecisionAuthorizer,
)
from .models import (
    ApiErrorDetail,
    ApiErrorResponse,
    CancelDecisionCommand,
    ConfirmDecisionCommand,
    RunDecisionCommand,
)
from .production import (
    ProductionConfigurationError,
    ProductionSettings,
    create_production_app,
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
    "HashedBearerAuthorizer",
    "HashedBearerCredential",
    "HashedBearerPolicy",
    "ProductionConfigurationError",
    "ProductionSettings",
    "RunDecisionCommand",
    "create_app",
    "create_production_app",
]
