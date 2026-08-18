"""Sanitized public-event projection for graph node updates."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from magi.domain import DecisionEvent


FIRST_AGENT_NODES = {
    "first_melchior": "melchior",
    "first_balthasar": "balthasar",
    "first_casper": "casper",
}

REVIEW_AGENT_NODES = {
    "review_melchior": "melchior",
    "review_balthasar": "balthasar",
    "review_casper": "casper",
}


class PublicEventProjector:
    """Convert internal graph updates to DecisionEvents without leaking ballots."""

    def __init__(
        self,
        decision_id: UUID,
        decision_version: int,
        *,
        starting_sequence: int = 0,
    ) -> None:
        self._decision_id = decision_id
        self._decision_version = decision_version
        self._sequence = starting_sequence

    def project(
        self,
        node_name: str,
        update: Mapping[str, Any],
    ) -> DecisionEvent | None:
        event_type: str
        actor = "orchestrator"
        payload: dict[str, Any]

        if node_name == "prepare_case":
            event_type = "case.normalized"
            payload = {}
        elif node_name == "confirm_case":
            event_type = (
                "decision.cancelled"
                if update.get("cancelled")
                else "case.confirmed"
            )
            payload = {"cancelled": bool(update.get("cancelled", False))}
        elif node_name == "validate_evidence":
            event_type = "evidence.snapshot_created"
            payload = {}
        elif node_name in FIRST_AGENT_NODES:
            actor = FIRST_AGENT_NODES[node_name]
            event_type = "agent.completed"
            payload = {"agent": actor, "round": 1}
        elif node_name == "assess_first":
            assessment = dict(update.get("first_assessment", {}))
            event_type = "first_ballot.completed"
            payload = {
                "action": assessment.get("action"),
                "vote_count": assessment.get("vote_count", {}),
                "missing_agents": assessment.get("missing_agents", []),
                "abstentions": assessment.get("abstentions", []),
            }
        elif node_name == "begin_review":
            event_type = "cross_review.started"
            payload = {}
        elif node_name in REVIEW_AGENT_NODES:
            actor = REVIEW_AGENT_NODES[node_name]
            event_type = "agent.review_completed"
            payload = {"agent": actor, "round": 2}
        elif node_name == "arbitrate":
            result = dict(update.get("result", {}))
            event_type = "arbitration.completed"
            payload = {
                "status": result.get("status"),
                "winning_option": result.get("winning_option"),
                "vote_count": result.get("vote_count", {}),
            }
        else:
            return None

        self._sequence += 1
        return DecisionEvent(
            decision_id=self._decision_id,
            decision_version=self._decision_version,
            sequence=self._sequence,
            type=event_type,
            actor=actor,
            public_payload=payload,
        )
