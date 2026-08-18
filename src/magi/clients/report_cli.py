"""Keyboard-friendly terminal client for the authoritative report API."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import sys
import textwrap
import unicodedata
from collections.abc import Iterable, Sequence
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from uuid import UUID

from pydantic import ValidationError

from magi.application import DecisionReport
from magi.domain import ArbitrationStatus

MAX_REPORT_BYTES = 1_000_000


class ReportClientError(RuntimeError):
    """Sanitized failure raised by the terminal report client."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def fetch_report(
    base_url: str,
    decision_id: UUID,
    version: int,
    bearer_token: str,
    *,
    timeout: float = 10,
) -> DecisionReport:
    """Read and validate one report without retaining or displaying the token."""

    if version < 1:
        raise ReportClientError("decision version must be at least one")
    if not bearer_token:
        raise ReportClientError("a bearer token is required")
    if timeout <= 0:
        raise ReportClientError("request timeout must be positive")
    endpoint = _report_url(base_url, decision_id, version)
    request = Request(
        endpoint,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {bearer_token}",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310
            payload = _bounded_read(response)
    except HTTPError as exc:
        payload = _bounded_read(exc)
        raise ReportClientError(
            _api_error_message(payload, exc.code),
            status_code=exc.code,
        ) from exc
    except (URLError, TimeoutError) as exc:
        raise ReportClientError("the report API could not be reached") from exc

    try:
        return DecisionReport.model_validate_json(payload)
    except ValidationError as exc:
        raise ReportClientError("the report API returned an invalid report") from exc


def _report_url(base_url: str, decision_id: UUID, version: int) -> str:
    candidate = base_url.strip().rstrip("/")
    parsed = urlsplit(candidate)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ReportClientError(
            "the API URL must be an HTTP origin or path without credentials"
        )
    query = urlencode({"version": version})
    return f"{candidate}/v1/decisions/{decision_id}/report?{query}"


def _bounded_read(response: Any) -> bytes:
    declared = response.headers.get("Content-Length")
    if declared is not None:
        try:
            if int(declared) > MAX_REPORT_BYTES:
                raise ReportClientError("the report API response is too large")
        except ValueError as exc:
            raise ReportClientError("the report API returned an invalid length") from exc
    payload = response.read(MAX_REPORT_BYTES + 1)
    if len(payload) > MAX_REPORT_BYTES:
        raise ReportClientError("the report API response is too large")
    return payload


def _api_error_message(payload: bytes, status_code: int) -> str:
    try:
        document = json.loads(payload)
        detail = document["error"]
        code = str(detail["code"])
        message = str(detail["message"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return f"the report API returned HTTP {status_code}"
    return f"{code}: {_terminal_text(message)}"


class DecisionReportTerminalRenderer:
    """Render report fields for a terminal without interpreting external control text."""

    def render(
        self,
        report: DecisionReport,
        *,
        width: int = 88,
        color: bool = False,
    ) -> str:
        width = max(60, min(width, 160))
        heading = self._style("MAGI // DECISION REPORT", "36;1", color)
        status = self._style(report.status.value.upper(), self._status_color(report), color)
        selected = "—"
        if report.selected_option is not None:
            selected = (
                f"{_terminal_text(report.selected_option_label or report.selected_option)} "
                f"[{report.selected_option}]"
            )
        lines = [
            heading,
            "═" * width,
            f"Decision  {report.decision_id}  ·  v{report.version}",
            f"Status    {status}",
            f"Selected  {selected}",
            f"Ballots   {report.ballot_count}  ·  Protocol {report.protocol_version}  "
            f"·  Rule {report.rule_version}",
            "─" * width,
        ]
        self._section(
            lines,
            "VOTE COUNT",
            tuple(f"{option}: {count}" for option, count in sorted(report.vote_count.items())),
            width,
            color,
        )
        self._section(lines, "MAJORITY RATIONALE", report.majority_rationale, width, color)
        self._minority(lines, report, width, color)
        self._section(lines, "EVIDENCE", report.evidence_refs, width, color)
        self._section(lines, "ASSUMPTIONS", report.assumptions, width, color)
        self._section(
            lines,
            "UNRESOLVED QUESTIONS",
            report.unresolved_questions,
            width,
            color,
        )
        self._section(lines, "RISKS", report.risks, width, color)
        self._section(lines, "CONDITIONS", report.conditions, width, color)
        self._section(
            lines,
            "NEXT STEP",
            (report.recommended_next_step,),
            width,
            color,
        )
        self._review_audit(lines, report, width, color)
        lines.extend(("─" * width, f"Generated  {report.generated_at.isoformat()}"))
        return "\n".join(lines) + "\n"

    def _section(
        self,
        lines: list[str],
        title: str,
        items: Iterable[str],
        width: int,
        color: bool,
    ) -> None:
        lines.extend(("", self._style(title, "36", color)))
        rendered = tuple(_terminal_text(item) for item in items if item)
        if not rendered:
            lines.append("  —")
            return
        for item in rendered:
            lines.extend(_wrapped_bullet(item, width))

    def _minority(
        self,
        lines: list[str],
        report: DecisionReport,
        width: int,
        color: bool,
    ) -> None:
        minority = report.minority_report
        if minority is None:
            self._section(lines, "MINORITY REPORT", (), width, color)
            return
        selected = minority.selected_option or "abstain"
        items = (
            f"{minority.agent.value} · {minority.stance.value} · {selected}",
            *minority.rationale_summary,
        )
        self._section(lines, "MINORITY REPORT", items, width, color)

    def _review_audit(
        self,
        lines: list[str],
        report: DecisionReport,
        width: int,
        color: bool,
    ) -> None:
        items = tuple(
            f"{entry.agent.value} · "
            f"{'revised' if entry.changed else 'retained'} · {entry.reason}"
            for entry in report.review_audit
        )
        self._section(lines, "REVIEW AUDIT", items, width, color)

    @staticmethod
    def _style(value: str, code: str, enabled: bool) -> str:
        return f"\x1b[{code}m{value}\x1b[0m" if enabled else value

    @staticmethod
    def _status_color(report: DecisionReport) -> str:
        if report.status in {ArbitrationStatus.CONSENSUS, ArbitrationStatus.MAJORITY}:
            return "32;1"
        if report.status in {
            ArbitrationStatus.UNRESOLVED,
            ArbitrationStatus.CONDITIONAL_REJECTION,
            ArbitrationStatus.INSUFFICIENT_INFORMATION,
        }:
            return "33;1"
        return "31;1"


def _wrapped_bullet(value: str, width: int) -> tuple[str, ...]:
    wrapped = textwrap.wrap(
        value,
        width=max(20, width - 4),
        initial_indent="  • ",
        subsequent_indent="    ",
        break_long_words=False,
        break_on_hyphens=False,
    )
    return tuple(wrapped) or ("  • —",)


def _terminal_text(value: str) -> str:
    safe = "".join(
        character if not unicodedata.category(character).startswith("C") else " "
        for character in value
    )
    return " ".join(safe.split())


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read a MAGI final report")
    parser.add_argument("decision_id", type=UUID)
    parser.add_argument("--version", type=int, default=1)
    parser.add_argument(
        "--api-url",
        default=os.getenv("MAGI_API_URL", "http://127.0.0.1:8000"),
    )
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--no-color", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    token = os.getenv("MAGI_API_TOKEN")
    if not token and sys.stdin.isatty():
        token = getpass.getpass("MAGI API token: ")
    if not token:
        print("error: set MAGI_API_TOKEN or run from an interactive terminal", file=sys.stderr)
        return 5
    try:
        report = fetch_report(
            args.api_url,
            args.decision_id,
            args.version,
            token,
            timeout=args.timeout,
        )
    except ReportClientError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 5

    if args.as_json:
        print(report.model_dump_json(indent=2))
    else:
        color = (
            not args.no_color
            and "NO_COLOR" not in os.environ
            and sys.stdout.isatty()
        )
        width = shutil.get_terminal_size(fallback=(88, 24)).columns
        print(DecisionReportTerminalRenderer().render(report, width=width, color=color), end="")
    return _exit_code(report.status)


def _exit_code(status: ArbitrationStatus) -> int:
    if status in {ArbitrationStatus.CONSENSUS, ArbitrationStatus.MAJORITY}:
        return 0
    if status in {
        ArbitrationStatus.UNRESOLVED,
        ArbitrationStatus.CONDITIONAL_REJECTION,
        ArbitrationStatus.INSUFFICIENT_INFORMATION,
    }:
        return 2
    if status is ArbitrationStatus.DEGRADED:
        return 3
    return 4


if __name__ == "__main__":
    raise SystemExit(main())
