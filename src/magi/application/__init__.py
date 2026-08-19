"""Use cases and client-safe projections for MAGI interfaces."""

from .models import DecisionView, DecisionViewProjector
from .evidence import (
    EvidenceRetrievalError,
    EvidenceRetrievalGateway,
    EvidenceSourceRequest,
    RetrievedEvidence,
)
from .operations import (
    DecisionCatalog,
    DecisionCatalogEntry,
    DecisionHistory,
    OperationEvent,
    OperationEventPage,
    OperationEventType,
    OperationIdempotencyConflict,
    OperationInbox,
    OperationLease,
    OperationLeaseLost,
    OperationKind,
    OperationReceipt,
    OperationStage,
    OperationStatus,
    OperationStore,
    OperationQueue,
    validate_operation_transition,
)
from .operation_worker import (
    DecisionOperationExecutor,
    OperationExecutor,
    OperationWorker,
)
from .reporting import (
    DecisionReport,
    DecisionReportMarkdownRenderer,
    DecisionReportNotReady,
    DecisionReportProjector,
    ReviewAudit,
)
from .service import (
    DecisionApplicationService,
    DecisionAuditor,
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
    "EvidenceRetrievalError",
    "EvidenceRetrievalGateway",
    "EvidenceSourceRequest",
    "RetrievedEvidence",
    "DecisionCatalog",
    "DecisionCatalogEntry",
    "DecisionHistory",
    "DecisionApplicationService",
    "DecisionAuditor",
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
    "OperationEvent",
    "OperationEventPage",
    "OperationEventType",
    "OperationIdempotencyConflict",
    "OperationInbox",
    "OperationLease",
    "OperationLeaseLost",
    "OperationKind",
    "OperationReceipt",
    "OperationStage",
    "OperationStatus",
    "OperationStore",
    "OperationQueue",
    "DecisionOperationExecutor",
    "OperationExecutor",
    "OperationWorker",
    "validate_operation_transition",
    "DecisionWorkflowConflict",
    "DecisionWorkflowNotFound",
    "InMemoryCommandIdempotencyStore",
    "ReviewAudit",
    "SuppliedEvidence",
]
