# Threat Model 0.1

## Assets

- User questions, files, preferences, and decision history.
- Evidence snapshots and provenance.
- Agent and skill instructions.
- Model and tool credentials.
- Ballots, arbitration results, and audit integrity.
- Cross-user isolation.

## Trust boundaries

Untrusted:

- user input,
- uploaded files,
- webpages and retrieval results,
- quoted instructions inside evidence,
- client-provided status or vote data.

Trusted only after validation:

- normalized DecisionCase,
- tool gateway output,
- schema-valid Ballot,
- verified ConstraintClaim,
- DecisionView projection.

## Primary threats and controls

| Threat | Required control |
|---|---|
| Prompt injection in evidence | Separate instruction and data fields; enforce tool permissions outside the model |
| Cross-user data leak | Authorization on every resource and event subscription; row-level isolation |
| Premature vote disclosure | Release first-round ballots atomically after all three close |
| Fabricated citation | Require evidence IDs that exist in the frozen snapshot |
| Evidence replacement | Store content hash and immutable snapshot version |
| Sensitive data in logs | Classify and redact before logging or client projection |
| Model prompt copied into telemetry | Store a SHA-256 prompt digest, not raw prompt content |
| Secret exposure | Keep credentials in the server-side gateway; never place them in prompts |
| Duplicate run | Require idempotency keys and stage transition guards |
| Retry counted as another vote | Reference attempts in audit; count one accepted ballot per agent and round |
| Provider error leaks sensitive text | Record only the exception type in model-call telemetry |
| Unsafe checkpoint deserialization | Use the LangGraph serializer with an explicit safe module allowlist |
| Cross-process duplicate model call | Serialize each idempotency key with a PostgreSQL advisory lock |
| Invocation/checkpoint database exposure | Restrict database credentials, network access, and application roles |
| Presenter changes result | Generate from ArbitrationResult and validate invariant fields |
| Tool or agent loop | Enforce turn, tool, retry, and review limits in code |
| Correlated model failure | Preserve independent contexts, use high-risk review, and evaluate representative cases |

## Data handling

- Never place restricted data in model context.
- Redact sensitive fields from public events and DecisionView.
- Separate ordinary conversation retention from append-only decision audit retention.
- Provide user export, correction, and deletion paths subject to the configured audit policy.
- Store concise rationale summaries, not hidden chain-of-thought.

## Initial authority

The first release is read-only and advisory. It cannot send messages, modify files, write business data, execute commands, purchase, or control devices. Adding an executor requires a separate threat model and explicit approval workflow.
