# M3c: Client parity and M3 acceptance

Package version: 0.3.0

## Parallel report surfaces

The terminal and Web styles coexist as independent consumers of the same
authenticated `DecisionReport` resource.

The `magi-report` command validates the server response against the application
schema before rendering it. It offers optional application-owned ANSI styling,
automatically emits plain text when redirected, supports unchanged JSON output,
and returns result-specific exit codes. Bearer credentials come from
`MAGI_API_TOKEN` or a hidden interactive prompt and are never accepted as a command
argument.

The Web report viewer is a dependency-free M3 reference surface. Its loopback
server serves static assets and proxies only final-report reads to MAGI. This keeps
browser requests same-origin without enabling broad CORS. The page retains its
token only in memory and constructs every report element with `textContent`.

These are report surfaces, not the full workflow clients planned for M5.

## Shared contract acceptance

`tests/fixtures/v1/decision-report-majority.json` is validated by Pydantic, rendered
by the terminal test, and consumed by the Node.js Web contract test. Both surfaces
must preserve:

- decision ID and version;
- majority status and selected option;
- all vote counts;
- majority rationale;
- Balthasar's minority report;
- all three review-audit entries.

## M3 acceptance matrix

| Requirement | Evidence | Result |
|---|---|---|
| Sanitized peer summaries | Runner and workflow isolation tests | Pass |
| At most one review | Round schema and LangGraph review path tests | Pass |
| High-risk review | Arbitration high-risk routing test | Pass |
| Review audit reason | Ballot validation and model-runner tests | Pass |
| Structured final report | Projector and DecisionView tests | Pass |
| Majority preserves dissent | Majority report fixture and projector tests | Pass |
| Authenticated report transport | FastAPI JSON/Markdown tests | Pass |
| Terminal/Web parity | Shared fixture cross-client acceptance test | Pass |
| Live PostgreSQL/OpenAI smoke | Explicit environment-gated M2 acceptance | Pending environment |

The local M3 exit criterion is complete. The existing deployment smoke remains
environment-gated and does not weaken deterministic acceptance.
