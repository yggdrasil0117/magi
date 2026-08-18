# API and Event Contract 1.0

## Rules

- Prefix HTTP routes with /v1.
- Use the API as the sole execution boundary.
- Require authentication and per-decision authorization.
- Accept an idempotency key for commands that may start work.
- Return DecisionView, never DecisionRecord.
- Use REST for commands and WebSocket for event delivery.

M2c-3 requires `Authorization: Bearer ...` for every decision route and an
`Idempotency-Key` header for `confirm`, `run`, and `cancel`. Keys are 8 through
200 characters using letters, digits, `.`, `_`, `:`, or `-`, and are scoped by
the authenticated principal.

## HTTP resources

| Method and path | Purpose |
|---|---|
| POST /v1/decisions | Create a draft |
| GET /v1/decisions/{id} | Read DecisionView |
| PATCH /v1/decisions/{id} | Edit an unfrozen case |
| POST /v1/decisions/{id}/prepare | Normalize and prepare evidence |
| POST /v1/decisions/{id}/confirm | Confirm and freeze the case |
| POST /v1/decisions/{id}/run | Start voting |
| POST /v1/decisions/{id}/cancel | Cancel unfinished work |
| POST /v1/decisions/{id}/revisions | Create a new version |
| GET /v1/decisions/{id}/report | Read the final report |
| GET /v1/decisions/{id}/events | Replay authorized public events |
| GET /v1/decisions | List authorized decisions |

M2c-3 currently implements read, confirm, run, and cancel for already prepared
decision versions. It does not advertise unimplemented create, prepare,
revision, list, report, event replay, or WebSocket handlers.

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

### TUI

Provide the same decision workflow through keyboard-first screens. Consume the API and WebSocket; do not import the runner.

### CLI

Provide scriptable create, prepare, confirm, run, show, report, and event-follow commands. Support stable JSON output, non-ANSI output when redirected, and distinct exit codes for completed, insufficient, degraded, and failed outcomes.

No client calculates vote totals or arbitration status.
