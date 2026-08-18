# UI-D4c-1: authorized operation inbox

Status: implemented

The first UI-D4c discovery surface lists durable background work for the authenticated
principal. It deliberately remains distinct from a decision catalog: operation history
cannot prove a complete set of accessible decisions or versions.

## Contract

`GET /v1/operations?limit=1..100` returns:

- recent `OperationReceipt` projections ordered by latest update;
- the total count of accepted/running work;
- the total count of failed work.

The PostgreSQL query hashes the authenticated subject before lookup. Public rows do not
contain the subject, bearer credential, raw idempotency key, request payload, worker
identity, prompts, or ballots. Each returned receipt is also checked against current
create/read authority before the response is released.

## Web interaction

The access rail accepts a memory-only bearer token and renders an angular activity
list with active/failed counts. Selecting an item enters the existing event monitor.
An empty result is a valid authorized state, not an error.

The loopback proxy permits only the exact inbox path and a bounded `limit` query.
Response caching remains `private, no-store`.

## Following slice

UI-D4c-2 introduces an explicit principal-scoped decision/version catalog. It does not
derive history from this operation inbox or from browser state.
