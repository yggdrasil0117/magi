import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { decisionWorkspaceView } from "./workspace.mjs";

const fixture = (name) => new URL(`../../tests/fixtures/v1/${name}`, import.meta.url);
const decisionCase = JSON.parse(await readFile(fixture("decision-case.json"), "utf8"));
const snapshot = JSON.parse(await readFile(fixture("evidence-snapshot.json"), "utf8"));
const ballots = JSON.parse(await readFile(fixture("ballots-round1.json"), "utf8"));

function documentFor(state, overrides = {}) {
  return {
    schema_version: "1.0",
    decision_id: decisionCase.decision_id,
    version: 1,
    state,
    case: decisionCase,
    evidence: snapshot.evidence,
    ballots: [],
    result: null,
    report: null,
    awaiting_confirmation: state === "waiting_for_user",
    awaiting_run: state === "evidence_ready",
    terminal: false,
    available_actions: [],
    ...overrides,
  };
}

test("workspace maps authoritative case, evidence, and actions", () => {
  const view = decisionWorkspaceView(documentFor("waiting_for_user", {
    available_actions: ["confirm", "cancel", "invented"],
  }));
  assert.equal(view.title, "Release decision");
  assert.equal(view.stateCode, "等待用户");
  assert.deepEqual(view.options.map((item) => item.id), ["release", "delay", "limited"]);
  assert.equal(view.evidence[0].id, "E-001");
  assert.deepEqual(view.actions, ["confirm", "cancel"]);
});

test("workspace suppresses ballots before disclosure even if upstream is malformed", () => {
  const first = decisionWorkspaceView(documentFor("first_ballot", { ballots }));
  assert.deepEqual(first.ballots, []);

  const review = decisionWorkspaceView(documentFor("cross_review", { ballots }));
  assert.equal(review.ballots.length, 3);
  assert.equal(review.preliminary, true);
});

test("workspace rejects unknown schema, state, and missing fields", () => {
  assert.throws(() => decisionWorkspaceView({}), /missing schema_version/);
  assert.throws(() => decisionWorkspaceView(documentFor("created", { schema_version: "2.0" })), /Unsupported/);
  assert.throws(() => decisionWorkspaceView(documentFor("private_state")), /Unsupported decision state/);
});

test("workspace strips controls from client-visible strings", () => {
  const altered = structuredClone(decisionCase);
  altered.title = "Release\n\u001b[31msecret";
  const view = decisionWorkspaceView(documentFor("created", { case: altered }));
  assert.equal(view.title, "Release [31msecret");
});
