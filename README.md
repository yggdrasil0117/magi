# MAGI

MAGI is a decision-support system inspired by Evangelion's three-perspective computer. It runs three isolated agents, preserves dissent, and applies deterministic arbitration rules. The first release is advisory only: it analyzes and records decisions but cannot modify external systems.

M1 includes the framework-independent decision domain, lifecycle state machine, first-round router, deterministic arbiter, and versioned protocol fixtures.

M2a adds a LangGraph Graph API builder, JSON-serializable checkpoint state, confirmation interrupt, parallel first and review branches, scripted perspective runner, and sanitized public-event projection. The executable LangGraph interrupt/resume integration path is verified with LangGraph 1.2.11.

M2b-1 adds a LangChain/OpenAI structured-output runner. Each LangGraph perspective node loads the shared MAGI protocol and exactly one perspective skill, receives an isolated prompt, and returns a ballot draft. Application code seals authoritative identity, round, decision, option, and evidence boundaries.

M2b-2a adds deterministic model-call idempotency, process-local duplicate suppression, classified retry, `Retry-After` handling, token/latency records, and a replaceable invocation-ledger boundary. Logs contain prompt digests and error types rather than raw prompts or provider error text.

M2b-2b adds a shared PostgreSQL runtime for durable invocation records, canonical ballots, cross-process duplicate suppression, and LangGraph checkpoints. An interrupted decision can resume from the same thread after an application restart.

M2c-1 adds the non-voting Coordinator normalization boundary. It converts an untrusted raw question into a protocol-1.0 `DecisionCase` draft while application code seals identity, version, raw input, classification, risk floor, and claim verification status. The case remains unconfirmed until the user approves it.

M2c-2 adds the shared application service and sanitized `DecisionView`. Confirmation and voting are separate commands, checkpoint state can be read through a new service instance, partial ballots stay hidden, and restricted evidence is excluded from both clients and model prompts.

M2c-3 adds the authenticated FastAPI transport for reading, confirming, running, and cancelling prepared decisions. Mutating commands require principal-scoped idempotency keys and all routes return `DecisionView` or a stable sanitized error envelope.

M2c-4a adds durable PostgreSQL API-command idempotency. Principal and client keys are stored only as SHA-256 digests, duplicate commands are serialized across processes with advisory locks, and the persisted response is schema-validated before reuse.

M2c-4b adds the fail-closed production FastAPI factory. Its lifespan owns the shared PostgreSQL runtime, loads the three perspective skills, builds the OpenAI runners and LangGraph, injects durable command idempotency, and requires an explicit hashed bearer authorization policy.

M2c-5 adds authenticated, idempotent decision creation. The non-voting Coordinator normalizes the raw question, application code seals retry-stable identity and user-asserted evidence, and the new workflow pauses at the existing confirmation gate before any perspective model runs.

M2c-6 closes M2 at version 0.2.0 with a bounded PostgreSQL-aware readiness probe, an explicitly enabled real-service acceptance flow, and a frozen acceptance matrix. Local implementation acceptance passes; deployment smoke remains environment-gated.

## Local setup (Windows PowerShell)

~~~powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]" -i https://mirrors.aliyun.com/pypi/simple/
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
~~~

## Confirmed M0 scope

- Melchior evaluates evidence, logic, feasibility, and uncertainty.
- Balthasar evaluates human impact, safety, privacy, and reversibility.
- Casper evaluates strategy, alternatives, and long-term effects.
- The first ballot is secret and parallel.
- A bounded cross-review may change each ballot once.
- Python code, not a fourth judging model, produces the result.
- Web, terminal TUI, and CLI clients share one API and one DecisionView.
- All tools are read-only in the first release.

## Repository map

~~~text
apps/          API, Web, TUI, and CLI client boundaries
src/magi/      Decision domain and service modules
skills/        Shared protocol and three perspective skills
docs/          Frozen M0 architecture and contracts
tests/         Unit, integration, evaluation, and fixture areas
~~~

Start with docs/architecture.md, docs/m1-implementation.md, and docs/m2a-implementation.md.
The current model-adapter increments are documented in docs/m2b1-implementation.md,
docs/m2b2a-invocation-control.md, and docs/m2b2b-postgres-persistence.md.
Coordinator normalization is documented in docs/m2c1-coordinator-normalization.md.
The shared application boundary is documented in docs/m2c2-application-service.md.
The initial HTTP transport is documented in docs/m2c3-fastapi-transport.md.
Durable API command idempotency is documented in docs/m2c4a-postgres-command-idempotency.md.
Production composition is documented in docs/m2c4b-production-composition.md.
Coordinator-backed creation is documented in docs/m2c5-decision-preparation.md.
M2 acceptance closure is documented in docs/m2c6-acceptance-closure.md.
