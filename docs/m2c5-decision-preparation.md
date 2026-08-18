# M2c-5 Decision Preparation

Status: implemented and locally verified
Package version: 0.2.0b9
Architecture version: 0.2
API contract version: 1.0

## Scope

`POST /v1/decisions` now creates and prepares one decision version atomically.
It accepts the raw question, a minimum risk level, data classification, and up
to 50 supplied evidence items. It returns the shared `DecisionView` paused at
the user-confirmation gate.

The command deliberately does not accept a decision ID, version, evidence ID,
content hash, or verification status. Those fields belong to the application
boundary.

## Preparation flow

1. Authenticate the bearer token and require `decision:create`.
2. Derive a stable server-owned decision ID from the principal and idempotency
   key.
3. Invoke the non-voting Coordinator with the raw question and sealed risk and
   classification bounds.
4. Assign evidence IDs in request order, calculate SHA-256 excerpt hashes, and
   mark every supplied item `user_asserted`.
5. Freeze an `EvidenceSnapshot` with one application timestamp.
6. Store a canonical preparation-request fingerprint in checkpoint state.
7. Enter LangGraph and pause at `confirm_case`.

No Melchior, Balthasar, or Casper model is invoked during creation. Voting
still requires separate confirmation and run commands.

## Retry identity

The decision ID is a namespaced UUID derived from a SHA-256 digest of the
authenticated principal and idempotency key. The raw values are not embedded in
the UUID. Repeating the same principal/key pair therefore addresses the same
LangGraph thread even when a process fails after checkpoint creation but before
the durable command result is inserted.

The checkpointed preparation fingerprint lets a retry return the saved view
without making a second Coordinator call. A different body for the same stable
ID is rejected. The transport fingerprint independently enforces the durable
idempotency-key conflict when its result row exists.

## Authorization limitation

Decision creation is a global action because the resource does not exist before
the command. The initial static hashed-policy adapter therefore permits
`decision:create` only on credentials with the explicit
`allow_all_decisions: true` flag. This ensures the creator can access the random
resource after restart, but it is intentionally broad.

A multi-tenant deployment should replace the static adapter with an external
`DecisionAuthorizer` that persists creator ownership. That ownership store is
not silently simulated in process memory.

## Evidence boundary

Supplied evidence is not treated as independently verified. The application:

- assigns `E-001`, `E-002`, and subsequent IDs;
- hashes the UTF-8 excerpt on the server;
- seals verification status as `user_asserted`;
- preserves the supplied source, capture time, and classification;
- excludes restricted evidence from `DecisionView` and perspective prompts
  through the existing projector and prompt boundary.

This increment does not retrieve URLs, inspect uploaded files, validate source
claims, or promote evidence to `verified`.

## Error and idempotency behavior

- Missing authentication, creation permission, or idempotency key fails before
  Coordinator invocation.
- Invalid request structure returns the stable validation error envelope.
- Coordinator refusal, malformed output, or provider failure becomes the
  sanitized `decision_preparation_failed` response.
- Failed creation is not cached and may be retried.
- A repeated successful command returns the stored `DecisionView` without a
  second Coordinator call.

## Verification

- Application tests seal decision identity, evidence identity, hashes, and
  verification status before the confirmation interrupt.
- Preparation failure hides provider details.
- Transport tests verify authentication, creation permission, successful
  replay, stable retry identity, and sanitized failures.
- Checkpoint replay returns the prepared view without invoking Coordinator
  again and rejects changed preparation inputs.
- Authorization tests require explicit creation permission and reject scoped
  static creator credentials.
- Production composition constructs and injects the Coordinator.
- The complete suite runs 117 tests: 115 pass and 2 expected tests skip locally.

## M2 closure

M2c-6 completes the M2 code and local acceptance scope with database-aware
readiness and an opt-in real-service acceptance flow. Editable drafts and the
separate prepare route remain product-surface additions, not blockers for the
M2 three-perspective exit criterion.
