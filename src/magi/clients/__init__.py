"""API-consuming client surfaces for MAGI reports."""

from typing import Any

__all__ = [
    "DecisionReportTerminalRenderer",
    "ReportClientError",
    "fetch_report",
]


def __getattr__(name: str) -> Any:
    if name not in __all__:
        raise AttributeError(name)
    from . import report_cli

    return getattr(report_cli, name)
