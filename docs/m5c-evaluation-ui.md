# M5c Evaluation UI and Client Parity

M5c exposes M5b's server-authoritative evaluation history in both interactive
clients. It does not introduce a second evaluator or a client-side scoring path.

## Shared semantics

Web and TUI display citation validity, persona differentiation, deterministic
arbitration consistency, P95 model latency, and explicitly priced token cost.
Each metric preserves the API status (`pass`, `warn`, `fail`, or
`not_measured`). The latest overall status, returned-window counts, total record
count, and append-only sequence are displayed without inferring missing history.

## Web surface

The decision workspace loads evaluation history alongside the separately
authorized audit chain. Five responsive cards include text status labels, values,
and native progress elements where the API supplies a score. The history window
uses sequence, status, timestamp, and digest prefix. Access denial degrades only
the evaluation panel.

For terminal decisions, the keyboard-reachable run button posts exactly
`{"version": <current version>}` and then reloads history. No ballot, metric,
threshold, price, or total is accepted from the browser. The loopback proxy keeps
the exact M5b path allowlist and no-store policy.

## Terminal surface

`evaluations DECISION [VERSION] [LIMIT]` reads a bounded history window.
`evaluate DECISION [VERSION]` requests a server-side run. Both use a stable,
control-character-sanitized five-line metric display and explicit
`NOT MEASURED` text. The dependency-free TUI continues to use only public HTTP
contracts and does not import evaluation or decision-engine code.

## Acceptance

- Web contract validation rejects identity, digest, ordering, and trend drift.
- Every metric status is written as text; color is supplementary.
- Web controls retain visible keyboard focus and responsive/reduced-motion rules.
- TUI contract tests prove the exact GET/POST resources and version-only run body.
- Both clients render missing latency or pricing as not measured, never zero.

At M5c, M5 remained open for broader representative suites and release closure;
M5d subsequently completed that calibration and local acceptance gate.
