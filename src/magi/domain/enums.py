"""Shared enums for MAGI decision records and protocol flow."""

from enum import StrEnum


class DecisionType(StrEnum):
    BOOLEAN = "boolean"
    SINGLE_CHOICE = "single_choice"
    MULTIPLE_CHOICE = "multiple_choice"
    RANKING = "ranking"
    OPEN = "open"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DataClassification(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    SENSITIVE = "sensitive"
    RESTRICTED = "restricted"


class VerificationStatus(StrEnum):
    USER_ASSERTED = "user_asserted"
    VERIFIED = "verified"
    DISPUTED = "disputed"
    UNVERIFIED = "unverified"


class ConstraintStrength(StrEnum):
    HARD = "hard"
    SOFT = "soft"


class AgentName(StrEnum):
    MELCHIOR = "melchior"
    BALTHASAR = "balthasar"
    CASPER = "casper"


class Stance(StrEnum):
    SUPPORT = "support"
    OPPOSE = "oppose"
    ABSTAIN = "abstain"


class EvidenceQuality(StrEnum):
    WEAK = "weak"
    MEDIUM = "medium"
    STRONG = "strong"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Likelihood(StrEnum):
    UNLIKELY = "unlikely"
    POSSIBLE = "possible"
    LIKELY = "likely"
    ALMOST_CERTAIN = "almost_certain"


class ConstraintValidationStatus(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ArbitrationStatus(StrEnum):
    CONSENSUS = "consensus"
    MAJORITY = "majority"
    UNRESOLVED = "unresolved"
    CONDITIONAL_REJECTION = "conditional_rejection"
    INSUFFICIENT_INFORMATION = "insufficient_information"
    DEGRADED = "degraded"
    FAILED = "failed"


class RoundAction(StrEnum):
    ARBITRATE = "arbitrate"
    CROSS_REVIEW = "cross_review"
    CONDITIONAL_REJECTION = "conditional_rejection"
    INSUFFICIENT_INFORMATION = "insufficient_information"
    DEGRADED = "degraded"
    FAILED = "failed"


class DecisionState(StrEnum):
    CREATED = "created"
    NORMALIZED = "normalized"
    WAITING_FOR_USER = "waiting_for_user"
    EVIDENCE_READY = "evidence_ready"
    FIRST_BALLOT = "first_ballot"
    CROSS_REVIEW = "cross_review"
    ARBITRATED = "arbitrated"
    COMPLETED = "completed"
    INSUFFICIENT_INFORMATION = "insufficient_information"
    DEGRADED = "degraded"
    FAILED = "failed"
    CANCELLED = "cancelled"

