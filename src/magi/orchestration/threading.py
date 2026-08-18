"""Stable LangGraph thread identity for decision versions."""

from __future__ import annotations


def decision_thread_id(decision_id: object, version: int) -> str:
    if version < 1:
        raise ValueError("decision version must be positive")
    thread_id = f"{decision_id}:{version}"
    if len(thread_id) > 255:
        raise ValueError("decision thread ID exceeds PostgreSQL checkpointer limit")
    return thread_id
