# M4b: Append-only Audit and Reconstruction

Status: implemented.

Package version: 0.4.0a2.

M4b separates canonical decision audit from LangGraph operational checkpoints.
Every application projection after preparation, confirmation, cancellation, or
execution captures a validated `AuditDecisionState`. The state contains the case,
frozen evidence snapshot, constraint validations, first and review ballots,
round assessment, arbitration result, phase, and cancellation status required to
reproduce the decision.

## Integrity model

Audit records are partitioned by decision ID and version. Each record has a
monotonic sequence, canonical JSON payload hash, previous-record hash, and
envelope hash. Identical payloads are idempotent, so command retries repair a
missing audit write without duplicating history. Reads verify identity, sequence,
payload hashes, and the complete chain before returning or reconstructing data.

The PostgreSQL adapter serializes appends with a transaction-scoped advisory lock
and enforces uniqueness for sequences, record identities, payloads, and hashes.
A database trigger rejects `UPDATE` and `DELETE` on the audit table. Operational
checkpoint tables remain mutable and are not treated as audit truth.

## Redaction model

Redaction never edits a canonical record. An `AuditRedaction` is appended to the
same hash chain and names a target record plus explicit JSON Pointer fields,
reason, and actor. Operator-visible projection applies `[REDACTED]` overlays only
after verifying the chain. Canonical reconstruction continues to use the original
record, preserving reproducibility and proof that a redaction occurred.

The current increment exposes redaction through the internal application service;
authenticated API and UI controls are deferred to M4c.

## Report reconstruction

`DecisionAuditService.reconstruct_report` loads and verifies the audit chain,
selects the latest state containing an arbitration result, validates every domain
record, and invokes the deterministic `DecisionReportProjector`. It does not read
a LangGraph checkpoint or a stored report and performs no model call.

Checkpoint and audit writes cannot be one atomic transaction because LangGraph
owns checkpoint persistence. The command fails if the audit append fails, and a
subsequent read or idempotent retry captures the saved state again. Stable record
identity makes this repair safe.

