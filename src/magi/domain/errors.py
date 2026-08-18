"""Domain and protocol exceptions."""


class MagiDomainError(ValueError):
    """Base class for deterministic domain failures."""


class ProtocolViolation(MagiDomainError):
    """Raised when records violate the accepted MAGI protocol."""


class DuplicateBallotError(ProtocolViolation):
    """Raised when more than one ballot exists for an agent and round."""


class CrossReviewRequired(ProtocolViolation):
    """Raised when final arbitration is attempted before required cross-review."""


class InvalidStateTransition(MagiDomainError):
    """Raised when a lifecycle state transition is not allowed."""

