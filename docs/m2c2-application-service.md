# M2c-2 Application Service and DecisionView

Status: implemented and locally verified  
Package version: 0.2.0b5  
Architecture version: 0.2

## Shared execution boundary

`DecisionApplicationService` is the single use-case boundary intended for the
future FastAPI adapter. Web, terminal TUI, and CLI clients will consume the API
and never import LangGraph, perspective runners, or arbitration code.

The service derives the LangGraph thread ID from the authoritative decision ID
and version. A client cannot submit arbitrary checkpoint configuration.

## Commands

- `wait_for_confirmation` creates the initial checkpoint and pauses before user
  confirmation. Repeating the exact prepared inputs is idempotent; changing the
  case, evidence snapshot, or constraint validations for the same version is a
  conflict.
- `confirm` records a timezone-aware confirmation and stops at
  `EVIDENCE_READY`. It does not invoke a perspective.
- `run` explicitly resumes the second interrupt and starts the three first-ballot
  branches.
- `cancel` is accepted before confirmation or after confirmation but before run.
- `get` reconstructs a client-safe view from a persisted checkpoint.
- `confirm_and_run` is a convenience composition for non-HTTP callers; the two
  state transitions remain separate.

Terminal commands are idempotent only when they agree with the stored outcome.
For example, confirming a completed decision returns the same view, while
cancelling it returns a conflict.

## DecisionView release rules

`DecisionView` includes the validated case, lifecycle state, non-restricted
evidence, available commands, released ballots, and arbitration result.

- No first-round ballot appears until `first_assessment` exists.
- During cross-review, the complete first-round set remains visible but partial
  review ballots remain hidden.
- Review ballots replace first ballots only after the final result exists.
- Restricted evidence is omitted.
- LangGraph checkpoint configuration, tasks, interrupts, and metadata are never
  exposed.

The projector validates that case, snapshot, result, decision ID, and version all
belong to the same workflow before returning a view.

## Restricted model context

The perspective adapter now constructs a model-visible evidence snapshot that
excludes restricted items. Restricted IDs are also excluded from the set of
permitted citations. This closes the gap between the existing arbitration-time
check and the earlier model-prompt boundary.

The external Coordinator and perspective adapters also refuse an entire case
classified as restricted before invoking a model. A future approved local-model
adapter may define a separate policy; there is no silent external fallback.

## Verification

- A fresh application-service instance reads an existing confirmation checkpoint.
- Confirmation reaches `EVIDENCE_READY` with zero perspective calls.
- Another fresh service instance runs the same thread to consensus.
- Cancellation before and after confirmation makes zero perspective calls.
- Duplicate prepared input is idempotent; changed case or snapshot conflicts.
- Partial first ballots and review ballots are not released.
- Restricted evidence is absent from both `DecisionView` and model prompts.
- Invalid checkpoint identity and evidence relationships are rejected.
- The complete suite runs 83 tests: 81 pass and 2 expected tests skip locally.

## Next increment

M2c-3 should add the FastAPI transport adapter, command idempotency headers,
HTTP error mapping, and initial REST tests while returning only `DecisionView`.
Web and TUI can then be built in parallel against the same API contract.
