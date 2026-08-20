"""FastAPI adapter and transport-level contracts."""

from .app import (
    AuditApiService,
    DecisionApiService,
    EvaluationApiService,
    ReadinessProbe,
    create_app,
)
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
    CreateDecisionCommand,
    EvidenceSourceCommand,
    RedactAuditCommand,
    RunDecisionCommand,
    RunEvaluationCommand,
    SuppliedEvidenceCommand,
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
    "AuditApiService",
    "CancelDecisionCommand",
    "ConfirmDecisionCommand",
    "CreateDecisionCommand",
    "DecisionApiService",
    "EvaluationApiService",
    "DecisionAuthorizer",
    "EvidenceSourceCommand",
    "HashedBearerAuthorizer",
    "HashedBearerCredential",
    "HashedBearerPolicy",
    "ProductionConfigurationError",
    "ProductionSettings",
    "ReadinessProbe",
    "RedactAuditCommand",
    "RunDecisionCommand",
    "RunEvaluationCommand",
    "SuppliedEvidenceCommand",
    "create_app",
    "create_production_app",
]
