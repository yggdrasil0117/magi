# M2c-4b Production Composition

Status: implemented and locally verified; live services remain operator-run
Package version: 0.2.0b8
Architecture version: 0.2
API contract version: 1.0

## Scope

`magi.api.create_production_app` is the first production ASGI factory. Unlike
the transport-level `create_app`, it provides no test-oriented or in-memory
fallbacks. Missing configuration, an invalid authorization policy, database
startup failure, missing skills, or model-runner construction failure prevents
the process from serving requests.

The factory uses FastAPI lifespan to:

1. open `PostgresPersistenceRuntime` and prepare its schemas;
2. validate the shared protocol and all three perspective skill files;
3. construct three isolated OpenAI structured-output model boundaries;
4. compile LangGraph with the PostgreSQL checkpointer;
5. bind `DecisionApplicationService` to the HTTP routes;
6. release the shared PostgreSQL pool during shutdown or failed startup.

The durable command-idempotency adapter exists before route construction and is
always injected into the production API.

## Required configuration

| Variable | Purpose |
|---|---|
| `MAGI_DATABASE_URL` | PostgreSQL connection string |
| `OPENAI_API_KEY` | Server-side OpenAI credential |
| `MAGI_OPENAI_MODEL` | Explicit model identifier; no fallback model |
| `MAGI_SKILLS_DIR` | Directory containing `magi-core` and three perspective skills |
| `MAGI_AUTH_POLICY_FILE` | Versioned hashed bearer policy JSON |

Optional bounds are `MAGI_POSTGRES_MIN_SIZE` (default 1),
`MAGI_POSTGRES_MAX_SIZE` (default 10, minimum 2), and
`MAGI_MODEL_MAX_ATTEMPTS` (default 2, range 1 through 5).

Database URLs and OpenAI keys are excluded from `ProductionSettings` string
representations. The production factory stores only the selected model name and
runtime object on FastAPI state, not those secrets.

## Hashed bearer policy

Copy `config/auth-policy.example.json` to the path configured by
`MAGI_AUTH_POLICY_FILE`. Replace its zero digest, subject, permissions, and
decision IDs. Generate at least 32 random bytes for each bearer token, then
compute its digest without placing the raw token in shell history:

~~~powershell
python -c "import getpass,hashlib; print(hashlib.sha256(getpass.getpass('Bearer token: ').encode()).hexdigest())"
~~~

The policy stores a SHA-256 digest, not the raw token. Each credential has one
unique subject, an explicit action set, and either an explicit decision-ID
allowlist or `allow_all_decisions: true`. Duplicate digests and subjects,
unknown actions, and unscoped credentials fail validation.

M2c-5 adds `decision:create`. Because the static adapter has no durable
creator-ownership store, this action requires an explicit
`allow_all_decisions: true` flag. Scoped resource credentials cannot create.

A digest does not make a weak token safe against offline guessing. The static
adapter is appropriate for the initial controlled deployment. A broader
deployment should inject an identity-provider-backed `DecisionAuthorizer`
without changing the application service or routes.

## Launch

After installing the package and configuring `.env`, start the ASGI factory:

~~~powershell
python -m uvicorn magi.api.production:create_production_app --factory --host 127.0.0.1 --port 8000
~~~

Binding to a public interface, TLS termination, proxy trust, rate limits, and
secret injection belong to the deployment environment and are not enabled by
this command.

## Verification

- Hashed authentication accepts only a matching digest and never echoes a raw
  bearer value.
- Authorization enforces both action and decision allowlists.
- All-decisions access requires an explicit policy flag and still limits
  actions.
- Empty, duplicate, malformed, and unscoped policy records fail closed.
- FastAPI lifespan opens the shared runtime before composing the graph.
- Normal shutdown and model-runner startup failure both close the runtime.
- Settings reject missing values and unsafe pool/retry bounds.
- The complete suite runs 112 tests: 110 pass and 2 expected tests skip locally.

## Deliberate limits

M2c-5 now adds Coordinator-backed atomic creation and preparation. Editable
drafts remain deferred. The workstation still has no configured real
PostgreSQL test DSN, and no live OpenAI call is made in the automated suite.

## Next increment

Run the M2c-6 acceptance increment with live PostgreSQL/OpenAI smoke coverage,
readiness checks, and the final M2 acceptance record.
