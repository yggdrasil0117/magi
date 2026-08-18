import assert from "node:assert/strict";
import test from "node:test";

import { createAsyncIntent, operationView } from "./operations.mjs";

const receipt = {
  schema_version: "1.0",
  operation_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  kind: "run_decision",
  status: "running",
  stage: "first_ballot",
  decision_id: "11111111-1111-4111-8111-111111111111",
  decision_version: 3,
  last_event_sequence: 2,
  next_poll_after_ms: 1000,
  result_available: false,
  failure_code: null,
};

test("operation receipt maps only public lifecycle fields", () => {
  const view = operationView({ ...receipt, private_prompt: "do not expose" });
  assert.equal(view.stage, "first_ballot");
  assert.equal(view.sequence, 2);
  assert.equal("private_prompt" in view, false);
});

test("async create intent freezes sanitized request and key", () => {
  const intent = createAsyncIntent("create", {
    rawQuestion: "Deploy?\n\u001b[31m",
    risk: "medium",
    classification: "sensitive",
  }, { uuid: "create-0001" });
  assert.equal(intent.endpoint, "/api/v1/decisions");
  assert.equal(intent.idempotencyKey, "web-create-create-0001");
  assert.equal(intent.body.raw_question, "Deploy? [31m");
  assert.equal(Object.isFrozen(intent.body), true);
});

test("async run requires an authoritative available action", () => {
  const view = { decisionId: receipt.decision_id, version: 3, actions: ["run"] };
  const intent = createAsyncIntent("run", view, { uuid: "run-0001" });
  assert.equal(intent.endpoint, `/api/v1/decisions/${receipt.decision_id}/run`);
  assert.deepEqual(intent.body, { version: 3 });
  assert.throws(
    () => createAsyncIntent("run", { ...view, actions: [] }, { uuid: "run-2" }),
    /not available/,
  );
});

test("operation receipt rejects unknown private lifecycle values", () => {
  assert.throws(() => operationView({ ...receipt, stage: "model_secret_retry" }), /lifecycle/);
  assert.throws(() => operationView({ ...receipt, schema_version: "2.0" }), /Unsupported/);
});
