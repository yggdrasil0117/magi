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
| Partial review vote disclosure | Keep first ballots visible during review; release review ballots only with final arbitration |
| Fabricated citation | Require evidence IDs that exist in the frozen snapshot |
| Evidence replacement | Store content hash and immutable snapshot version |
| Sensitive data in logs | Classify and redact before logging or client projection |
| Model prompt copied into telemetry | Store a SHA-256 prompt digest, not raw prompt content |
| Coordinator overwrites authoritative input | Seal raw question, ID, version, classification, and risk floor in application code |
| User assertion promoted to fact | Seal normalized claims as user-asserted with no evidence references |
| Restricted evidence reaches model or client | Filter it from perspective prompts and DecisionView; reject citations |
| Client selects another checkpoint | Derive thread ID from authorized decision ID and version inside the application service |
| Unauthenticated decision API | Require an injected bearer authenticator and per-decision authorizer; provide no allow-all default |
| Credential or request-body reflection | Return stable sanitized errors and never include validation bodies or auth-provider detail |
| Cross-user idempotency collision | Hash and scope command keys by authenticated principal |
| API idempotency key leaks from database | Persist only principal and key SHA-256 digests, never raw values |
| Duplicate command across API processes | Hold a PostgreSQL advisory lock through lookup, execution, and result insertion |
| Production starts with test adapters | Production factory requires PostgreSQL, OpenAI, skills, and authorization policy; no in-memory fallback |
| Static bearer token disclosure | Store only SHA-256 digests in policy, compare digests in constant time, and require high-entropy tokens |
| Over-broad API credential | Bind every subject to explicit actions and decision IDs; all-decisions access requires an explicit flag |
| Client chooses decision or evidence identity | Derive decision ID from principal and idempotency key; assign evidence IDs in application code |
| Client marks supplied evidence verified | Seal supplied evidence as user-asserted and calculate content hashes server-side |
| Create retry duplicates work or changes normalization | Reuse a deterministic principal-scoped decision ID and validate a checkpointed preparation fingerprint before Coordinator invocation |
| Readiness leaks infrastructure detail | Return only ready/not-ready and suppress database exception text |
| Dependency failure receives traffic | Require the application binding and a bounded PostgreSQL probe before reporting ready |
| Automated test triggers paid model calls | Require the explicit `MAGI_RUN_M2_LIVE=1` opt-in flag |
| Secret exposure | Keep credentials in the server-side gateway; never place them in prompts |
| Duplicate run | Require idempotency keys and stage transition guards |
| Retry counted as another vote | Reference attempts in audit; count one accepted ballot per agent and round |
| Provider error leaks sensitive text | Record only the exception type in model-call telemetry |
| Unsafe checkpoint deserialization | Use the LangGraph serializer with an explicit safe module allowlist |
| Cross-process duplicate model call | Serialize each idempotency key with a PostgreSQL advisory lock |
| Invocation/checkpoint database exposure | Restrict database credentials, network access, and application roles |
| Presenter changes result | Generate from ArbitrationResult and validate invariant fields |
| Review rationale is lost or rewritten | Require a reason on every second-round ballot and project it verbatim into immutable review audit links |
| Report invents a recommendation | Use a deterministic projector and forbid selected options on non-decisive statuses |
| Exported rationale becomes active markup | Collapse newlines, escape Markdown controls, force attachment download, and send `nosniff` |
| Shared cache leaks a report | Mark JSON and Markdown report responses private and no-store |
| Model text injects terminal controls | Remove Unicode control categories before terminal layout and add only application-owned ANSI |
| Browser report executes external text | Build DOM nodes with `textContent`; disallow inline code with CSP |
| Browser token persists or crosses origins | Keep it in page memory and use a loopback same-origin report-only proxy |
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
