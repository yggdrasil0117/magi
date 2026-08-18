# M1 Deterministic Decision Kernel

Status: implemented  
Package version: 0.1.0  
Protocol version: 1.0

## Included

- Strict immutable Pydantic records for DecisionCase, EvidenceSnapshot, Ballot, ConstraintClaim, ConstraintValidation, RoundAssessment, ArbitrationResult, and DecisionEvent.
- Shared enums and explicit protocol exceptions.
- Framework-independent lifecycle state machine with legal transitions and transition history.
- First-round router for consensus, mandatory cross-review, insufficient information, conditional rejection, degraded operation, and failure.
- Deterministic final arbiter that preserves a minority report and never weights votes by confidence.
- Evidence, decision-version, agent, ballot, and accepted-constraint validation.
- Versioned JSON fixtures and standard-library unit tests.

## Protocol 1.0 limits

- Arbitrate boolean and single-choice decisions only.
- Require a user-confirmed case and matching frozen evidence snapshot.
- Require all cited evidence to exist in that snapshot.
- Forbid ballots and constraint claims from citing restricted evidence.
- Require cross-review for high-risk unanimity, 2:1, 1:1:1, or any other non-unanimous complete first round.
- Treat one unavailable agent as degraded and two unavailable agents as failed.
- Treat two abstentions as insufficient information.
- Treat an accepted hard constraint as conditional rejection and require a reconsideration condition.

## Module map

~~~text
src/magi/domain/enums.py
src/magi/domain/errors.py
src/magi/domain/models.py
src/magi/orchestration/state_machine.py
src/magi/arbitration/engine.py
~~~

## Run tests

Install the project dependencies, then run:

~~~text
python -m unittest discover -s tests/unit -v
~~~

M1 deliberately has no LangGraph, model, API, database, or UI runtime. M2 will wrap this kernel in LangGraph nodes without moving arbitration rules into the graph.

