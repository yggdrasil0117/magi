"""Contract tests for durable asynchronous operation projections."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from uuid import UUID

from pydantic import ValidationError

from magi.application import (
    OperationEvent,
    OperationEventPage,
    OperationEventType,
    OperationKind,
    OperationReceipt,
    OperationStage,
    OperationStatus,
    validate_operation_transition,
)


OPERATION_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
DECISION_ID = UUID("11111111-1111-4111-8111-111111111111")
NOW = datetime(2026, 8, 18, 10, 0, tzinfo=timezone.utc)


def receipt(**updates: object) -> OperationReceipt:
    values: dict[str, object] = {
        "operation_id": OPERATION_ID,
        "kind": OperationKind.RUN_DECISION,
        "status": OperationStatus.ACCEPTED,
        "stage": OperationStage.QUEUED,
        "decision_id": DECISION_ID,
        "decision_version": 1,
        "created_at": NOW,
        "updated_at": NOW,
        "last_event_sequence": 1,
        "next_poll_after_ms": 1000,
    }
    values.update(updates)
    return OperationReceipt(**values)


def event(sequence: int, **updates: object) -> OperationEvent:
    values: dict[str, object] = {
        "operation_id": OPERATION_ID,
        "sequence": sequence,
        "event_type": OperationEventType.ACCEPTED,
        "status": OperationStatus.ACCEPTED,
        "stage": OperationStage.QUEUED,
        "occurred_at": NOW,
        "message_code": "operation_accepted",
    }
    values.update(updates)
    return OperationEvent(**values)


class OperationContractTests(unittest.TestCase):
    def test_active_receipt_has_polling_hint_and_no_result(self) -> None:
        value = receipt()

        self.assertEqual(value.status, OperationStatus.ACCEPTED)
        self.assertEqual(value.next_poll_after_ms, 1000)
        self.assertFalse(value.result_available)
        self.assertIsNone(value.completed_at)

    def test_success_receipt_requires_complete_result(self) -> None:
        completed = receipt(
            status=OperationStatus.SUCCEEDED,
            stage=OperationStage.COMPLETE,
            updated_at=NOW + timedelta(seconds=5),
            completed_at=NOW + timedelta(seconds=5),
            next_poll_after_ms=None,
            result_available=True,
            last_event_sequence=4,
        )
        self.assertTrue(completed.result_available)

        with self.assertRaisesRegex(ValidationError, "require a result"):
            receipt(
                status=OperationStatus.SUCCEEDED,
                stage=OperationStage.COMPLETE,
                completed_at=NOW,
                next_poll_after_ms=None,
            )

    def test_failed_receipt_exposes_only_stable_failure_code(self) -> None:
        failed = receipt(
            status=OperationStatus.FAILED,
            updated_at=NOW + timedelta(seconds=2),
            completed_at=NOW + timedelta(seconds=2),
            next_poll_after_ms=None,
            failure_code="provider_unavailable",
            last_event_sequence=3,
        )
        self.assertEqual(failed.failure_code, "provider_unavailable")

        with self.assertRaisesRegex(ValidationError, "failure code"):
            receipt(
                status=OperationStatus.FAILED,
                completed_at=NOW,
                next_poll_after_ms=None,
            )

    def test_event_page_requires_identity_order_and_exact_cursor(self) -> None:
        first = event(
            2,
            event_type=OperationEventType.STARTED,
            status=OperationStatus.RUNNING,
            message_code="operation_started",
        )
        second = event(
            3,
            event_type=OperationEventType.STAGE_CHANGED,
            status=OperationStatus.RUNNING,
            stage=OperationStage.FIRST_BALLOT,
            message_code="first_ballot_started",
        )
        page = OperationEventPage(
            operation_id=OPERATION_ID,
            after_sequence=1,
            events=(first, second),
            next_after_sequence=3,
        )
        self.assertEqual(page.next_after_sequence, 3)

        with self.assertRaisesRegex(ValidationError, "strictly ordered"):
            OperationEventPage(
                operation_id=OPERATION_ID,
                after_sequence=1,
                events=(second, first),
                next_after_sequence=2,
            )

    def test_event_status_and_transition_rules_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValidationError, "does not match"):
            event(1, event_type=OperationEventType.SUCCEEDED, status=OperationStatus.RUNNING)

        validate_operation_transition(OperationStatus.ACCEPTED, OperationStatus.RUNNING)
        validate_operation_transition(OperationStatus.RUNNING, OperationStatus.RUNNING)
        validate_operation_transition(OperationStatus.RUNNING, OperationStatus.SUCCEEDED)
        with self.assertRaisesRegex(ValueError, "illegal operation transition"):
            validate_operation_transition(OperationStatus.SUCCEEDED, OperationStatus.RUNNING)


if __name__ == "__main__":
    unittest.main()
