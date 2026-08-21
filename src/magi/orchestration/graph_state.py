"""Serializable state schema shared by LangGraph and test harnesses."""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class MagiGraphState(TypedDict, total=False):
    """Keep checkpointed graph state JSON-serializable."""

    case: dict[str, Any]
    snapshot: dict[str, Any]
    preparation_fingerprint: str
    constraint_validations: list[dict[str, Any]]
    first_ballots: Annotated[list[dict[str, Any]], operator.add]
    review_ballots: Annotated[list[dict[str, Any]], operator.add]
    first_assessment: dict[str, Any]
    result: dict[str, Any]
    phase: str
    cancelled: bool
    run_failed: bool
