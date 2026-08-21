import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

globalThis.window = {};
globalThis.localStorage = {
  getItem(key) { return key === "magi.language" ? "en" : null; },
  setItem() {},
};

const { decisionWorkspaceView } = await import("./workspace.mjs");
const fixtureUrl = new URL("../../tests/fixtures/v1/decision-case.json", import.meta.url);
const decisionCase = JSON.parse(await readFile(fixtureUrl, "utf8"));

test("English preference localizes dynamic workspace labels", () => {
  const view = decisionWorkspaceView({
    schema_version: "1.0",
    decision_id: decisionCase.decision_id,
    version: 1,
    state: "waiting_for_user",
    case: decisionCase,
    evidence: [],
    ballots: [],
    result: null,
    report: null,
    awaiting_confirmation: true,
    awaiting_run: false,
    terminal: false,
    available_actions: ["confirm"],
  });

  assert.equal(view.stateCode, "WAITING FOR USER");
  assert.equal(view.risk, "LOW");
  assert.equal(view.classification, "INTERNAL");
});
