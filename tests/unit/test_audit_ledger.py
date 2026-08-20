"""Append-only audit integrity, redaction, and reconstruction tests."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from uuid import UUID

from magi.arbitration import DeterministicArbiter
from magi.audit import (
    AuditChainViolation,
    AuditRedaction,
    AuditRedactionConflict,
    AuditTrailNotFound,
    DecisionAuditService,
    InMemoryAuditLedger,
)
from magi.domain import AgentName
from tests.fixtures.factories import make_ballot, make_case, make_snapshot


AUDIT_TIME = datetime(2026, 8, 19, 9, 0, tzinfo=timezone.utc)


def completed_state() -> dict[str, object]:
    case = make_case(confirmed=True)
    snapshot = make_snapshot(case)
    ballots = tuple(make_ballot(case, agent, "release") for agent in AgentName)
    result = DeterministicArbiter().arbitrate(case, snapshot, ballots)
    return {
        "case": case.model_dump(mode="json"),
        "snapshot": snapshot.model_dump(mode="json"),
        "constraint_validations": [],
        "first_ballots": [ballot.model_dump(mode="json") for ballot in ballots],
        "review_ballots": [],
        "result": result.model_dump(mode="json"),
        "phase": "completed",
    }


class DecisionAuditServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_record_hash_is_stable_across_timezone_normalization(self) -> None:
        ledger = InMemoryAuditLedger()
        service = DecisionAuditService(ledger)
        china_time = datetime(
            2026,
            8,
            20,
            16,
            30,
            tzinfo=timezone(timedelta(hours=8)),
        )

        captured = await service.capture(completed_state(), occurred_at=china_time)
        normalized = captured.model_copy(
            update={"occurred_at": china_time.astimezone(timezone.utc)}
        )

        self.assertEqual(captured.record_hash, normalized.record_hash)
        type(captured).model_validate(normalized.model_dump())

    async def test_missing_trail_is_not_reported_as_verified_empty_history(self) -> None:
        service = DecisionAuditService(InMemoryAuditLedger())
        with self.assertRaises(AuditTrailNotFound):
            await service.trail(
                UUID("11111111-1111-4111-8111-111111111111"), 1
            )

    async def test_capture_is_idempotent_and_builds_a_hash_chain(self) -> None:
        ledger = InMemoryAuditLedger()
        service = DecisionAuditService(ledger)
        state = completed_state()

        first = await service.capture(state, occurred_at=AUDIT_TIME)
        repeated = await service.capture(
            state, occurred_at=AUDIT_TIME + timedelta(seconds=1)
        )
        changed = dict(state)
        changed["phase"] = "archived"
        second = await service.capture(
            changed, occurred_at=AUDIT_TIME + timedelta(seconds=2)
        )

        self.assertEqual(first, repeated)
        self.assertEqual(second.sequence, 2)
        self.assertEqual(second.previous_hash, first.record_hash)
        self.assertNotEqual(second.record_hash, first.record_hash)

    async def test_report_is_reconstructed_without_checkpoint_or_stored_report(self) -> None:
        ledger = InMemoryAuditLedger()
        service = DecisionAuditService(ledger)
        state = completed_state()

        await service.capture(state, occurred_at=AUDIT_TIME)
        report = await service.reconstruct_report(
            UUID(state["case"]["decision_id"]), state["case"]["version"]
        )

        self.assertEqual(report.selected_option, "release")
        self.assertEqual(report.ballot_count, 3)
        self.assertEqual(report.vote_count["release"], 3)

    async def test_redaction_is_an_overlay_and_preserves_canonical_reconstruction(self) -> None:
        ledger = InMemoryAuditLedger()
        service = DecisionAuditService(ledger)
        state = completed_state()
        captured = await service.capture(state, occurred_at=AUDIT_TIME)

        redaction = await service.redact(
            captured.decision_id,
            captured.decision_version,
            AuditRedaction(
                target_record_id=captured.record_id,
                field_paths=("/case/raw_question",),
                reason="Remove question text from operator-visible audit export.",
                actor="privacy-officer",
            ),
            occurred_at=AUDIT_TIME + timedelta(seconds=1),
        )
        visible = await service.visible_records(
            captured.decision_id, captured.decision_version
        )
        trail = await service.trail(
            captured.decision_id, captured.decision_version
        )
        report = await service.reconstruct_report(
            captured.decision_id, captured.decision_version
        )

        self.assertEqual(redaction.kind, "redaction")
        self.assertEqual(visible[0]["payload"]["case"]["raw_question"], "[REDACTED]")
        self.assertEqual(visible[0]["redacted_fields"], ["/case/raw_question"])
        self.assertEqual(trail.record_count, 2)
        self.assertEqual(trail.records[0].redacted_fields, ("/case/raw_question",))
        canonical = await ledger.records(captured.decision_id, captured.decision_version)
        self.assertEqual(
            canonical[0].payload["case"]["raw_question"],
            "Should we release?",
        )
        self.assertEqual(report.selected_option, "release")

    async def test_tampered_record_fails_before_reconstruction(self) -> None:
        ledger = InMemoryAuditLedger()
        service = DecisionAuditService(ledger)
        captured = await service.capture(completed_state(), occurred_at=AUDIT_TIME)
        key = (captured.decision_id, captured.decision_version)
        ledger._records[key][0] = captured.model_copy(
            update={"payload": {**captured.payload, "phase": "tampered"}}
        )

        with self.assertRaises(AuditChainViolation):
            await service.reconstruct_report(*key)

    async def test_invalid_redaction_target_or_path_is_rejected(self) -> None:
        ledger = InMemoryAuditLedger()
        service = DecisionAuditService(ledger)
        captured = await service.capture(completed_state(), occurred_at=AUDIT_TIME)
        await service.redact(
            captured.decision_id,
            captured.decision_version,
            AuditRedaction(
                target_record_id=captured.record_id,
                field_paths=("/case/not_present",),
                reason="Test invalid overlay.",
                actor="privacy-officer",
            ),
            occurred_at=AUDIT_TIME + timedelta(seconds=1),
        )

        with self.assertRaisesRegex(AuditChainViolation, "path"):
            await service.visible_records(
                captured.decision_id, captured.decision_version
            )

    async def test_redaction_command_identity_cannot_be_reused_differently(self) -> None:
        ledger = InMemoryAuditLedger()
        service = DecisionAuditService(ledger)
        captured = await service.capture(completed_state(), occurred_at=AUDIT_TIME)
        command_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
        original = AuditRedaction(
            target_record_id=captured.record_id,
            field_paths=("/case/raw_question",),
            reason="Privacy request.",
            actor="privacy-officer",
            command_id=command_id,
        )
        await service.redact(
            captured.decision_id,
            captured.decision_version,
            original,
            occurred_at=AUDIT_TIME + timedelta(seconds=1),
        )

        with self.assertRaises(AuditRedactionConflict):
            await service.redact(
                captured.decision_id,
                captured.decision_version,
                original.model_copy(update={"reason": "Changed request."}),
                occurred_at=AUDIT_TIME + timedelta(seconds=2),
            )


if __name__ == "__main__":
    unittest.main()
