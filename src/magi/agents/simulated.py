"""Scripted perspective runner for deterministic M2a graph tests."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

from magi.domain import AgentName, Ballot, DecisionCase, EvidenceSnapshot

from .ports import PeerBallotSummary, PerspectiveExecutionError


class ScriptedPerspectiveRunner:
    """Return prebuilt ballots while enforcing assignment boundaries."""

    def __init__(
        self,
        first_ballots: Mapping[AgentName, Ballot],
        review_ballots: Mapping[AgentName, Ballot] | None = None,
        *,
        delay_seconds: float = 0,
    ) -> None:
        self._first_ballots = dict(first_ballots)
        self._review_ballots = dict(review_ballots or {})
        self._delay_seconds = delay_seconds
        self.calls: list[tuple[str, AgentName]] = []

    async def first_ballot(
        self,
        agent: AgentName,
        case: DecisionCase,
        snapshot: EvidenceSnapshot,
    ) -> Ballot:
        await asyncio.sleep(self._delay_seconds)
        self.calls.append(("first", agent))
        try:
            ballot = self._first_ballots[agent]
        except KeyError as exc:
            raise PerspectiveExecutionError(
                f"no scripted first ballot for {agent.value}"
            ) from exc
        self._validate_assignment(ballot, agent, case, expected_round=1)
        return ballot

    async def review_ballot(
        self,
        agent: AgentName,
        case: DecisionCase,
        snapshot: EvidenceSnapshot,
        previous_ballot: Ballot,
        peer_summaries: tuple[PeerBallotSummary, ...],
    ) -> Ballot:
        await asyncio.sleep(self._delay_seconds)
        self.calls.append(("review", agent))
        if len(peer_summaries) != 2 or any(
            summary.agent is agent for summary in peer_summaries
        ):
            raise PerspectiveExecutionError(
                "cross-review requires exactly two peer summaries"
            )
        try:
            ballot = self._review_ballots[agent]
        except KeyError as exc:
            raise PerspectiveExecutionError(
                f"no scripted review ballot for {agent.value}"
            ) from exc
        self._validate_assignment(ballot, agent, case, expected_round=2)
        if ballot.previous_ballot_id != previous_ballot.ballot_id:
            raise PerspectiveExecutionError(
                f"{agent.value} review ballot references the wrong first ballot"
            )
        return ballot

    @staticmethod
    def _validate_assignment(
        ballot: Ballot,
        agent: AgentName,
        case: DecisionCase,
        *,
        expected_round: int,
    ) -> None:
        if ballot.agent is not agent:
            raise PerspectiveExecutionError(
                f"{agent.value} runner returned a {ballot.agent.value} ballot"
            )
        if ballot.round != expected_round:
            raise PerspectiveExecutionError(
                f"{agent.value} runner returned round {ballot.round}, "
                f"expected {expected_round}"
            )
        if ballot.decision_id != case.decision_id or ballot.decision_version != case.version:
            raise PerspectiveExecutionError(
                f"{agent.value} runner returned a ballot for another decision"
            )

