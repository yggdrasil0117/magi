# M2b-2b PostgreSQL Persistence

Status: implemented and locally verified; real database smoke test is optional  
Package version: 0.2.0b3  
Architecture version: 0.2

## Scope

This increment makes model-call idempotency and LangGraph decision state durable.
One asynchronous PostgreSQL connection pool is shared by the invocation ledger
and `AsyncPostgresSaver`.

## Invocation ledger

`magi_model_invocations` stores one sanitized, append-only record for each model
attempt or cache reuse. `magi_model_ballots` stores the canonical successful
ballot and has a primary key on the SHA-256 idempotency key.

Before reading or writing an idempotency key, the runner enters the ledger's
guard. The PostgreSQL implementation holds a session advisory lock and reuses
that same connection for the cache lookup and transaction. This serializes the
same logical model call across application processes. Unrelated keys can proceed
concurrently.

The database stores no raw prompt, provider response, API key, provider error
message, or hidden reasoning.

## LangGraph checkpoints

`PostgresPersistenceRuntime` exposes an `AsyncPostgresSaver` backed by the shared
pool. `open(setup=True)` creates both MAGI and LangGraph tables. The saver uses
LangGraph's JSON-plus serializer with its explicit safe module allowlist.

Each decision uses a stable `<decision_id>:<version>` thread ID. The helper
rejects non-positive versions and IDs over the PostgreSQL checkpointer's
255-character limit.

## Configuration

Copy `.env.example`, then set a non-production database URL:

~~~text
MAGI_DATABASE_URL=postgresql://magi:<password>@127.0.0.1:5432/magi
~~~

For the optional integration test, use a disposable database only:

~~~text
MAGI_TEST_POSTGRES_DSN=postgresql://magi:<password>@127.0.0.1:5432/magi
~~~

`compose.yaml` defines a loopback-only PostgreSQL 17 service. Set
`MAGI_DB_PASSWORD` before starting it; never commit the real password.

## Verification

- Protocol tests verify schema setup, transaction boundaries, advisory locking,
  canonical-ballot lookup, and same-connection reuse without requiring a server.
- Two independent runner instances sharing one ledger issue only one provider
  call for the same idempotency key.
- The full suite runs 61 tests: 59 pass and 2 skip locally.
- One skip is the installed-LangGraph negative-path test.
- The second is the real PostgreSQL restart test because this workstation has no
  Docker executable or configured `MAGI_TEST_POSTGRES_DSN`.
- When configured, the integration test persists a canonical ballot, interrupts
  a graph, closes the first runtime, opens a second runtime, reloads that ballot,
  and resumes the same thread to consensus.

## Remaining validation

Run the restart integration test against a disposable PostgreSQL instance before
enabling multiple production application processes. Then perform the controlled
live-model evaluation described in M2b-2a.
