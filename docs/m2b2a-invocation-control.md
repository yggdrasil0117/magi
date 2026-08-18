# M2b-2a Model Invocation Control

Status: implemented and locally verified without live API calls  
Package version: 0.2.0b2  
Architecture version: 0.2

## Scope

This increment controls model calls before the invocation ledger is implemented
in PostgreSQL. It adds deterministic idempotency, bounded retry, usage capture,
and sanitized append-only attempt records.

## Idempotency

The runner computes two SHA-256 values:

- `prompt_digest` hashes the isolated system and user messages;
- `idempotency_key` hashes the protocol version, configured model name, assigned
  agent, and prompt digest.

The ledger stores the canonical sealed `Ballot`, not only the model draft. A
repeat call therefore returns the same ballot ID, timestamp, and content. A
per-key asynchronous lock prevents duplicate provider calls within one runner
process.

In M2b-2a the lock was intentionally process-local. M2b-2b replaces this behavior
when the PostgreSQL ledger is selected: a session advisory lock serializes each
idempotency key across application processes, while the canonical-ballot table
enforces uniqueness.

## Retry classification

The runner retries at most once by default and only for transient categories:

- API connection failure;
- API timeout;
- internal server error;
- rate limit;
- unprocessable entity;
- built-in connection and timeout errors.

Authentication, permission, bad-request, structured-output, and MAGI protocol
errors are not retried. `Retry-After` takes precedence over exponential backoff
and is bounded by the configured maximum delay. The provider SDK's internal
retry is disabled so MAGI records every attempt itself.

This classification follows the official OpenAI error guidance:
https://developers.openai.com/api/docs/guides/error-codes

## Invocation record

Each attempt or reuse creates an immutable `ModelInvocationRecord` containing:

- decision ID and version;
- agent and round;
- model name;
- idempotency key and prompt digest;
- attempt number and status;
- UTC start and completion times;
- latency in milliseconds;
- input, output, and total token counts;
- exception type for failures.

Records do not contain raw prompts, raw provider responses, API keys, provider
error messages, or hidden reasoning.

## Verification

- Sequential duplicate calls reuse the exact canonical ballot.
- Concurrent duplicate calls trigger one provider invocation in the process.
- Token usage is extracted from the structured-output raw response envelope.
- A timeout produces one failed and one successful attempt record.
- Authentication and bad-request errors are not retried.
- `Retry-After` overrides calculated backoff.
- Existing LangGraph interrupt, review, and arbitration paths remain green.
- The complete suite runs 55 tests: 54 pass and the missing-LangGraph negative
  test is skipped because LangGraph is installed.

## Subsequent M2b work

- Run the optional restart integration test against a real PostgreSQL instance.
- Perform controlled live-model evaluation after explicit model selection.
- Add pricing snapshots and cost calculation after token telemetry is validated
  against live responses.
