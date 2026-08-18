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

M2c-4b provides `magi.api.create_production_app`. It opens the shared PostgreSQL
runtime in the FastAPI lifespan, injects `PostgresCommandIdempotencyStore`,
builds the OpenAI perspective runner and LangGraph, and requires a hashed bearer
authorization policy. Start it as an ASGI factory:

~~~powershell
python -m uvicorn magi.api.production:create_production_app --factory --host 127.0.0.1
~~~

Creation/preparation, history, reports, and WebSocket events remain separate
increments.
