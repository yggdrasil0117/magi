import assert from "node:assert/strict";
import test from "node:test";

import { auditTrailView, createRedactionIntent } from "./audit.mjs";

const id = "11111111-1111-4111-8111-111111111111";
const recordId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const hash = "a".repeat(64);

function trail(overrides = {}) {
  return {
    schema_version: "1.0",
    decision_id: id,
    decision_version: 1,
    integrity_status: "verified",
    record_count: 1,
    records: [{
      schema_version: "1.0", record_id: recordId, decision_id: id,
      decision_version: 1, sequence: 1, kind: "decision_state",
      classification: "internal", payload: { phase: "completed" },
      payload_hash: hash, previous_hash: "0".repeat(64), record_hash: hash,
      occurred_at: "2026-08-19T09:00:00Z", redacted_fields: [],
    }],
    ...overrides,
  };
}

test("audit view requires a verified contiguous hash-shaped trail", () => {
  const view = auditTrailView(trail());
  assert.equal(view.integrity, "VERIFIED");
  assert.equal(view.records[0].phase, "completed");
  assert.throws(() => auditTrailView(trail({ integrity_status: "failed" })), /integrity/);
  const broken = trail();
  broken.records[0].sequence = 2;
  assert.throws(() => auditTrailView(broken), /sequence/);
});

test("redaction intent freezes one safe command body and key", () => {
  const intent = createRedactionIntent(id, 1, {
    targetRecordId: recordId,
    fieldPath: "/case/raw_question",
    reason: "Privacy request.",
  });
  assert.equal(intent.body.version, 1);
  assert.deepEqual(intent.body.field_paths, ["/case/raw_question"]);
  assert.ok(intent.key.length >= 8);
  assert.throws(
    () => createRedactionIntent(id, 1, {
      targetRecordId: recordId, fieldPath: "case/raw_question", reason: "No.",
    }),
    /path/,
  );
});
