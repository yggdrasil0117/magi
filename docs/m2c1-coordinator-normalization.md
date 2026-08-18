# M2c-1 Coordinator Normalization

Status: implemented and locally verified without live API calls  
Package version: 0.2.0b4  
Architecture version: 0.2

## Role boundary

The Coordinator is a non-voting preprocessing role. It does not become a fourth
MAGI personality, recommend an option, participate in cross-review, or alter an
agent ballot. It loads only the shared `magi-core` protocol; the three persona
skills remain exclusive to Melchior, Balthasar, and Casper.

`DecisionNormalizer` is the application-facing port. `LangChainCoordinator` is
its structured-output adapter for an explicitly selected OpenAI model.

## Input and output

`NormalizationRequest` contains the authoritative raw question, decision ID,
version, minimum risk level, and data classification. The Coordinator proposes:

- a short title and normalized question;
- a protocol-1.0 boolean or single-choice option set;
- explicit hard and soft user constraints;
- context claims and material unknowns;
- a proposed risk level.

Open, ranking, and multiple-choice questions must be converted into explicit
single-choice options. A draft that still uses an unsupported decision type is
rejected.

## Authority sealing

Application code, not the model, controls these fields:

- `decision_id`, version, and the exact `raw_question`;
- data classification;
- the minimum risk level;
- claim verification status and evidence references;
- confirmation state.

The model may raise risk but cannot lower the request's risk floor. Every
normalized context claim is sealed as `user_asserted` with no evidence reference.
Every output case has `confirmed_at=None`, so it cannot enter voting until the
user confirms the structured case.

## Prompt isolation

The system prompt contains the shared MAGI protocol and explicit non-voting
instructions. Raw user content is serialized under `UNTRUSTED_INPUT_JSON` and is
treated as data. No perspective skill or peer output enters the Coordinator
context.

Provider error text and malformed model output are converted into sanitized
`CoordinatorExecutionError` messages.

## Verification

- Authoritative ID, version, raw question, classification, and confirmation are
  sealed by tests.
- Risk floors cannot be lowered and higher proposed risk is retained.
- User claims cannot become verified facts or cite invented evidence.
- Persona skill text is absent from the Coordinator prompt.
- Unsupported decision types and invalid option IDs are rejected.
- Provider error payloads are not exposed.
- The complete suite runs 68 tests: 66 pass and 2 expected tests skip locally.

## Next increment

M2c-2 should add the application service that stores prepared cases, resumes the
LangGraph confirmation interrupt, projects a shared `DecisionView`, and provides
one execution boundary for the API, Web, TUI, and CLI.
