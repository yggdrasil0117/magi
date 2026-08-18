# M2c-6 Acceptance Closure

Status: implementation accepted; live deployment smoke pending environment
Package version: 0.2.0
Architecture version: 0.2
API contract version: 1.0

## Outcome

M2 is code-complete and satisfies its frozen exit criterion: the three
perspectives run in isolated first-round branches, no partial ballot is
released, and deterministic arbitration accepts at most one ballot per
perspective and round.

M2c-6 adds the operational evidence needed to close the implementation:

- `/healthz` remains a dependency-free liveness endpoint;
- `/readyz` requires a bound application service and PostgreSQL connectivity;
- the PostgreSQL query is bounded to two seconds and fails closed;
- readiness errors return only `ready` or `not_ready`;
- an opt-in acceptance test drives create, confirm, run, read, shutdown, restart,
  and restored read through the production FastAPI composition;
- real OpenAI calls require `MAGI_RUN_M2_LIVE=1` and are never enabled by
  ordinary test discovery.

## Acceptance matrix

| Area | Evidence | Local result |
|---|---|---|
| Domain and arbitration | Versioned fixtures and deterministic unit tests | Pass |
| First-round secrecy | LangGraph parallel-branch integration tests | Pass |
| One ballot per perspective | Workflow and arbitration invariants | Pass |
| Coordinator authority | Sealing and restricted-input tests | Pass |
| Confirmation and run gates | Application and API stack tests | Pass |
| Restart-safe command behavior | Checkpoint/idempotency protocol tests | Pass |
| Production lifecycle | FastAPI lifespan composition tests | Pass |
| Readiness behavior | API, production, and PostgreSQL probe tests | Pass |
| Real PostgreSQL restart | `MAGI_TEST_POSTGRES_DSN` integration test | Pending environment |
| Real OpenAI end-to-end | Explicit live acceptance test | Pending environment |

Local automated result: 120 tests discovered, 117 passed, and 3 intentionally
skipped. The skips are the missing real PostgreSQL DSN, the unavailable-runtime
negative test because LangGraph is installed, and the opt-in live M2 test.

## Readiness contract

`PostgresPersistenceRuntime.is_ready()` returns false when the runtime is not
open, the timeout is invalid, pool checkout fails, or `SELECT 1` fails. It does
not propagate database exception details through HTTP.

The generic transport factory has no assumed production dependencies and
therefore reports not-ready unless a probe is injected. The production factory
injects a probe bound to its own service and shared PostgreSQL runtime.

## Running live acceptance

Use a dedicated non-production PostgreSQL database. Configure the model and
explicitly enable paid calls:

~~~powershell
$env:MAGI_TEST_POSTGRES_DSN = "postgresql://.../magi_test"
$env:OPENAI_API_KEY = "..."
$env:MAGI_OPENAI_MODEL = "your-evaluated-model"
$env:MAGI_RUN_M2_LIVE = "1"
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m unittest tests.live.test_m2_acceptance -v
~~~

The live test creates a unique static authorization policy in a temporary
directory, invokes the production factory, completes one synthetic decision,
restarts the application, and verifies that the final `DecisionView` is restored
from PostgreSQL. It can make four to seven model calls depending on whether the
first-round result requires cross-review.

## Current environment record

At local acceptance time this workstation had no `.env`, PostgreSQL DSN,
OpenAI key/model variables, or Docker runtime. No live service or paid model
call was attempted. The two live rows above remain pending and must not be
reported as passed until the explicit command succeeds.

## Next milestone

M3 begins with final-report projection and cross-review audit semantics. The
existing graph already supports one bounded cross-review; M3 will turn that
state into a complete, reconstructable report while preserving dissent.
