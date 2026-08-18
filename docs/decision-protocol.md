# Decision Protocol 1.0

## Preconditions

Do not open the first ballot until all of the following exist:

1. A user-confirmed DecisionCase.
2. At least two explicit options, including defer or no-action when relevant.
3. A frozen EvidenceSnapshot.
4. A declared risk level and data classification.
5. A unique decision ID and version.

## First ballot

Run all three perspective agents concurrently. They must not observe:

- another agent's output,
- another agent's tool results,
- another agent's working memory,
- partial vote totals.

Each agent must select an option or abstain and return a schema-valid Ballot. Confidence is diagnostic metadata, not a vote weight or tie-breaker.

## Constraint claims

An agent may request suspension by submitting a ConstraintClaim with:

- category,
- precise statement,
- severity and likelihood,
- causal chain,
- evidence references when available,
- requested action.

The arbiter validates completeness and whether the claim maps to a declared hard condition. A feeling of risk alone is not a veto. No perspective has an unlimited veto.

## First-round routing

| Result | Next action |
|---|---|
| 3:0 and low or medium risk | Produce consensus |
| 3:0 and high risk | Run cross-review |
| 2:1 | Run cross-review |
| 1:1:1 | Run cross-review |
| Two or more abstentions | Insufficient information |
| Unresolved valid hard constraint | Suspend normal majority processing |
| One unavailable agent after retry | Degraded |
| Two unavailable agents | Failed |

## Cross-review

Provide each agent only sanitized summaries of the other two ballots:

- selected option and stance,
- rationale summary,
- cited evidence,
- risks,
- constraint claims.

Ask each agent to identify the strongest opposing point, the weakest unsupported point, and whether its own ballot should change. Permit one revision only. Do not create open-ended agent conversation or recursive delegation.

## Final arbitration

| Final result | Status |
|---|---|
| All valid ballots select one option | consensus |
| Two valid ballots select one option | majority |
| No option has two valid ballots | unresolved |
| A validated hard constraint remains unresolved | conditional_rejection |
| Required evidence is missing or two agents abstain | insufficient_information |
| One agent is unavailable | degraded |
| The protocol cannot complete | failed |

A majority result must retain the minority report. A conditional rejection must identify the condition that would permit reconsideration.

## Presentation requirements

Every completed report must include:

- decision ID and version,
- final status and selected option,
- ballot count,
- majority rationale,
- minority report when present,
- evidence references,
- assumptions and unresolved questions,
- risks and conditions,
- recommended next step,
- protocol and rule versions.

The presenter must not turn a conditional or unresolved result into a definitive recommendation.

