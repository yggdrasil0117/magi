# M2c-4a PostgreSQL Command Idempotency

Status: implemented and locally verified; real database test remains optional
Package version: 0.2.0b7
Architecture version: 0.2
API contract version: 1.0

## Scope

`PostgresCommandIdempotencyStore` implements the M2c-3
`CommandIdempotencyStore` port. It shares the existing asynchronous PostgreSQL
pool with LangGraph checkpoints and model-invocation records.

`PostgresPersistenceRuntime.open(setup=True)` now creates all three persistence
areas:

- sanitized model invocation attempts and canonical ballots;
- API command results;
- LangGraph checkpoints.

The app factory still defaults to the bounded in-memory store for isolated
tests. A production composition root must explicitly inject
`runtime.command_idempotency_store`.

## Stored record

`magi_api_command_results` stores:

- a versioned storage digest;
- a principal digest;
- an idempotency-key digest;
- the canonical command fingerprint;
- the resulting immutable `DecisionView` as JSONB;
- creation time.

Raw bearer credentials, principal subjects, idempotency keys, request bodies,
provider output, and checkpoint metadata are not stored in this table.

The persisted response intentionally contains the same authorized,
client-visible decision data carried by `DecisionView`, including case fields.
It is therefore decision data rather than a minimal command receipt, and its
database access controls and retention must follow the decision-data
classification.

Every cached JSONB response is validated back into `DecisionView`. Invalid or
corrupted stored data raises a workflow integrity failure instead of being
returned to a client.

## Cross-process serialization

The store derives a signed 64-bit lock ID from the versioned storage digest and
holds a session-level PostgreSQL advisory lock while it:

1. looks up an existing result;
2. rejects a different fingerprint or returns the validated cached view;
3. executes the command on a miss;
4. inserts the successful result in an explicit transaction;
5. releases the advisory lock in a `finally` block.

Failed operations are not cached. The same application command remains
state-idempotent, so a database failure after command completion can be retried
without reopening a completed workflow transition.

Because one pool connection is held as the cross-process guard while LangGraph
uses the same pool, `PostgresPersistenceRuntime` now rejects `max_size < 2`.

## Layer correction

`decision_thread_id` moved from infrastructure to orchestration. Infrastructure
continues to re-export it for compatibility. This removes the previous
application-to-PostgreSQL dependency and allows PostgreSQL to implement an
application port without a circular import.

## Verification

- Cache misses execute once and insert a JSONB result.
- Cache hits return the persisted view without invoking the operation.
- A different fingerprint returns an idempotency conflict.
- Advisory locks release on both success and conflict paths.
- Raw principal and idempotency-key values are absent from SQL parameters.
- Invalid persisted views become integrity failures.
- Schema setup is transactional.
- The optional real PostgreSQL test persists a command result in one runtime and
  reuses it after opening another runtime.
- The complete suite runs 104 tests: 102 pass and 2 expected tests skip locally.

## Remaining operational work

The local machine still has no configured `MAGI_TEST_POSTGRES_DSN`, so the real
PostgreSQL path is written but not executed here. A retention/cleanup policy for
old command results must be defined before production data volume grows.

## Next increment

Build the production composition root and lifecycle that opens
`PostgresPersistenceRuntime`, constructs model runners and LangGraph, injects the
durable command store, and requires a concrete authentication/authorization
adapter. No insecure default composition should be created.
