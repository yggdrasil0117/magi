# UI-D4b-2b: PostgreSQL operation persistence

Status: implemented and locally verified; real PostgreSQL test remains environment-gated

## Delivered

`PostgresOperationStore` implements the application `OperationStore` port using the
shared PostgreSQL runtime. Runtime setup now creates operation records and their
append-only public event log alongside command results, model invocations, ballots,
and LangGraph checkpoints.

`magi_operations` stores digested ownership/idempotency identifiers, fingerprint,
operation/decision identity, data classification, protected request JSONB, public
status/stage, fencing and lease fields reserved for D4b-2c, validated result or
stable failure code, event cursor, timestamps, and retention boundary.

`magi_operation_events` stores only the public event contract. The initial
`accepted` operation row and sequence-1 event commit atomically.

## Idempotency and isolation

- operation IDs are deterministic UUIDv5 values derived from the principal-scoped
  storage digest, not from raw identity or key values;
- one session advisory lock serializes acceptance for the same storage key;
- matching repeats return the persisted receipt without another insert;
- a different fingerprint raises `OperationIdempotencyConflict`;
- synchronous command results and async operations check each other's tables under
  the same storage key and conflict in both directions;
- raw principal and idempotency key never enter SQL parameters;
- operation reads include the principal digest and return `None` for non-owners.

The protected request payload intentionally remains recoverable because a future
worker needs it after the original HTTP request ends. Its classification is stored
with the operation so retention and database controls can follow decision policy.

## Reads and integrity

Receipt reads reconstruct and validate `OperationReceipt`. A successful row must
contain a valid `DecisionView`; non-success rows cannot contain a result. Event reads
require ownership, accept `after_sequence`, fetch at most 100 records, request one
extra row to calculate `has_more`, and validate identity, order, event/status shape,
and exact next cursor.

Invalid persisted receipts, results, or events raise `ProtocolViolation` rather
than leaking raw data or returning an ambiguous representation.

## Verification

- schema creation is transactional;
- acceptance writes one receipt and first event transaction;
- replay, fingerprint conflict, and cross-mode conflict are tested;
- raw principal/key absence and protected payload presence are tested;
- owner masking, result validation, bounded cursor pagination, and event validation
  are tested without a database server;
- the optional real PostgreSQL restart test now accepts an operation in one runtime,
  replays it and reads its event from a second runtime;
- the real test still runs only when `MAGI_TEST_POSTGRES_DSN` targets a disposable DB.

## Next increment

UI-D4b-2c will implement worker claim, fencing, lease renewal, session advisory lock,
atomic state/event transitions, stale-lease recovery, and application-service
execution. No API route or background task is activated by this storage increment.
