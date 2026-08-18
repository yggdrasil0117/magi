# M2a LangGraph Orchestration

Status: code complete, runtime smoke test passed  
Package version: 0.2.0a1  
Architecture version: 0.2

## Implemented

- JSON-serializable MagiGraphState with reducers for parallel first and review ballots.
- LangGraph StateGraph builder with explicit fan-out and fan-in.
- Human confirmation interrupt and cancellation branch.
- Evidence validation before any perspective runs.
- Three isolated first-ballot nodes.
- Deterministic first-round assessment and conditional routing.
- Three isolated cross-review nodes with sanitized peer summaries.
- M1 deterministic arbiter as the only final decision rule.
- InMemorySaver default with injectable checkpointer for PostgreSQL in M2b.
- ScriptedPerspectiveRunner for deterministic tests.
- PublicEventProjector that hides partial votes until first-round closure.

## Graph

~~~text
START
  -> prepare_case
  -> confirm_case [interrupt]
       -> mark_cancelled -> END
       -> validate_evidence
            -> first_melchior
            -> first_balthasar
            -> first_casper
                 -> assess_first
                      -> arbitrate -> END
                      -> begin_review
                           -> review_melchior
                           -> review_balthasar
                           -> review_casper
                                -> arbitrate -> END
~~~

## State ownership

- LangGraph checkpoint state controls progress and recovery.
- DecisionCase, ballots, and ArbitrationResult remain validated domain records.
- PostgreSQL DecisionRecord remains the future canonical audit source.
- LangGraph checkpoint data must not be exposed directly to clients.

## Secrecy

Parallel ballot nodes write private ballot records to graph state. Their public completion events include only agent name and round. Vote counts are emitted only by assess_first after all three branches have joined.

Cross-review receives PeerBallotSummary records only. It does not receive private working memory, hidden instructions, or hidden reasoning.

## Dependency and verification status

The project declares LangGraph, LangChain, LangChain OpenAI, Pydantic, and python-dotenv as direct dependencies with major-version bounds. The project-local virtual environment currently uses LangGraph 1.2.11, LangChain 1.3.15, LangChain OpenAI 1.5.1, and python-dotenv 1.2.3.

The real graph integration test passes for interrupt, checkpoint resume, parallel first ballots, parallel cross-review, and deterministic arbitration. The full suite runs 40 tests successfully; the negative test for a missing LangGraph runtime is skipped when LangGraph is installed.

## M2b

- Replace ScriptedPerspectiveRunner with OpenAI Agents SDK adapters.
- Add PostgreSQL checkpointer using thread ID decision_id:version.
- Persist append-only DecisionRecord separately from checkpoints.
- Convert graph stream updates into authenticated WebSocket events.
- Add retry and idempotency keys around model calls.
