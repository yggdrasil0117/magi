"""Keyboard-first, no-dependency terminal workflow shell."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID

from .workflow_cli import request_json


def run(input_fn: Callable[[str], str] = input, output_fn: Callable[[str], None] = print) -> None:
    output_fn("MAGI TERMINAL / inbox, get, history, create, confirm, run, cancel, watch, quit")
    while True:
        parts = input_fn("magi> ").strip().split()
        if not parts:
            continue
        if parts[0] in {"quit", "exit"}:
            return
        try:
            identity_commands = {"get", "history", "confirm", "run", "cancel", "watch"}
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
            else:
                output_fn("Unknown command or arguments.")
                continue
            output_fn(json.dumps(payload, ensure_ascii=False, indent=2))
        except Exception:
            output_fn("Request failed. Credentials and server details were not displayed.")


def main() -> None:
    run()
