"""Scriptable MAGI workflow client using only public HTTP contracts."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlsplit
from uuid import UUID, uuid4


EXIT_OK = 0
EXIT_USAGE = 2
EXIT_AUTH = 3
EXIT_CONFLICT = 4
EXIT_TRANSPORT = 5


def request_json(
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    async_preference: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    base = os.environ.get("MAGI_API_URL", "http://127.0.0.1:8000").rstrip("/")
    parsed = urlsplit(base)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError("MAGI_API_URL is invalid")
    token = os.environ.get("MAGI_API_TOKEN", "")
    if not token:
        raise RuntimeError("MAGI_API_TOKEN is required")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers.update({
            "Content-Type": "application/json",
            "Idempotency-Key": idempotency_key
            or os.environ.get("MAGI_IDEMPOTENCY_KEY")
            or f"cli-{uuid4()}",
        })
    if async_preference:
        headers["Prefer"] = "respond-async"
    request = Request(base + path, data=data, headers=headers, method=method)
    with urlopen(request, timeout=30) as response:
        if int(response.headers.get("Content-Length", "0") or 0) > 1_000_000:
            raise RuntimeError("API response exceeds limit")
        payload = response.read(1_000_001)
        if len(payload) > 1_000_000:
            raise RuntimeError("API response exceeds limit")
        return json.loads(payload)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="magi")
    sub = parser.add_subparsers(dest="command", required=True)
    inbox = sub.add_parser("inbox")
    inbox.add_argument("--limit", type=_bounded_positive, default=50)
    get = sub.add_parser("get")
    get.add_argument("decision_id", type=UUID)
    get.add_argument("--version", type=_bounded_positive, default=1)
    history = sub.add_parser("history")
    history.add_argument("decision_id", type=UUID)
    audit = sub.add_parser("audit")
    audit.add_argument("decision_id", type=UUID)
    audit.add_argument("--version", type=_bounded_positive, default=1)
    create = sub.add_parser("create")
    create.add_argument("question")
    create.add_argument("--risk", choices=("low", "medium", "high", "critical"), default="low")
    create.add_argument(
        "--classification",
        choices=("public", "internal", "sensitive", "restricted"),
        default="internal",
    )
    create.add_argument("--idempotency-key")
    run = sub.add_parser("run")
    run.add_argument("decision_id", type=UUID)
    run.add_argument("--version", type=_bounded_positive, default=1)
    run.add_argument("--idempotency-key")
    watch = sub.add_parser("watch")
    watch.add_argument("operation_id", type=UUID)
    confirm = sub.add_parser("confirm")
    confirm.add_argument("decision_id", type=UUID)
    confirm.add_argument("--version", type=_bounded_positive, default=1)
    confirm.add_argument("--at", required=True)
    confirm.add_argument("--idempotency-key")
    cancel = sub.add_parser("cancel")
    cancel.add_argument("decision_id", type=UUID)
    cancel.add_argument("--version", type=_bounded_positive, default=1)
    cancel.add_argument("--reason")
    cancel.add_argument("--idempotency-key")
    redact = sub.add_parser("redact")
    redact.add_argument("decision_id", type=UUID)
    redact.add_argument("target_record_id", type=UUID)
    redact.add_argument("field_path")
    redact.add_argument("--reason", required=True)
    redact.add_argument("--version", type=_bounded_positive, default=1)
    redact.add_argument("--idempotency-key")
    return parser


def execute(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "inbox":
        return request_json("GET", f"/v1/decisions?limit={args.limit}")
    if args.command == "get":
        return request_json("GET", f"/v1/decisions/{args.decision_id}?version={args.version}")
    if args.command == "history":
        return request_json("GET", f"/v1/decisions/{args.decision_id}/versions")
    if args.command == "audit":
        return request_json(
            "GET", f"/v1/decisions/{args.decision_id}/audit?version={args.version}"
        )
    if args.command == "create":
        return request_json("POST", "/v1/decisions", body={
            "raw_question": args.question,
            "minimum_risk_level": args.risk,
            "data_classification": args.classification,
            "evidence": [],
        }, async_preference=True, idempotency_key=args.idempotency_key)
    if args.command == "run":
        return request_json(
            "POST", f"/v1/decisions/{args.decision_id}/run",
            body={"version": args.version}, async_preference=True,
            idempotency_key=args.idempotency_key,
        )
    if args.command == "confirm":
        return request_json(
            "POST", f"/v1/decisions/{args.decision_id}/confirm",
            body={"version": args.version, "confirmed_at": args.at},
            idempotency_key=args.idempotency_key,
        )
    if args.command == "cancel":
        return request_json(
            "POST", f"/v1/decisions/{args.decision_id}/cancel",
            body={"version": args.version, "reason": args.reason},
            idempotency_key=args.idempotency_key,
        )
    if args.command == "redact":
        return request_json(
            "POST", f"/v1/decisions/{args.decision_id}/audit/redactions",
            body={
                "version": args.version,
                "target_record_id": str(args.target_record_id),
                "field_paths": [args.field_path],
                "reason": args.reason,
            },
            idempotency_key=args.idempotency_key,
        )
    return request_json("GET", f"/v1/operations/{args.operation_id}")


def _bounded_positive(value: str) -> int:
    parsed = int(value)
    if parsed < 1 or parsed > 100:
        raise argparse.ArgumentTypeError("value must be between 1 and 100")
    return parsed


def main(argv: list[str] | None = None) -> int:
    try:
        payload = execute(build_parser().parse_args(argv))
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        return EXIT_OK
    except HTTPError as exc:
        if exc.code in {401, 403}:
            return EXIT_AUTH
        if exc.code == 409:
            return EXIT_CONFLICT
        return EXIT_TRANSPORT
    except (URLError, OSError, RuntimeError, ValueError, json.JSONDecodeError):
        return EXIT_TRANSPORT


if __name__ == "__main__":
    raise SystemExit(main())
