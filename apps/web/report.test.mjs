import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { reportView, safeText } from "./report.mjs";

const fixtureUrl = new URL("../../tests/fixtures/v1/decision-report-majority.json", import.meta.url);
const report = JSON.parse(await readFile(fixtureUrl, "utf8"));

test("web view preserves majority, dissent, and review audit", () => {
  const view = reportView(report);

  assert.equal(view.identity, "11111111-1111-4111-8111-111111111111 · v1");
  assert.equal(view.status, "多数通过");
  assert.equal(view.selected, "Release [release]");
  assert.deepEqual(view.votes, ["delay: 1", "limited: 0", "release: 2"]);
  assert.equal(view.minority[0], "balthasar · 支持 · delay");
  assert.equal(view.minority[1], "balthasar rationale");
  assert.equal(view.audit.length, 3);
  assert.equal(view.audit[0].agent, "balthasar");
});

test("web contract rejects missing fields and strips control text", () => {
  assert.throws(() => reportView({}), /missing decision_id/);
  assert.equal(safeText("line one\n\u001b[31mline two"), "line one [31mline two");
});
