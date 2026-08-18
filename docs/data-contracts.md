# Data Contracts 1.0

This document defines logical records. M1 implements the immutable Pydantic records; database mappings remain deferred. All timestamps use UTC ISO 8601 and all IDs are UUIDs unless noted.

Decision protocol 1.0 arbitrates boolean and single-choice cases. The remaining DecisionType values are reserved for later protocols; a Coordinator must convert an open, multiple-choice, or ranking question into explicit single-choice options before a protocol 1.0 ballot.

## Shared enums

DecisionType:

- boolean
- single_choice
- multiple_choice
- ranking
- open

RiskLevel:

- low
- medium
- high

DataClassification:

- public
- internal
- sensitive
- restricted

VerificationStatus:

- user_asserted
- verified
- disputed
- unverified

AgentName:

- melchior
- balthasar
- casper

Stance:

- support
- oppose
- abstain

ArbitrationStatus:

- consensus
- majority
- unresolved
- conditional_rejection
- insufficient_information
- degraded
- failed

## DecisionCase

Required fields:

| Field | Type | Rule |
|---|---|---|
| schema_version | string | Initially 1.0 |
| decision_id | UUID | Stable across revisions |
| version | positive integer | Increment for new evidence or edited frozen case |
| title | string | Short human-readable label |
| raw_question | string | Immutable submitted text |
| question | string | Normalized, user-confirmed question |
| decision_type | enum | Drives option validation |
| options | list of DecisionOption | Include defer or no-action when relevant |
| user_constraints | list of UserConstraint | Preserve hard versus soft |
| context_claims | list of ContextClaim | Never imply verification |
| unknowns | list of string | Material missing information |
| risk_level | enum | Set before the run |
| data_classification | enum | Controls model and client exposure |

## EvidenceSnapshot

Required fields:

- snapshot_id
- decision_id
- decision_version
- created_at
- frozen_at
- evidence

Each EvidenceItem includes evidence_id, source_type, source locator, capture time, content hash, excerpt, verification status, and classification. Restricted evidence cannot enter model context.

## Ballot

Required fields:

- ballot_id
- decision_id and decision_version
- agent
- round
- selected_option, nullable only for abstention
- stance
- confidence from 0 through 1
- evidence_quality: weak, medium, or strong
- rationale_summary
- evidence_refs
- assumptions
- risks
- missing_information
- constraint_claims
- changed_from_previous
- previous_ballot_id when revised
- created_at

Do not define a hidden reasoning or chain-of-thought field.

## ConstraintClaim

Required fields:

- claim_id
- category
- statement
- severity
- likelihood
- causal_chain
- evidence_refs
- requested_action

The arbiter records validation_status and validation_reason separately. Agent submission never implies acceptance.

## ArbitrationResult

Required fields:

- arbitration_id
- decision_id and version
- status
- winning_option when applicable
- vote_count
- ballot_refs
- minority_report when applicable
- unresolved_constraints
- conditions
- required_information
- rule_version
- created_at

## DecisionEvent

Required fields:

- event_id
- decision_id and version
- monotonically increasing sequence
- type
- timestamp
- actor
- public_payload

Internal diagnostics belong in the audit record, not public_payload.

## DecisionRecord and DecisionView

DecisionRecord is the internal append-only aggregate. It may include sanitized prompts, tool requests, errors, retry metadata, model identifiers, cost, and latency.

DecisionView is the client projection used by Web, TUI, and CLI. It excludes secrets, hidden instructions, private working memory, restricted evidence, other users' data, and unreleased first-round ballots.
