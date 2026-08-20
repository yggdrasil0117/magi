# API application

The FastAPI application is the sole execution boundary. It exposes the REST and
WebSocket contracts in `docs/api-contract.md` and returns `DecisionView`
projections only.

M2c-3 provides `magi.api.create_app`. Construction requires both a decision
application service and an authentication/per-decision authorization adapter;
there is intentionally no unauthenticated default application.

Implemented routes:

- `GET /healthz`
- `GET /readyz`
- `POST /v1/decisions`
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

M2c-5 makes `POST /v1/decisions` an atomic create-and-prepare command. It invokes
the non-voting Coordinator, seals supplied evidence as user-asserted, and pauses
at confirmation. Editable drafts, a separate prepare route, history, reports,
and WebSocket events remain separate increments.

M2c-6 adds database-aware readiness. `/healthz` reports only that the process is
alive. `/readyz` returns 200 only after the application service is bound and the
shared PostgreSQL runtime completes a bounded probe; otherwise it returns a
sanitized 503 response.

M5b adds `GET` and `POST /v1/decisions/{decision_id}/evaluations`. The POST
accepts only a version and rebuilds all metric inputs from server-owned audit and
invocation records. History is append-only, exact-result retries are deduplicated,
and reading/running use separate authorization actions.
