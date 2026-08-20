"""Keyboard-first, no-dependency terminal workflow shell."""

from __future__ import annotations

import json
import unicodedata
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID

from .workflow_cli import request_json


def run(input_fn: Callable[[str], str] = input, output_fn: Callable[[str], None] = print) -> None:
    output_fn(
        "MAGI TERMINAL / inbox, get, history, audit, create, confirm, run, "
        "cancel, redact, evaluations, evaluate, watch, quit"
    )
    while True:
        parts = input_fn("magi> ").strip().split()
        if not parts:
            continue
        if parts[0] in {"quit", "exit"}:
            return
        try:
            identity_commands = {
                "get", "history", "audit", "confirm", "run", "cancel",
                "redact", "evaluations", "evaluate", "watch",
            }
            if parts[0] in identity_commands and len(parts) >= 2:
                parts[1] = str(UUID(parts[1]))
            if parts[0] == "inbox":
                payload = request_json("GET", "/v1/decisions?limit=50")
            elif parts[0] == "get" and len(parts) in {2, 3}:
                version = parts[2] if len(parts) == 3 else 1
                payload = request_json(
                    "GET", f"/v1/decisions/{parts[1]}?version={version}"
                )
            elif parts[0] == "history" and len(parts) == 2:
                payload = request_json("GET", f"/v1/decisions/{parts[1]}/versions")
            elif parts[0] == "audit" and len(parts) in {2, 3}:
                version = parts[2] if len(parts) == 3 else 1
                payload = request_json(
                    "GET", f"/v1/decisions/{parts[1]}/audit?version={version}"
                )
            elif parts[0] == "evaluations" and len(parts) in {2, 3, 4}:
                version = _bounded_positive(parts[2]) if len(parts) >= 3 else 1
                limit = _bounded_positive(parts[3]) if len(parts) == 4 else 20
                payload = request_json(
                    "GET",
                    f"/v1/decisions/{parts[1]}/evaluations"
                    f"?version={version}&limit={limit}",
                )
            elif parts[0] == "evaluate" and len(parts) in {2, 3}:
                version = _bounded_positive(parts[2]) if len(parts) == 3 else 1
                payload = request_json(
                    "POST",
                    f"/v1/decisions/{parts[1]}/evaluations",
                    body={"version": version},
                )
            elif parts[0] == "watch" and len(parts) == 2:
                payload = request_json("GET", f"/v1/operations/{parts[1]}")
            elif parts[0] == "create" and len(parts) >= 2:
                payload = request_json(
                    "POST", "/v1/decisions",
                    body={"raw_question": " ".join(parts[1:]), "evidence": []},
                    async_preference=True,
                )
            elif parts[0] == "run" and len(parts) in {2, 3}:
                payload = request_json(
                    "POST", f"/v1/decisions/{parts[1]}/run",
                    body={"version": int(parts[2]) if len(parts) == 3 else 1},
                    async_preference=True,
                )
            elif parts[0] == "confirm" and len(parts) in {2, 3}:
                payload = request_json(
                    "POST", f"/v1/decisions/{parts[1]}/confirm",
                    body={
                        "version": int(parts[2]) if len(parts) == 3 else 1,
                        "confirmed_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
            elif parts[0] == "cancel" and len(parts) in {2, 3}:
                payload = request_json(
                    "POST", f"/v1/decisions/{parts[1]}/cancel",
                    body={"version": int(parts[2]) if len(parts) == 3 else 1},
                )
            elif parts[0] == "redact" and len(parts) in {4, 5}:
                target_record_id = str(UUID(parts[2]))
                version = int(parts[4]) if len(parts) == 5 else 1
                reason = input_fn("redaction reason> ").strip()
                if not reason:
                    output_fn("Redaction reason is required.")
                    continue
                payload = request_json(
                    "POST", f"/v1/decisions/{parts[1]}/audit/redactions",
                    body={
                        "version": version,
                        "target_record_id": target_record_id,
                        "field_paths": [parts[3]],
                        "reason": reason,
                    },
                )
            else:
                output_fn("Unknown command or arguments.")
                continue
            if parts[0] in {"evaluations", "evaluate"}:
                output_fn(_render_evaluation(payload))
            else:
                output_fn(json.dumps(payload, ensure_ascii=False, indent=2))
        except Exception:
            output_fn("Request failed. Credentials and server details were not displayed.")


def _render_evaluation(payload: dict[str, object]) -> str:
    raw_records = payload.get("evaluations")
    if raw_records is None:
        records: list[object] = [payload]
        total_count = 1
    elif isinstance(raw_records, list):
        records = raw_records
        total_count = _nonnegative(payload.get("total_count"))
    else:
        raise ValueError("invalid evaluation records")

    decision_id = _terminal_text(payload.get("decision_id", "UNKNOWN"))
    version = payload.get("decision_version", "?")
    lines = [
        "MAGI // QUALITY EVALUATION",
        "═" * 72,
        f"DECISION  {decision_id}  ·  V{_terminal_text(version)}",
        f"HISTORY   WINDOW {len(records)} / TOTAL {total_count}",
    ]
    trend = payload.get("trend")
    if isinstance(trend, dict):
        lines.append(
            "TREND     "
            f"PASS {_nonnegative(trend.get('pass_count'))}  ·  "
            f"WARN {_nonnegative(trend.get('warn_count'))}  ·  "
            f"FAIL {_nonnegative(trend.get('fail_count'))}"
        )
    if not records:
        lines.extend(("─" * 72, "NO EVALUATION RECORDS"))
        return "\n".join(lines)

    latest = records[-1]
    if not isinstance(latest, dict) or not isinstance(latest.get("evaluation"), dict):
        raise ValueError("invalid evaluation record")
    evaluation = latest["evaluation"]
    lines.extend(
        (
            f"STATUS    {_status(evaluation.get('overall_status'))}",
            "─" * 72,
            _metric_line("E-01 CITATION", evaluation.get("citation_validity"), "score"),
            _metric_line(
                "E-02 PERSONA",
                evaluation.get("persona_differentiation"),
                "score",
            ),
            _metric_line(
                "E-03 ARBITRATION",
                evaluation.get("arbitration_consistency"),
                "consistent",
            ),
            _metric_line(
                "E-04 P95 LATENCY", evaluation.get("latency"), "p95_latency_ms"
            ),
            _metric_line(
                "E-05 COST", evaluation.get("cost"), "total_cost_microusd"
            ),
            "─" * 72,
            "SEQUENCE  " + " / ".join(_record_summary(record) for record in records),
        )
    )
    return "\n".join(lines)


def _metric_line(label: str, raw_metric: object, value_key: str) -> str:
    if not isinstance(raw_metric, dict):
        raise ValueError("invalid evaluation metric")
    status = _status(raw_metric.get("status"))
    value = raw_metric.get(value_key)
    if value is None:
        display = "NOT MEASURED"
    elif value_key == "score":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("invalid evaluation score")
        score = float(value)
        if not 0 <= score <= 1:
            raise ValueError("invalid evaluation score")
        display = f"{score * 100:.1f}%"
    elif value_key == "consistent":
        if not isinstance(value, bool):
            raise ValueError("invalid arbitration value")
        display = "CONSISTENT" if value else "DRIFT"
    elif value_key == "p95_latency_ms":
        display = f"{_nonnegative(value)} ms"
    else:
        display = f"USD {_nonnegative(value) / 1_000_000:.6f}"
    return f"{label:<22} {status:<14} {display}"


def _record_summary(raw_record: object) -> str:
    if not isinstance(raw_record, dict):
        raise ValueError("invalid evaluation record")
    evaluation = raw_record.get("evaluation")
    if not isinstance(evaluation, dict):
        raise ValueError("invalid evaluation payload")
    return f"#{_positive(raw_record.get('sequence'))} {_status(evaluation.get('overall_status'))}"


def _status(value: object) -> str:
    status = _terminal_text(value).upper()
    if status not in {"PASS", "WARN", "FAIL", "NOT_MEASURED"}:
        raise ValueError("invalid evaluation status")
    return status.replace("_", " ")


def _positive(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("value must be positive")
    return value


def _bounded_positive(value: object) -> int:
    parsed = int(value)
    if parsed < 1 or parsed > 100:
        raise ValueError("value must be between 1 and 100")
    return parsed


def _nonnegative(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("value must be nonnegative")
    return value


def _terminal_text(value: object) -> str:
    safe = "".join(
        character if not unicodedata.category(character).startswith("C") else " "
        for character in str(value)
    )
    return " ".join(safe.split())


def main() -> None:
    run()
