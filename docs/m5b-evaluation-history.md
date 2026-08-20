# M5b Evaluation History and Trends

M5b turns the M5a offline evaluator into a server-authoritative production
resource. A client identifies only a decision ID and version. The server obtains
the terminal state from the verified audit chain, obtains latency and token usage
from the invocation ledger, runs the deterministic evaluator, and appends the
result to evaluation history.

## Data flow

~~~text
verified audit chain ──> terminal case/snapshot/ballots/result ─┐
                                                               ├─> evaluator ─> append-only history
invocation ledger ─────> attempts/latency/token usage ─────────┘
explicit server price snapshot ────────────────────────────────┘
~~~

The HTTP request cannot provide ballots, vote totals, citations, invocation
usage, metric scores, or cost. This prevents a client from manufacturing a
favorable quality report.

## Storage contract

`EvaluationRecord` contains a decision-scoped sequence, stable evaluation UUID,
SHA-256 digest, immutable `DecisionEvaluation`, and server timestamp. The UUID is
derived from decision identity and the full evaluation digest. Running the same
evaluation again returns the original record; a changed threshold, price,
invocation set, or authoritative decision state produces a new sequence.
The cost metric retains a SHA-256 digest of the complete explicit pricing input,
so even two price snapshots that round to the same micro-USD total remain
distinguishable.

PostgreSQL serializes sequence assignment with a transaction-scoped advisory
lock. A database trigger rejects `UPDATE` and `DELETE`. Stored JSON is validated
against the current schema before it crosses the adapter boundary.

## API and authorization

~~~text
GET  /v1/decisions/{id}/evaluations?version=1&limit=20
POST /v1/decisions/{id}/evaluations
Body: {"version": 1}
~~~

GET requires `evaluation:read`; POST requires `evaluation:run`. Both responses
use private no-store headers. A missing evaluation service returns a sanitized
503. A missing audit trail returns 404, and a non-terminal decision returns the
existing stable 409 report-not-ready error.

The history result is chronological. `total_count` covers the complete decision
version while `trend.sample_count` covers only the returned bounded window. The
trend includes status counts and means for measured citation score, persona
score, p95 latency, and cost. Missing metric values are excluded rather than
treated as zero.

## Production price configuration

Cost remains provider-neutral. Production may configure both variables:

~~~text
MAGI_MODEL_INPUT_MICROUSD_PER_MILLION_TOKENS
MAGI_MODEL_OUTPUT_MICROUSD_PER_MILLION_TOKENS
~~~

Both must be present together and nonnegative. If omitted, evaluation still runs
but cost is `not_measured`. Existing history is never recalculated after a price
change.

## Client contract

~~~text
magi evaluations DECISION_ID --version 1 --limit 20
magi evaluate DECISION_ID --version 1
~~~

The loopback Web proxy allowlists this exact resource, `version`, and bounded
`limit`; UI rendering is deferred to M5c so the browser depends on the frozen
server response instead of an interim client metric implementation.
