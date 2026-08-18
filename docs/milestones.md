# Delivery Milestones

## M0: Architecture freeze

- Accepted architecture and decision protocol.
- Logical data, API, event, and threat contracts.
- Project and skill skeleton.
- No model or business runtime.

## M1: Deterministic decision kernel

Status: implemented.

- Implemented immutable domain models and legal state transitions.
- Implemented first-round routing and arbitration without model access.
- Added versioned case, snapshot, and ballot fixtures.
- Covered 3:0, 2:1, 1:1:1, abstention, validated constraints, missing agents, duplicate ballots, evidence integrity, and state-transition boundaries.

Exit criterion: all arbitration outcomes are reproducible from fixtures.

## M2: Three perspectives

Status: implemented and locally accepted at version 0.2.0. Live deployment
smoke remains explicitly environment-gated.

- Add LangGraph Graph API orchestration and PostgreSQL checkpointing.
- Implement Coordinator.
- Run three isolated agents concurrently.
- Load shared and perspective skills.
- Validate structured ballots.

Exit criterion: first-round secrecy and one accepted ballot per perspective are covered by integration tests.

M2a provides the tested graph and scripted runner. M2b-1 adds three isolated
LangChain/OpenAI structured-output boundaries and loads the shared plus assigned
perspective skills. Controlled live API evaluation remains.
M2b-2a adds idempotent model calls, bounded transient retries, sanitized attempt
records, token usage, and latency through a persistence-neutral ledger port.
M2b-2b adds the PostgreSQL invocation ledger, cross-process advisory locking,
canonical ballot storage, and `AsyncPostgresSaver` checkpointing. The real
database restart test is available and runs when `MAGI_TEST_POSTGRES_DSN` is set;
the current workstation has no local PostgreSQL service, so that test is skipped.
M2c-1 adds the non-voting Coordinator model boundary and seals every field that
must remain under application authority. It deliberately does not add a fourth
persona or expose the perspective agents before user confirmation.
M2c-2 adds the shared application service, an explicit run gate after user
confirmation, restart-safe checkpoint reads, and a sanitized `DecisionView` for
all future clients.
M2c-3 exposes the completed application commands through an authenticated
FastAPI adapter with per-decision authorization, principal-scoped idempotency,
stable error responses, and transport-to-LangGraph integration coverage.
M2c-4a adds durable cross-process API-command idempotency to the shared
PostgreSQL runtime. Raw principals and idempotency keys are never stored.
M2c-4b adds the fail-closed production ASGI factory, lifecycle ownership of the
shared runtime, startup skill validation, and a concrete hashed bearer policy
with explicit action and decision allowlists.
M2c-5 adds authenticated idempotent decision creation, production Coordinator
composition, application-owned evidence sealing, and a confirmation pause
before any perspective model call.
M2c-6 adds bounded database-aware readiness, an opt-in real PostgreSQL/OpenAI
end-to-end acceptance test, and the frozen M2 acceptance matrix. The local M2
implementation exit criterion passes; the current workstation has no database,
Docker, or OpenAI configuration, so deployment smoke is recorded as pending
rather than passed.

## M3: Cross-review

Status: implemented and locally accepted at version 0.3.0.

- Produce sanitized ballot summaries.
- Permit one revision.
- Force review for high-risk cases.
- Render a structured final report.

Exit criterion: every majority report preserves dissent and every revision has an audit reason.

M3a makes a review reason mandatory on every second-round ballot and adds a
deterministic structured report to terminal `DecisionView` responses. Majority
reports preserve the arbiter's minority record verbatim; incomplete review state
does not expose a report. Dedicated report transport and client rendering remain.

M3b adds authorized JSON report retrieval and safe Markdown download. Both formats
come from the same `DecisionReport`; incomplete decisions return a stable conflict
instead of a partial document. Terminal and Web rendering remain for M3c.

M3c adds terminal and Web report surfaces over the same report API. A shared
versioned majority fixture proves that both preserve the selected option, vote
count, dissent, and review audit. The terminal removes external control characters;
the browser uses text-only DOM construction and a loopback same-origin proxy.

The M3 exit criterion is satisfied: majority reports require and retain dissent,
and every second-round ballot requires an audit reason whether retained or revised.

## UI/UX delivery track

Status: UI-D1 through UI-D4b-2a accepted; UI-D4b-2c worker implemented.

- UI-D1: define user journeys, information architecture, and every workflow state.
- UI-D2: confirm low-fidelity Web and terminal wireframes before visual styling.
- UI-D3: define shared semantic tokens, components, accessibility, and responsive rules.
- UI-D4: build production TUI and Web flows against the same API contracts.
- UI-D5: run usability, keyboard, accessibility, and cross-client parity acceptance.

Each design gate requires review before the next layer is treated as frozen. Web
and terminal share information priority and state meaning, but each keeps its own
interaction model; pixel-level imitation between them is not a goal.

Exit criterion: the primary decision journey is usable without hidden state,
status is never communicated by color alone, every action is keyboard reachable,
and Web/TUI render the same authoritative decision semantics.

## M4: Evidence and audit

- Add read-only retrieval gateway.
- Freeze and hash evidence.
- Validate citations.
- Add append-only audit and redaction.
- Design evidence provenance, citation failure, redaction, and audit-history UI states
  in parallel through UI-D1 to UI-D3.

Exit criterion: a completed report can be reconstructed from stored records.

## M5: Clients and evaluation

- Implement the confirmed UI system in TUI first, then Web and CLI automation surfaces.
- Add history and revision views.
- Cover loading, empty, waiting, denied, partial, degraded, insufficient, failed,
  cancelled, and completed states explicitly.
- Verify responsive layout, keyboard navigation, focus order, reduced motion,
  contrast, screen-reader labels, and Chinese/English text expansion.
- Evaluate citation validity, persona differentiation, arbitration consistency, latency, and cost.

Exit criterion: all three clients display the same DecisionView for the same
decision ID, and Web/TUI pass the UI-D5 accessibility and usability gates.
