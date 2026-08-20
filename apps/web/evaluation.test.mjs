import assert from "node:assert/strict";
import test from "node:test";

import { createEvaluationIntent, evaluationHistoryView } from "./evaluation.mjs";

const id = "11111111-1111-4111-8111-111111111111";
const evaluationId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const hash = "a".repeat(64);

function metric(status, score = 1) { return { status, score }; }

function history(overrides = {}) {
  const record = {
    schema_version: "1.0", evaluation_id: evaluationId,
    decision_id: id, decision_version: 1, sequence: 1,
    evaluation_digest: hash, created_at: "2026-08-20T08:00:00Z",
    evaluation: {
      schema_version: "1.0", evaluator_version: "1.0", decision_id: id, version: 1,
      overall_status: "pass", evaluated_at: "2026-08-20T07:00:00Z",
      citation_validity: { ...metric("pass"), reference_count: 3, valid_reference_count: 3 },
      persona_differentiation: { ...metric("pass"), pair_count: 3, minimum_pair_distance: 0.8 },
      arbitration_consistency: { ...metric("pass"), consistent: true, mismatch_fields: [], rule_version: "1.0" },
      latency: { ...metric("pass", null), sample_count: 3, mean_latency_ms: 900, p95_latency_ms: 1100 },
      cost: { ...metric("pass", null), input_tokens: 300, output_tokens: 120, total_cost_microusd: 450, pricing_digest: hash },
    },
  };
  return {
    schema_version: "1.0", decision_id: id, decision_version: 1,
    total_count: 1, evaluations: [record],
    trend: {
      schema_version: "1.0", sample_count: 1,
      pass_count: 1, warn_count: 0, fail_count: 0, latest_status: "pass",
      mean_citation_score: 1, mean_persona_score: 1,
      mean_p95_latency_ms: 1100, mean_cost_microusd: 450,
    },
    ...overrides,
  };
}

test("evaluation view preserves five authoritative metrics and trend counts", () => {
  const view = evaluationHistoryView(history());
  assert.equal(view.latest.metrics.length, 5);
  assert.equal(view.latest.metrics[0].value, "100%");
  assert.equal(view.latest.metrics[3].value, "1100 ms");
  assert.equal(view.trend.passCount, 1);
});

test("evaluation view rejects identity, digest, and trend drift", () => {
  const identity = history(); identity.evaluations[0].decision_id = evaluationId;
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
