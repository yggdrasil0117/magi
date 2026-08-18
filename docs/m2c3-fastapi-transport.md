# M2c-3 FastAPI Transport

Status: implemented and locally verified  
Package version: 0.2.0b6  
Architecture version: 0.2  
API contract version: 1.0

## Scope

`magi.api.create_app` exposes the application commands already implemented in
M2c-2. It does not create temporary HTTP-only state and therefore does not expose
create, prepare, revision, list, report, or event endpoints before their
repositories exist.

Implemented routes:

- unauthenticated `GET /healthz` for process health;
- authenticated `GET /v1/decisions/{decision_id}?version=...`;
- authenticated and idempotent `POST .../confirm`;
- authenticated and idempotent `POST .../run`;
- authenticated and idempotent `POST .../cancel`.

Every decision response is a `DecisionView`; checkpoint metadata is never a
response model.

## Authentication and authorization

Application construction requires a `DecisionAuthorizer`. There is no default
allow-all implementation. The adapter:

1. requires an HTTP Bearer credential;
2. authenticates it into a bounded `ApiPrincipal` subject;
3. authorizes that principal for the exact decision ID and action;
4. only then reads a view or executes a command.

Authentication tokens and authorization-provider messages are not returned in
errors. Authentication failures return 401 with `WWW-Authenticate: Bearer`, and
decision authorization failures return 403.

## Command idempotency

Confirm, run, and cancel require an `Idempotency-Key`. A fingerprint binds the
key to the action, decision ID, version, and canonical request body. Repeating
the same command returns the cached immutable `DecisionView`; reusing the key for
another payload returns 409.

Keys are hashed with the authenticated principal before storage, so two users
may safely use the same client-generated value. The included in-memory store has
a bounded result cache and fixed lock shards, preventing per-key lock growth.

The store implements `CommandIdempotencyStore` and remains process-local. A
durable PostgreSQL adapter is required before multiple API processes are enabled.

## Error handling

All known transport errors use `{error: {code, message}}`. Request validation
returns a generic 422 response without echoing the body. Workflow integrity,
authorization policy, database, and provider error detail remain server-side.

## Verification

- Missing or invalid bearer credentials return a sanitized 401.
- Per-decision denial returns a sanitized 403.
- Missing decisions return 404; workflow and idempotency conflicts return 409.
- Missing/invalid headers and request bodies return a sanitized 422.
- Concurrent duplicate operations execute once.
- Idempotency is scoped by authenticated principal.
- OpenAPI declares HTTP bearer security.
- A full REST test drives the real application service and LangGraph from
  confirmation through explicit run to consensus.
- The complete suite runs 98 tests: 96 pass and 2 expected tests skip locally.

## Runtime dependencies

The local environment verified FastAPI 0.141.1, Starlette 1.6.0, Uvicorn 0.52.3,
and HTTPX 0.28.1. `pyproject.toml` uses bounded major-version requirements rather
than pinning those exact patch releases.

## Next increment

Add durable PostgreSQL command idempotency and the production composition root
that wires PostgreSQL, model runners, authentication, authorization, and the API
lifecycle. Then implement prepared-case persistence and the create/prepare REST
flow before starting client work.
