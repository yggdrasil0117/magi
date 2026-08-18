"""Use cases and client-safe projections for MAGI interfaces."""

from .models import DecisionView, DecisionViewProjector
from .reporting import (
    DecisionReport,
    DecisionReportMarkdownRenderer,
    DecisionReportNotReady,
    DecisionReportProjector,
    ReviewAudit,
)
from .service import (
    DecisionApplicationService,
    DecisionGraph,
    DecisionWorkflowConflict,
    DecisionWorkflowNotFound,
)
from .idempotency import (
    CommandIdempotencyConflict,
    CommandIdempotencyStore,
    InMemoryCommandIdempotencyStore,
)
from .preparation import (
    DecisionPreparationFailed,
    DecisionPreparationRequest,
    SuppliedEvidence,
)

__all__ = [
    "DecisionApplicationService",
    "CommandIdempotencyConflict",
    "CommandIdempotencyStore",
    "DecisionGraph",
    "DecisionPreparationFailed",
    "DecisionPreparationRequest",
    "DecisionReport",
    "DecisionReportMarkdownRenderer",
    "DecisionReportNotReady",
    "DecisionReportProjector",
    "DecisionView",
    "DecisionViewProjector",
    "DecisionWorkflowConflict",
    "DecisionWorkflowNotFound",
    "InMemoryCommandIdempotencyStore",
    "ReviewAudit",
    "SuppliedEvidence",
]
