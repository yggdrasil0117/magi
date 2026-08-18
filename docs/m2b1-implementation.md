# M2b-1 Model Perspective Adapter

Status: implemented and locally verified without live API calls  
Package version: 0.2.0b1  
Architecture version: 0.2

## Scope

This increment connects the LangGraph perspective nodes to a real
LangChain/OpenAI model boundary while keeping model calls optional during local
tests. It does not add PostgreSQL, HTTP APIs, or clients.

## Isolation

- One independent structured model runnable is created for each perspective.
- Every call receives the shared MAGI core protocol and exactly one perspective
  skill.
- First-round prompts contain no peer ballots, summaries, or vote counts.
- Review prompts contain the agent's previous ballot and two sanitized
  `PeerBallotSummary` records only.
- Case data, evidence excerpts, and peer summaries are explicitly marked as
  untrusted input rather than instructions.

## Authority boundary

The model returns `BallotDraft`, not the canonical `Ballot`. The draft cannot set:

- decision ID or version;
- agent identity;
- ballot ID or round;
- previous ballot ID;
- creation timestamp.

Application code supplies those fields and rejects option IDs outside the
confirmed case or evidence references outside the frozen snapshot. Invalid,
refused, or unstructured model responses become `PerspectiveExecutionError`.

## Structured output

The OpenAI factory uses the Responses API and LangChain's strict JSON Schema
structured output with a Pydantic model. The model name is deliberately explicit
through `MAGI_OPENAI_MODEL`; MAGI does not silently substitute another model.

Live configuration is read only when `from_environment()` is called:

~~~text
OPENAI_API_KEY=...
MAGI_OPENAI_MODEL=...
MAGI_SKILLS_DIR=...  # optional
~~~

## Verification

- All three model boundaries are required.
- Assigned skill isolation is checked from the generated system prompt.
- First-round peer secrecy is checked from the generated user payload.
- Cross-review excludes peer ballot IDs and private state.
- Invalid option and evidence references are rejected.
- Provider failures and non-schema output are converted to bounded execution
  errors without including provider response text.
- The complete suite runs 48 tests: 47 pass and the missing-LangGraph negative
  test is skipped because LangGraph is installed.

## Remaining M2b work

- Run a controlled live-model evaluation after the user selects a model and
  supplies an API key locally.
- Add request idempotency, retry classification, token usage, latency, and cost
  records.
- Add PostgreSQL checkpointing and append-only canonical audit records.
