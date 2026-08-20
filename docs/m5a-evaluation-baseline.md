# M5a Deterministic Evaluation Baseline

M5a introduces a reproducible evaluation layer beside the decision runtime. It
does not participate in voting, change an arbitration result, or call another
model. Its input is a sealed `EvaluationBundle`; its output is an immutable
`DecisionEvaluation`.

## Metrics

| Metric | Observation | Gate |
| --- | --- | --- |
| Citation validity | Ballot and constraint references that resolve in the frozen snapshot | Valid-reference ratio meets the configured minimum |
| Persona differentiation | Jaccard distance over normalized rationale, assumptions, risks, unknowns, and constraint statements | Every agent pair meets the configured minimum distance |
| Arbitration consistency | A fresh deterministic arbitration compared field-by-field with the stored result | No authoritative field differs |
| Latency | Nearest-rank p95 and mean across provider attempts; cache reuse is excluded | p95 is at or below the configured maximum |
| Cost | Input/output tokens multiplied by an explicit model price snapshot | Total is at or below the optional configured maximum |

`not_measured` is distinct from `pass`. Missing invocation samples, missing
pricing, or decisions without citations therefore produce an overall `warn`
instead of silently satisfying the gate. Any failed measured metric makes the
overall status `fail`.

## Integrity boundaries

- Case, snapshot, ballots, result, and invocation records must have one decision
  ID and version.
- The deterministic arbiter is the only source of the consistency comparison.
- Invocation cache-reuse records add neither provider latency nor token cost.
- Cost uses integer micro-USD and ceiling rounding; no floating point currency
  arithmetic is used.
- A missing model price makes the cost metric `not_measured`; partial cost is not
  presented as complete.
- The price values are supplied by the caller and should carry their own review
  and update process. MAGI does not embed current vendor pricing.

## Automation contract

~~~powershell
magi-eval tests/evals/v1/consensus-baseline.json --fail-on-threshold
~~~

The command reads at most 5 MB and writes one sorted UTF-8 JSON document. Exit
codes are `0` for an accepted evaluation, `1` for a threshold failure when the
flag is enabled, and `2` for invalid input. The fixture under
`tests/evals/v1/` covers all five metrics and is evaluated twice in tests to
prove deterministic output.

## Deferred from M5a and completed by M5d

- Aggregate evaluation history and trend storage.
- Representative cases for abstention, revision, degraded runs, and fail-closed
  citation failure.
- EVA/MAGI Web and terminal metric dashboards.
- Explicit synthetic acceptance labels and calibration against expected outcomes.

History was delivered in M5b, dashboards in M5c, and the representative
calibration plus opt-in live acceptance gate in M5d.
Calibration against real human decisions remains a deployment/research activity
and is not represented as completed by the synthetic local suite.
