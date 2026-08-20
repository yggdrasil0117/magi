"""Offline JSON evaluation command for local and CI acceptance gates."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from magi.domain import ProtocolViolation
from magi.evaluation import DecisionEvaluator, EvaluationBundle, MetricStatus

EXIT_OK = 0
EXIT_THRESHOLD = 1
EXIT_INVALID_INPUT = 2
MAX_INPUT_BYTES = 5_000_000


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="magi-eval")
    parser.add_argument("bundle", type=Path, help="versioned evaluation bundle JSON")
    parser.add_argument(
        "--fail-on-threshold",
        action="store_true",
        help="return exit code 1 when any measured metric fails",
    )
    return parser


def evaluate_path(path: Path) -> dict[str, object]:
    with path.open("rb") as source:
        raw = source.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError("evaluation bundle exceeds the size limit")
    payload = json.loads(raw.decode("utf-8"))
    bundle = EvaluationBundle.model_validate(payload)
    return DecisionEvaluator().evaluate(bundle).model_dump(mode="json")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = evaluate_path(args.bundle)
    except (OSError, ValueError, json.JSONDecodeError, ValidationError, ProtocolViolation):
        return EXIT_INVALID_INPUT
    sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
    if args.fail_on_threshold and result["overall_status"] == MetricStatus.FAIL.value:
        return EXIT_THRESHOLD
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
