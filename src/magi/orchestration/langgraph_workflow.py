"""LangGraph wiring for the M2a MAGI workflow."""

from __future__ import annotations

from typing import Any

from magi.agents import PerspectiveRunner
from magi.arbitration import DeterministicArbiter
from magi.domain import AgentName

from .graph_state import MagiGraphState
from .workflow_nodes import MagiWorkflowNodes


class LangGraphUnavailable(RuntimeError):
    """Raised when the optional orchestration runtime is not installed."""


def build_langgraph_workflow(
    runner: PerspectiveRunner,
    *,
    arbiter: DeterministicArbiter | None = None,
    checkpointer: Any | None = None,
) -> Any:
    """Compile the M2a graph with isolated parallel perspective branches."""

    try:
        from langgraph.checkpoint.memory import InMemorySaver
        from langgraph.graph import END, START, StateGraph
        from langgraph.types import interrupt
    except ModuleNotFoundError as exc:
        raise LangGraphUnavailable(
            "LangGraph is not installed. Install project dependencies before "
            "building the M2a workflow."
        ) from exc

    nodes = MagiWorkflowNodes(runner, arbiter)
    builder = StateGraph(MagiGraphState)

    def confirm_case(state: MagiGraphState) -> dict[str, Any]:
        resume_value = interrupt(
            {
                "type": "user_confirmation_required",
                "case": state["case"],
            }
        )
        return nodes.apply_confirmation(state, resume_value)

    async def first_melchior(state: MagiGraphState) -> dict[str, Any]:
        return await nodes.run_first_ballot(AgentName.MELCHIOR, state)

    async def first_balthasar(state: MagiGraphState) -> dict[str, Any]:
        return await nodes.run_first_ballot(AgentName.BALTHASAR, state)

    async def first_casper(state: MagiGraphState) -> dict[str, Any]:
        return await nodes.run_first_ballot(AgentName.CASPER, state)

    async def review_melchior(state: MagiGraphState) -> dict[str, Any]:
        return await nodes.run_review_ballot(AgentName.MELCHIOR, state)

    async def review_balthasar(state: MagiGraphState) -> dict[str, Any]:
        return await nodes.run_review_ballot(AgentName.BALTHASAR, state)

    async def review_casper(state: MagiGraphState) -> dict[str, Any]:
        return await nodes.run_review_ballot(AgentName.CASPER, state)

    builder.add_node("prepare_case", nodes.prepare_case)
    builder.add_node("confirm_case", confirm_case)
    builder.add_node("validate_evidence", nodes.validate_evidence)
    builder.add_node("first_melchior", first_melchior)
    builder.add_node("first_balthasar", first_balthasar)
    builder.add_node("first_casper", first_casper)
    builder.add_node("assess_first", nodes.assess_first)
    builder.add_node("begin_review", nodes.begin_review)
    builder.add_node("review_melchior", review_melchior)
    builder.add_node("review_balthasar", review_balthasar)
    builder.add_node("review_casper", review_casper)
    builder.add_node("arbitrate", nodes.arbitrate)
    builder.add_node("mark_cancelled", nodes.mark_cancelled)

    builder.add_edge(START, "prepare_case")
    builder.add_edge("prepare_case", "confirm_case")
    builder.add_conditional_edges(
        "confirm_case",
        nodes.route_after_confirmation,
        {
            "continue": "validate_evidence",
            "cancelled": "mark_cancelled",
        },
    )
    builder.add_edge("mark_cancelled", END)

    builder.add_edge("validate_evidence", "first_melchior")
    builder.add_edge("validate_evidence", "first_balthasar")
    builder.add_edge("validate_evidence", "first_casper")
    builder.add_edge(
        ["first_melchior", "first_balthasar", "first_casper"],
        "assess_first",
    )
    builder.add_conditional_edges(
        "assess_first",
        nodes.route_after_first,
        {
            "cross_review": "begin_review",
            "arbitrate": "arbitrate",
        },
    )
    builder.add_edge("begin_review", "review_melchior")
    builder.add_edge("begin_review", "review_balthasar")
    builder.add_edge("begin_review", "review_casper")
    builder.add_edge(
        ["review_melchior", "review_balthasar", "review_casper"],
        "arbitrate",
    )
    builder.add_edge("arbitrate", END)

    selected_checkpointer = checkpointer if checkpointer is not None else InMemorySaver()
    return builder.compile(checkpointer=selected_checkpointer)
