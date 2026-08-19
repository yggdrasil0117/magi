# API and Event Contract 1.0

## Rules

- Prefix HTTP routes with /v1.
- Use the API as the sole execution boundary.
- Require authentication and per-decision authorization.
- Accept an idempotency key for commands that may start work.
- Return DecisionView, never DecisionRecord.
- Use REST for commands and WebSocket for event delivery.

M2c-5 requires `Authorization: Bearer ...` for every decision route and an
`Idempotency-Key` header for `create`, `confirm`, `run`, and `cancel`. Keys are
8 through 200 characters using letters, digits, `.`, `_`, `:`, or `-`, and are
scoped by the authenticated principal.

## HTTP resources

| Method and path | Purpose |
|---|---|
| GET /healthz | Process liveness without dependency claims |
| GET /readyz | Application and PostgreSQL readiness |
| POST /v1/decisions | Create a draft |
| GET /v1/decisions/{id} | Read DecisionView |
| PATCH /v1/decisions/{id} | Edit an unfrozen case |
| POST /v1/decisions/{id}/prepare | Normalize and prepare evidence |
| POST /v1/decisions/{id}/confirm | Confirm and freeze the case |
| POST /v1/decisions/{id}/run | Start voting |
| POST /v1/decisions/{id}/cancel | Cancel unfinished work |
| POST /v1/decisions/{id}/revisions | Create a new version |
| GET /v1/decisions/{id}/report | Read the final report |
| GET /v1/decisions/{id}/report.md | Download the final report as Markdown |
| GET /v1/decisions/{id}/audit | Read the verified visible audit chain |
| POST /v1/decisions/{id}/audit/redactions | Append a redaction overlay |
| GET /v1/decisions/{id}/events | Replay authorized public events |
| GET /v1/decisions | List authorized decisions |

M2c-5 implements an atomic `POST /v1/decisions` create-and-prepare vertical
slice in addition to read, confirm, run, and cancel. The command accepts a raw
question, risk floor, data classification, up to 50 supplied evidence items,
and up to 20 authorized HTTPS `evidence_sources`. It returns a `DecisionView`
paused at user confirmation. Editable drafts
and the separate prepare route remain unimplemented, as do revision, list,
report, event replay, and WebSocket handlers.

M3a embeds a structured `report` in terminal `DecisionView` responses. M3b adds
the dedicated JSON report route and a deterministic Markdown attachment. Both
reuse `decision:read` authorization because they expose the same report fields,
return `report_not_ready` until arbitration completes, and set private no-store
cache controls. Report routes do not accept idempotency keys because they are
read-only.

M4c requires the separate `audit:read` action for audit history and
`audit:redact` for redaction overlays. Redaction commands require an idempotency
key and accept a decision version, target audit record ID, simple JSON Pointer
paths, and a reason. Actor, command identity, and occurrence time are server
owned. Audit responses are private and never cacheable.

Decision creation requires the explicit `decision:create` permission. The
server derives a stable decision ID from the authenticated principal and
idempotency key so a retry after partial persistence returns to the same
workflow thread. Clients cannot provide decision IDs, evidence IDs, hashes, or
verification status during creation.

Health routes do not require bearer authentication and reveal no connection
details. `/readyz` returns `{"status":"ready"}` with status 200 only when the
production service is bound and PostgreSQL answers within the bounded probe.
All other states return status 503 with `{"status":"not_ready"}`.

## Error envelope

Transport errors use one stable structure and never echo bearer credentials,
request bodies, provider messages, or authorization policy detail:

~~~json
{
  "error": {
    "code": "decision_conflict",
    "message": "The command conflicts with the current decision state."
  }
}
~~~

Current mappings include 401 authentication required, 403 access denied, 404
decision or route not found, 409 workflow/idempotency conflict, and 422 request
validation failure.

Mutating a frozen version returns a conflict response and directs the client to create a revision.

## WebSocket

Subscribe at:

~~~text
/ws/v1/decisions/{decision_id}?after_sequence={n}
~~~

Use after_sequence to replay missed events. The socket carries events and heartbeat messages only; state-changing commands remain REST calls.

## Public event types

- decision.created
- case.normalization_started
- case.normalized
- user_confirmation_required
- evidence.snapshot_created
- run.started
- agent.started
- agent.tool_status
- agent.completed
- first_ballot.completed
- cross_review.started
- agent.review_completed
- cross_review.completed
- arbitration.completed
- decision.completed
- decision.degraded
- decision.failed

Before first_ballot.completed, agent events expose status only. They must not expose partial votes, rationale, or tool results.

## Client boundaries

### Web

Provide draft editing, upload, confirmation, live status, evidence inspection, reports, history, revision comparison, and export.

The production Web workspace fetches reports and full workflow resources through a
loopback same-origin proxy, keeps bearer tokens in page memory, and inserts external
content with DOM `textContent`.

### TUI

Provide the same decision workflow through keyboard-first screens. Consume the API and WebSocket; do not import the runner.

The keyboard-first `magi-tui` workflow covers inbox, read, history, create, confirm,
run, cancel, and operation watch without importing the runner.

### CLI

The `magi` CLI provides scriptable inbox, create, confirm, run, cancel, show, history,
and operation-watch commands with stable JSON and distinct exit-code families.

No client calculates vote totals or arbitration status.
