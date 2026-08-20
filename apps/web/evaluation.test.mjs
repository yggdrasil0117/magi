import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { createEvaluationIntent, evaluationHistoryView } from "./evaluation.mjs";

const id = "11111111-1111-4111-8111-111111111111";
const fixtureUrl = new URL(
  "../../tests/fixtures/v1/evaluation-history.json",
  import.meta.url,
);
const fixture = JSON.parse(await readFile(fixtureUrl, "utf8"));

function history(overrides = {}) {
  return { ...structuredClone(fixture), ...overrides };
}

test("evaluation view preserves five authoritative metrics and trend counts", () => {
  const view = evaluationHistoryView(history());
  assert.equal(view.latest.metrics.length, 5);
  assert.equal(view.latest.metrics[0].value, "100%");
  assert.equal(view.latest.metrics[3].value, "1200 ms");
  assert.equal(view.trend.passCount, 1);
});

test("evaluation view rejects identity, digest, and trend drift", () => {
  const identity = history();
  identity.evaluations[0].decision_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
  assert.throws(() => evaluationHistoryView(identity), /identity/);
  const digest = history(); digest.evaluations[0].evaluation_digest = "bad";
  assert.throws(() => evaluationHistoryView(digest), /digest/);
  const trend = history(); trend.trend.fail_count = 1;
  assert.throws(() => evaluationHistoryView(trend), /count/);
});

test("evaluation view labels unavailable operational metrics as not measured", () => {
  const document = history();
  const evaluation = document.evaluations[0].evaluation;
  evaluation.overall_status = "warn";
  evaluation.latency = {
    status: "not_measured", sample_count: 0,
    mean_latency_ms: null, p95_latency_ms: null,
  };
  evaluation.cost = {
    status: "not_measured", input_tokens: 0, output_tokens: 0,
    total_cost_microusd: null, pricing_digest: null,
  };
  document.trend.pass_count = 0;
  document.trend.warn_count = 1;
  document.trend.latest_status = "warn";
  document.trend.mean_p95_latency_ms = null;
  document.trend.mean_cost_microusd = null;

  const view = evaluationHistoryView(document);
  assert.equal(view.latest.metrics[3].value, "未测量");
  assert.equal(view.latest.metrics[4].status, "not_measured");
});

test("evaluation intent sends only the authoritative decision version", () => {
  const intent = createEvaluationIntent(id, 2);
  assert.equal(intent.endpoint, `/api/v1/decisions/${id}/evaluations`);
  assert.deepEqual(intent.body, { version: 2 });
  assert.equal(Object.isFrozen(intent.body), true);
  assert.throws(() => createEvaluationIntent("not-an-id", 1), /target/);
});
