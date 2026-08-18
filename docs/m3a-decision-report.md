# M3a: Deterministic decision report

Package version: 0.3.0a1

## Delivered boundary

M3a turns the existing bounded cross-review records into a client-safe final
report. It does not introduce another agent, voting round, or language-polishing
model.

Every round-two `Ballot` now requires both its first-round ballot reference and a
concise `review_reason`. The reason is required whether the perspective retains
or changes its selection, so the audit trail explains all three final ballots.
First-round ballots reject review metadata.

`DecisionReportProjector` derives an immutable `DecisionReport` from:

- the confirmed `DecisionCase`;
- the deterministic `ArbitrationResult`;
- the sealed first and final ballots.

The report contains the final status and option, vote count, winning rationales,
minority report, evidence references, assumptions, unresolved questions, risks,
conditions, a status-safe next step, ballot references, and per-agent review audit
links. Aggregation uses agent-name order and stable de-duplication, so rebuilding
from the same records produces the same report. `generated_at` is inherited from
the arbitration result rather than from projection time.

## Information boundary

The report appears only when a checkpoint already contains an arbitration result.
During cross-review, clients continue to see the released first-round ballots and
`report` remains null. Once arbitration completes, `DecisionView` switches to the
final ballots and publishes the report atomically.

For decisive results, the selected option must exist in the confirmed case. For
unresolved, conditional, insufficient, degraded, and failed results, the report
validator forbids a selected option. A majority report cannot validate without the
arbiter's minority report.

## Deferred to the next increment

- dedicated `GET /v1/decisions/{id}/report` transport;
- terminal and Web renderers over the shared report schema;
- export formats and report history comparison.
