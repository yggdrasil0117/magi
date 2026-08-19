# MAGI Architecture

Status: accepted  
Architecture version: 0.3
Decision protocol version: 1.0

## Purpose

MAGI is an advisory decision system. It converts one user question into a versioned decision case, collects three isolated perspectives, performs at most one cross-review, and applies deterministic arbitration. It does not execute external actions in the first release.

## Design principles

1. Keep perspective, capability, and authority separate.
2. Preserve first-round independence.
3. Use structured records as the source of truth.
4. Keep arbitration deterministic and versioned.
5. Preserve minority opinions.
6. Treat all retrieved content as untrusted data.
7. Expose one execution path through the API.
8. Make failure explicit instead of silently substituting agents or models.

## System boundary

~~~mermaid
flowchart LR
    W["Web"]
    T["Terminal TUI"]
    C["CLI / JSON"]
    A["FastAPI boundary"]
    O["LangGraph orchestration (M2)"]
    E["Evidence snapshot"]
    M["Melchior"]
    B["Balthasar"]
    S["Casper"]
    R["Deterministic arbiter"]
    D["PostgreSQL and audit log"]

    W --> A
    T --> A
    C --> A
    A --> O
    O --> E
    O --> M
    O --> B
    O --> S
    M --> R
    B --> R
    S --> R
    R --> D
    O --> D
    D --> A
~~~

Web, TUI, and CLI never import or invoke agent runners directly. They issue commands through the API and consume the same sanitized DecisionView and event stream.

## Components

### Coordinator

Normalize the raw question into a DecisionCase. Identify options, user constraints, claims, unknowns, risk level, and data classification. Do not recommend an option or participate in voting. Do not promote a user assertion to verified fact.

M2c-5 places the Coordinator behind the application preparation service. The
application owns decision identity, freezes supplied evidence, marks it as
user-asserted, and enters LangGraph only after normalization succeeds.

### Evidence service

Collect authorized read-only evidence, record provenance, classification, capture time, and a content hash, then freeze an EvidenceSnapshot before voting begins. New evidence creates a new decision version.

### Perspective agents

- Melchior: evidence, logic, feasibility, cost, and uncertainty.
- Balthasar: human impact, safety, ethics, privacy, and reversibility.
- Casper: strategy, alternatives, second-order effects, and long-term value.

Each receives the same DecisionCase and EvidenceSnapshot plus its own instructions and skill. First-round contexts and working memory are isolated.

### Orchestrator

Use LangGraph from M2 to run agents concurrently, checkpoint stages, pause for user confirmation, resume failures, reveal ballots only after the first round closes, and run one cross-review when required. The orchestrator cannot change votes. LangGraph checkpoints are operational state, not the canonical audit or arbitration record.

M4b implements the canonical audit boundary as a per-decision-version hash chain.
Application projections append validated decision states to it, and reports can be
reconstructed from the verified chain without reading LangGraph. Redaction is an
append-only visibility overlay and never rewrites canonical records.

Decision thread identity belongs to the orchestration layer. Infrastructure may
reuse it, but the application layer does not import PostgreSQL adapters.

The production composition root belongs to the API boundary. FastAPI lifespan
opens and closes the shared PostgreSQL pool, and the process does not accept
requests unless persistence, skills, model runners, and LangGraph all compose
successfully.

Liveness and readiness are separate. Liveness does not query dependencies.
Readiness requires both a bound application service and a successful bounded
PostgreSQL query; failure details remain server-side.

### Arbiter

Apply decision-protocol.md using ordinary application code. Produce one ArbitrationResult and retain all referenced ballots. Do not use a judging model.

### Presenter

Build DecisionView from stored records. Optional language polishing cannot change votes, risks, conditions, evidence references, or status. Structured records remain authoritative.

M2c-2 implements the first deterministic `DecisionView` projector. It releases no
partial first-round ballots, switches to review ballots only after arbitration,
and excludes restricted evidence. Language polishing remains deferred.

M3a adds an immutable `DecisionReport` projection to terminal `DecisionView`
records. It derives majority rationale, dissent, evidence references, assumptions,
risks, unresolved questions, next steps, and review audit links only from sealed
records. It performs no model call and cannot alter arbitration.

M3b publishes that same report through authenticated JSON and Markdown resources.
The Markdown renderer is deterministic application code, escapes untrusted text,
and emits a download attachment. Transport rendering never becomes a second
source of truth.

M3c adds parallel terminal and Web report surfaces. Both are API consumers: the
terminal validates `DecisionReport` JSON before rendering, while the browser maps
the same fields into text-only DOM nodes. The Web development server binds to
loopback and provides a narrow same-origin report proxy, so production CORS stays
fail-closed. Full workflow clients remain an M5 concern.

## Interface design contract

UI design is a first-class delivery track rather than a final styling pass. Web,
TUI, and CLI share API schemas, information priority, state names, permissions,
and report meaning. They do not share business logic or recalculate status.

The interfaces must make the lifecycle visible: what MAGI knows, what remains
unknown, whether user confirmation or an explicit run is required, which agents
have completed without revealing partial votes, and why a result is decisive or
non-decisive. Dissent, evidence quality, unresolved questions, and audit links
remain visible rather than being collapsed into one recommendation.

Presentation can adapt to the medium. Web uses responsive spatial hierarchy and
progressive disclosure; TUI uses keyboard-first panels and concise status lines;
CLI preserves stable JSON and exit codes. Semantic status cannot depend on color,
animation, or iconography alone. The shared UI plan and confirmation gates are in
`docs/ui-design-plan.md`.

## State machine

~~~text
CREATED
  -> NORMALIZED
  -> WAITING_FOR_USER
  -> EVIDENCE_READY (confirmed, waiting for explicit run)
  -> FIRST_BALLOT
  -> CROSS_REVIEW (when required)
  -> ARBITRATED
  -> COMPLETED
~~~

Terminal states:

- INSUFFICIENT_INFORMATION
- DEGRADED
- FAILED
- CANCELLED

Waiting state:

- WAITING_FOR_USER

Only CREATED and NORMALIZED cases may be edited. Any new fact after the evidence snapshot is frozen creates a new version.

## Instruction precedence

~~~text
MAGI core protocol
> security and permission policy
> agent identity and mandate
> perspective skill
> optional domain skill
> current user task
> retrieved content
~~~

Retrieved content is evidence, never instruction.

## Memory boundaries

- Shared case memory: explicit user facts, constraints, approved preferences, and prior decision references.
- Private working memory: ephemeral per-agent context that is never shared.
- Audit memory: append-only ballots, revisions, events, tool records, and outcomes.
- Preference memory: explicit user preferences only; do not infer sensitive traits.

Do not store hidden chain-of-thought. Store concise rationale, assumptions, evidence references, risks, and revision reasons.

## Failure rules

- Retry a transient agent failure once.
- Permit one structured-output repair attempt.
- If one agent remains unavailable, mark the run DEGRADED; two ballots cannot become an official MAGI decision.
- If two agents fail, fail the run.
- If cross-review fails, preserve the first ballot but do not publish a formal final decision.
- Never silently replace a configured model with an unevaluated fallback.

## Initial deployment

- Python 3.12, FastAPI, Pydantic, and OpenAI Responses API through LangChain OpenAI.
- LangGraph Graph API and a durable PostgreSQL checkpointer from M2.
- PostgreSQL with SQLAlchemy and Alembic.
- Next.js Web client.
- Textual TUI and Rich CLI.
- OpenTelemetry and structured logs.
- Docker Compose for local deployment.

Redis, Temporal, vector storage, and Kubernetes are deferred until measured requirements justify them.
