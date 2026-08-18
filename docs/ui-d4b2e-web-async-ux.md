# UI-D4b-2e: asynchronous Web workflow

Status: implemented

The EVA-inspired Web workspace now supports the complete long-running create/run
interaction without holding an HTTP request open.

## Interaction

- The access rail contains an explicit create form with question, minimum risk,
  classification, bearer token, and a required submission acknowledgement.
- `run` is enabled only when `DecisionView.available_actions` contains it and still
  passes through the consequence confirmation dialog.
- Accepted work displays an angular operation monitor with the public protocol stages:
  queued, Coordinator, first ballot, cross-review, arbitration, reporting, complete.
- Event rows show only sequence, public stage, and stable message code.
- On success the client fetches the authoritative `DecisionView`; it never constructs
  a decision result from progress events.

## Recovery and security

- The browser stores only the opaque operation ID in `sessionStorage`.
- Bearer tokens and idempotency intents remain in memory and are absent from URL,
  cookies, local storage, and session storage.
- After refresh, the operation ID is prefilled; the user must re-enter a bearer token.
- Unknown submit outcomes retain the same frozen idempotency intent for safe retry.
- Starting a new monitor aborts the previous polling loop.
- Polling follows server hints bounded between 250 ms and 10 seconds.

## Loopback proxy

The proxy now allowlists only the new create/run and operation read/event paths,
validates event cursor/limit queries, forwards `Prefer`, and rewrites the upstream
operation location to the same-origin `/api` path. All other methods and paths remain
closed.
