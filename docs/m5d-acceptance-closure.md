# M5d Acceptance Closure

M5d closes the local M5 implementation at version `0.5.0`. It adds calibration
and end-to-end acceptance evidence without moving evaluation authority into a
client or adding model-based judging.

## Representative quality matrix

`tests/evals/v1/representative-outcomes.json` freezes explicit acceptance labels
for six synthetic cases:

| Case | Decision outcome | Expected quality |
| --- | --- | --- |
| consensus baseline | consensus | pass |
| cross-review revision | majority | pass |
| insufficient information | insufficient information | pass |
| missing perspective | degraded | warn; persona not measured |
| performance regression | consensus | fail latency and cost |
| invalid citation | rejected before evaluation | protocol violation |

The suite checks every metric status and repeats each successful evaluation to
prove deterministic output. “Pass” means the quality contract was measured and
met; it does not mean MAGI endorses the underlying real-world choice. A degraded
decision is advisory even when its measured metrics pass, because three-persona
differentiation cannot be measured with one perspective missing.

These are engineering fixtures, not empirical human-preference data. Calibration
against real human decisions remains a deployment/research activity and is not
claimed as a local automated pass.

## Frozen client parity

`tests/fixtures/v1/evaluation-history.json` is a valid server model including the
evaluation digest, deterministic record ID, five metrics, price digest, and trend.
Python validates the complete envelope. TUI renders it as a five-line terminal
panel, and Web consumes the same file through its contract tests. This prevents
the two interactive clients from drifting toward separate evaluation semantics.

## Exit matrix

| M5 requirement | Acceptance evidence | Result |
| --- | --- | --- |
| Web, TUI, and CLI use public projections | client parity and workflow client tests | pass |
| history and revision are visible | UI-D4c plus evaluation-history tests | pass |
| all decision and failure states are explicit | UI-D5 and workspace state tests | pass |
| status is not color-only and actions are keyboard reachable | Web UI acceptance tests | pass |
| responsive and reduced-motion behavior exists | Web CSS acceptance tests | pass |
| all five quality metrics are deterministic | representative evaluation suite | pass |
| evaluation records are append-only and deduplicated | store and API integration tests | pass |
| real model/database path is testable | opt-in M5 live test | environment-gated |

The implementation exit criterion is satisfied locally. As in M2 and M4,
absence of real credentials is recorded as a skipped deployment smoke test, not
as a fabricated pass.

## Optional live acceptance

The live flow creates, confirms, and runs a synthetic decision using real
PostgreSQL and OpenAI services. It then runs evaluation twice, proves exact-result
deduplication, reads the five-metric history, and verifies it after an application
restart. It is disabled by default because it can incur provider cost.

Required variables:

~~~text
MAGI_RUN_M5_LIVE=1
MAGI_TEST_POSTGRES_DSN=...
OPENAI_API_KEY=...
MAGI_OPENAI_MODEL=...
MAGI_MODEL_INPUT_MICROUSD_PER_MILLION_TOKENS=...
MAGI_MODEL_OUTPUT_MICROUSD_PER_MILLION_TOKENS=...
~~~

Run only the live gate with:

~~~powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m unittest tests.live.test_m5_acceptance -v
~~~
