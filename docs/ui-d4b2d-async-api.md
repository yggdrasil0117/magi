# UI-D4b-2d: asynchronous operation API

Status: implemented

Create and run retain their synchronous behavior unless the caller explicitly sends
`Prefer: respond-async`. The asynchronous response is committed before returning
`202 Accepted` and includes `Preference-Applied`, an operation `Location`, and
private/no-store cache controls.

## Resources

- `POST /v1/decisions` accepts asynchronous create.
- `POST /v1/decisions/{decision_id}/run` accepts asynchronous run.
- `GET /v1/operations/{operation_id}` returns the current receipt.
- `GET /v1/operations/{operation_id}/events?after=0&limit=100` replays ordered,
  client-safe public events.

The receipt carries the authoritative decision identity and version. After success,
clients fetch that decision resource to obtain `DecisionView`; operation events never
duplicate ballots, reports, prompts, or internal reasoning.

## Security and compatibility

- Bearer authentication and the existing action permission are checked before submit.
- Polling first performs principal-scoped lookup. A different principal receives 404
  before authorization, preventing operation identifier enumeration.
- Create polling requires current create authority; run polling requires current read
  authority for the associated decision.
- The request body, principal, and raw idempotency key are absent from public models.
- Reusing a key across synchronous/asynchronous modes conflicts through the shared
  PostgreSQL storage-key guard.
- Synchronous clients remain compatible when the preference header is absent.

## Production lifecycle

Production startup now launches the leased operation worker after PostgreSQL,
LangGraph, the model runner, and Coordinator are ready. Shutdown cancels and joins the
worker before closing persistence; cancellation leaves an unfinished operation for
lease-based recovery rather than publishing a false failure.
