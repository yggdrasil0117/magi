# API application

The FastAPI application is the sole execution boundary. It exposes the REST and
WebSocket contracts in `docs/api-contract.md` and returns `DecisionView`
projections only.

M2c-3 provides `magi.api.create_app`. Construction requires both a decision
application service and an authentication/per-decision authorization adapter;
there is intentionally no unauthenticated default application.

Implemented routes:

- `GET /healthz`
- `GET /v1/decisions/{decision_id}`
- `POST /v1/decisions/{decision_id}/confirm`
- `POST /v1/decisions/{decision_id}/run`
- `POST /v1/decisions/{decision_id}/cancel`

Production composition, durable HTTP-command idempotency, creation/preparation,
history, reports, and WebSocket events remain separate increments.
