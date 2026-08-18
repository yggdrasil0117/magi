import assert from "node:assert/strict";
import test from "node:test";

import { commandPresentation, createCommandIntent } from "./commands.mjs";

const view = {
  decisionId: "11111111-1111-4111-8111-111111111111",
  version: 3,
  actions: ["confirm", "cancel"],
};

test("confirm intent freezes one timestamp and idempotency key for safe retry", () => {
  const now = new Date("2026-08-18T10:00:00.000Z");
  const intent = createCommandIntent("confirm", view, { now, uuid: "11111111-2222-4333-8444-555555555555" });
  assert.equal(intent.endpoint, "/api/v1/decisions/11111111-1111-4111-8111-111111111111/confirm");
  assert.equal(intent.body.confirmed_at, "2026-08-18T10:00:00.000Z");
  assert.equal(intent.body.version, 3);
  assert.equal(intent.idempotencyKey, "web-confirm-11111111-2222-4333-8444-555555555555");
  assert.equal(Object.isFrozen(intent.body), true);
});

test("cancel intent sanitizes and freezes its optional reason", () => {
  const intent = createCommandIntent("cancel", view, { reason: "Pause\n\u001b[31mnow", uuid: "cancel-0001" });
  assert.deepEqual(intent.body, { version: 3, reason: "Pause [31mnow" });
  assert.match(commandPresentation("cancel").consequence, /不会删除/);
});

test("client refuses unavailable and unsupported mutations", () => {
  assert.throws(() => createCommandIntent("run", view, { uuid: "run-0001" }), /Unsupported/);
  assert.throws(() => createCommandIntent("confirm", { ...view, actions: [] }, { uuid: "confirm-1" }), /not available/);
  assert.throws(() => commandPresentation("create"), /Unsupported/);
});
