# UI-D4b-2a: durable asynchronous operations

Status: accepted; contract models and D4b-2b storage implemented

## Decision

Long-running decision creation and MAGI assessment should not depend on one browser
HTTP connection remaining open. The proposed design durably accepts an operation,
returns `202 Accepted`, executes outside the request lifecycle, and exposes a
sanitized polling and event-replay resource.

Existing synchronous endpoints remain compatible. Clients explicitly request the
new behavior with `Prefer: respond-async`; the server must never silently switch a
synchronous call into background execution.

## HTTP contract

### Submit

- `POST /v1/decisions` with `Prefer: respond-async` submits create/normalization;
- `POST /v1/decisions/{decision_id}/run` with `Prefer: respond-async` submits run;
- both retain bearer authorization and `Idempotency-Key` requirements;
- acceptance returns `202`, an `OperationReceipt`, `Preference-Applied:
  respond-async`, and `Location: /v1/operations/{operation_id}`;
- durable insertion of the operation and its first event commits before `202`;
- a repeated principal/key/fingerprint returns the same operation receipt;
- the same key with another payload or execution preference returns the existing
  idempotency conflict.

### Poll and replay

- `GET /v1/operations/{operation_id}` returns the current `OperationReceipt`;
- `GET /v1/operations/{operation_id}/events?after={sequence}&limit={1..100}`
  returns an ordered `OperationEventPage`;
- a successful receipt links back to the authoritative decision resource; clients
  then fetch `DecisionView` rather than trusting event payload as the result;
- polling honors `next_poll_after_ms`; clients add jitter and cap backoff at 10 s;
- ETag/`If-None-Match` may be added without changing the representation;
- SSE is a later delivery optimization over the same stored event log, not a second
  event model.

The operation ID may appear in a URL; it is an opaque locator, not a credential.
Every read still requires bearer authentication and operation ownership plus the
corresponding decision permission.

## Client-safe models

`src/magi/application/operations.py` defines:

- kinds: `create_decision`, `run_decision`;
- statuses: `accepted`, `running`, `succeeded`, `failed`;
- public stages: `queued`, `coordinator`, `first_ballot`, `cross_review`,
  `arbitration`, `reporting`, `complete`;
- event types: `accepted`, `started`, `stage_changed`, `succeeded`, `failed`;
- `OperationReceipt`, `OperationEvent`, and cursor-based `OperationEventPage`.

There is no percentage complete. Stage ordering does not predict duration, and a
model retry must not make progress move backward or reveal attempt counts.

Terminal receipts have no next-poll hint. Success requires `stage=complete` and
`result_available=true`. Failure exposes only a stable `failure_code`, never a
provider response, prompt, trace, credential, hidden reasoning, or partial ballot.

## Public event disclosure

| Event | Visible payload | Forbidden payload |
|---|---|---|
| accepted | operation, kind, queued stage, time | request body, principal, raw key |
| started | running status, public stage | worker identity, lease, prompt |
| stage_changed | allowed stage and message code | vote, rationale, model output, percent |
| succeeded | complete status and decision link | duplicated report or private state |
| failed | stable failure code and time | provider text, traceback, partial ballots |

`first_ballot` and `cross_review` events communicate protocol stage only. Released
ballots remain governed by `DecisionView`; operation events never carry them.

## PostgreSQL records

### `magi_operations`

Proposed fields:

- operation UUID and schema version;
- principal digest, idempotency-key digest, storage key, and command fingerprint;
- kind, decision UUID, version, status, and public stage;
- encrypted-at-rest/request-protected JSONB payload required by the worker;
- data classification copied from the request/decision;
- attempt/fencing number, lease owner digest, and lease expiry;
- created, updated, completed, and retention timestamps;
- successful `DecisionView` JSONB or sanitized failure code.

The create request contains the raw question and evidence and must therefore be
protected as decision data. It is not acceptable to store only a digest because a
worker could not execute it after the HTTP request ends. Raw bearer credentials,
principal subject, and idempotency key are never stored.

### `magi_operation_events`

Proposed fields are operation UUID, strictly increasing sequence, event type,
status, public stage, stable message code, and timestamp. `(operation_id, sequence)`
is the primary key. Events and operation state update in one transaction.

Retention must delete operation request payloads as soon as policy permits while
retaining the minimum receipt/audit projection required to reconstruct a decision.

## Worker and recovery

1. A worker claims an accepted or expired operation with `FOR UPDATE SKIP LOCKED`.
2. It increments a fencing attempt, sets a bounded lease, appends `started`, and
   commits before calling application services.
3. A dedicated worker connection holds a session advisory lock derived from the
   operation storage key for the execution lifetime. Process death releases it.
4. The worker renews its observable lease; a replacement cannot execute while the
   advisory lock is held.
5. Create reuses deterministic decision identity and Coordinator invocation
   idempotency. Run resumes the stable LangGraph thread and model invocation ledger.
6. Completion writes the validated `DecisionView`, terminal receipt, and final
   event atomically. An old fencing attempt cannot overwrite a newer record.

Execution is at-least-once at the worker boundary but effect-idempotent across the
Coordinator, LangGraph checkpoint, and model ledger. The design does not claim
exactly-once external model calls after an unobservable network failure.

A separate worker pool is recommended so a long advisory lock does not starve API
or LangGraph connections. Production readiness must include stale-lease recovery,
process-kill restart, and concurrent-worker tests against disposable PostgreSQL.

## Authorization

- create acceptance requires `decision:create`;
- run acceptance requires `decision:run` for the decision;
- operation reads require the original principal digest match and current
  authorization for the associated decision action/read scope;
- returning 404 instead of 403 for another principal's opaque operation prevents
  operation-ID enumeration;
- workers run with internal service authority and never reuse user bearer tokens.

## Failure and cancellation

Provider exhaustion, integrity failure, invalid stored payload, and terminal graph
failure map to stable codes. Transient worker loss returns to claimable state after
lease expiry rather than publishing failure immediately.

Cancelling a *decision* remains the existing decision command. Cancelling an
accepted/running *operation* is out of D4b-2a scope because safe interruption during
parallel model calls requires its own protocol and user-facing semantics.

## Delivery slices after confirmation

1. D4b-2b: durable operation store, event append/read port, and real PostgreSQL tests. Implemented.
2. D4b-2c: worker claim/lease/advisory-lock loop and application adapters.
3. D4b-2d: async API responses, polling/event endpoints, authorization and OpenAPI.
4. D4b-2e: Web create/run submission, reconnect and event-driven progress UI.

## Confirmation requested

1. Adopt `Prefer: respond-async` while retaining synchronous compatibility.
2. Adopt durable polling receipts plus cursor-based event replay; SSE remains optional.
3. Adopt the four-status/seven-stage public lifecycle with no percentages.
4. Adopt protected request JSONB because background create requires its original input.
5. Adopt worker lease plus session advisory lock and fencing rules.
6. Keep operation cancellation outside this increment.

After these six decisions are accepted, D4b-2b can implement PostgreSQL storage
without reopening the browser interaction or public disclosure design.
