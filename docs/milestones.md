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

Status: M2a through M2b-2b implemented and locally verified.

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

## M3: Cross-review

- Produce sanitized ballot summaries.
- Permit one revision.
- Force review for high-risk cases.
- Render a structured final report.

Exit criterion: every majority report preserves dissent and every revision has an audit reason.

## M4: Evidence and audit

- Add read-only retrieval gateway.
- Freeze and hash evidence.
- Validate citations.
- Add append-only audit and redaction.

Exit criterion: a completed report can be reconstructed from stored records.

## M5: Clients and evaluation

- Build TUI first, then Web and CLI automation surfaces.
- Add history and revision views.
- Evaluate citation validity, persona differentiation, arbitration consistency, latency, and cost.

Exit criterion: all three clients display the same DecisionView for the same decision ID.
