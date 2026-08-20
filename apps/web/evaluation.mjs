import { safeText } from "./report.mjs";

const HASH = /^[a-f0-9]{64}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const METRIC_STATUS = new Set(["pass", "warn", "fail", "not_measured"]);
const OVERALL_STATUS = new Set(["pass", "warn", "fail"]);

export function evaluationHistoryView(document) {
  if (!document || document.schema_version !== "1.0") {
    throw new Error("Unsupported evaluation history schema.");
  }
  if (!UUID.test(document.decision_id || "") || !positiveInteger(document.decision_version)) {
    throw new Error("Invalid evaluation history identity.");
  }
  if (!Array.isArray(document.evaluations) || !nonnegativeInteger(document.total_count)) {
    throw new Error("Invalid evaluation history collection.");
  }
  if (document.total_count < document.evaluations.length) {
    throw new Error("Invalid evaluation history total.");
  }
  let previous = 0;
  const records = document.evaluations.map((record) => {
    const view = evaluationRecordView(record, document.decision_id, document.decision_version);
    if (view.sequence <= previous) throw new Error("Invalid evaluation history order.");
    previous = view.sequence;
    return view;
  });
  const trend = trendView(document.trend, records);
  return {
    decisionId: safeText(document.decision_id),
    version: Number(document.decision_version),
    totalCount: Number(document.total_count),
    records,
    latest: records.at(-1) || null,
    trend,
  };
}

export function evaluationRecordView(record, decisionId = record?.decision_id, version = record?.decision_version) {
  if (!record || record.schema_version !== "1.0" || !UUID.test(record.evaluation_id || "")) {
    throw new Error("Invalid evaluation record envelope.");
  }
  if (record.decision_id !== decisionId || Number(record.decision_version) !== Number(version)) {
    throw new Error("Evaluation record identity mismatch.");
  }
  if (!positiveInteger(record.sequence) || !HASH.test(record.evaluation_digest || "")) {
    throw new Error("Invalid evaluation record sequence or digest.");
  }
  const evaluation = record.evaluation;
  if (!evaluation || evaluation.schema_version !== "1.0" || evaluation.evaluator_version !== "1.0") {
    throw new Error("Unsupported evaluation schema.");
  }
  if (evaluation.decision_id !== decisionId || Number(evaluation.version) !== Number(version)) {
    throw new Error("Evaluation payload identity mismatch.");
  }
  if (!OVERALL_STATUS.has(evaluation.overall_status)) {
    throw new Error("Invalid evaluation overall status.");
  }
  const metrics = [
    scoreMetric("citation", "引用有效性", evaluation.citation_validity),
    scoreMetric("persona", "人格差异度", evaluation.persona_differentiation),
    arbitrationMetric(evaluation.arbitration_consistency),
    latencyMetric(evaluation.latency),
    costMetric(evaluation.cost),
  ];
  return {
    id: safeText(record.evaluation_id),
    sequence: Number(record.sequence),
    digest: safeText(record.evaluation_digest),
    createdAt: safeText(record.created_at),
    evaluatedAt: safeText(evaluation.evaluated_at),
    overall: evaluation.overall_status,
    metrics,
  };
}

function scoreMetric(key, label, metric) {
  const status = metricStatus(metric);
  const score = optionalScore(metric.score);
  return {
    key, label, status, score,
    value: score === null ? "未测量" : `${Math.round(score * 1000) / 10}%`,
    detail: key === "citation"
      ? `${number(metric.valid_reference_count)} / ${number(metric.reference_count)} REFERENCES`
      : `${number(metric.pair_count)} PAIRS · MIN ${formatScore(metric.minimum_pair_distance)}`,
  };
}

function arbitrationMetric(metric) {
  const status = metricStatus(metric);
  if (typeof metric.consistent !== "boolean") throw new Error("Invalid arbitration metric.");
  return {
    key: "arbitration", label: "裁决一致性", status,
    score: metric.consistent ? 1 : 0,
    value: metric.consistent ? "一致" : "发生漂移",
    detail: metric.consistent
      ? `RULE ${safeText(metric.rule_version)}`
      : `MISMATCH ${cleanList(metric.mismatch_fields).join(" / ") || "UNKNOWN"}`,
  };
}

function latencyMetric(metric) {
  const status = metricStatus(metric);
  const p95 = optionalNonnegative(metric.p95_latency_ms);
  return {
    key: "latency", label: "P95 延迟", status, score: null,
    value: p95 === null ? "未测量" : `${p95} ms`,
    detail: `${number(metric.sample_count)} SAMPLES · MEAN ${formatUnit(metric.mean_latency_ms, "ms")}`,
  };
}

function costMetric(metric) {
  const status = metricStatus(metric);
  const cost = optionalNonnegative(metric.total_cost_microusd);
  if (metric.pricing_digest !== null && metric.pricing_digest !== undefined
      && !HASH.test(metric.pricing_digest)) throw new Error("Invalid pricing digest.");
  return {
    key: "cost", label: "模型成本", status, score: null,
    value: cost === null ? "未测量" : `USD ${(cost / 1_000_000).toFixed(6)}`,
    detail: `${number(metric.input_tokens)} IN / ${number(metric.output_tokens)} OUT TOKENS`,
  };
}

function trendView(trend, records) {
  if (!trend || trend.schema_version !== "1.0") throw new Error("Invalid evaluation trend.");
  for (const key of ["sample_count", "pass_count", "warn_count", "fail_count"]) {
    if (!nonnegativeInteger(trend[key])) throw new Error("Invalid evaluation trend counts.");
  }
  if (trend.sample_count !== records.length
      || trend.pass_count + trend.warn_count + trend.fail_count !== trend.sample_count) {
    throw new Error("Evaluation trend count mismatch.");
  }
  const expectedLatest = records.at(-1)?.overall || null;
  if (trend.latest_status !== expectedLatest) throw new Error("Evaluation trend latest mismatch.");
  return {
    sampleCount: Number(trend.sample_count),
    passCount: Number(trend.pass_count),
    warnCount: Number(trend.warn_count),
    failCount: Number(trend.fail_count),
    latestStatus: trend.latest_status,
    citation: optionalScore(trend.mean_citation_score),
    persona: optionalScore(trend.mean_persona_score),
    latency: optionalNonnegative(trend.mean_p95_latency_ms),
    cost: optionalNonnegative(trend.mean_cost_microusd),
  };
}

export async function fetchEvaluationHistory(decisionId, version, token, signal, limit = 20) {
  const endpoint = `/api/v1/decisions/${encodeURIComponent(decisionId)}/evaluations`
    + `?version=${encodeURIComponent(version)}&limit=${encodeURIComponent(limit)}`;
  const response = await fetch(endpoint, {
    headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
    cache: "no-store", credentials: "omit", signal,
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) throw apiError(payload, response.status, "Evaluation history request failed");
  return evaluationHistoryView(payload);
}

export function createEvaluationIntent(decisionId, version) {
  if (!UUID.test(decisionId || "") || !positiveInteger(Number(version))) {
    throw new Error("Invalid evaluation target.");
  }
  return Object.freeze({
    endpoint: `/api/v1/decisions/${encodeURIComponent(decisionId)}/evaluations`,
    body: Object.freeze({ version: Number(version) }),
  });
}

export async function submitEvaluation(intent, token, signal) {
  const response = await fetch(intent.endpoint, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(intent.body), cache: "no-store", credentials: "omit", signal,
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) throw apiError(payload, response.status, "Evaluation run failed");
  return evaluationRecordView(payload);
}

export function renderEvaluationHistory(root, history, { canRun = false } = {}) {
  root.replaceChildren();
  const heading = element("div", "evaluation-heading");
  heading.append(
    element("span", "", "QUALITY EVALUATION / 07"),
    element("strong", `status-${history.latest?.overall || "empty"}`,
      history.latest ? `${statusLabel(history.latest.overall)} · ${history.totalCount} RECORDS` : "NO RECORDS"),
    runButton(canRun),
  );
  root.append(heading);
  if (!history.latest) {
    root.append(element("p", "evaluation-empty", canRun
      ? "当前版本尚无评估记录。可运行一次服务端权威评估。"
      : "当前版本尚无评估记录；决策终态后才能运行评估。"));
    return;
  }
  root.append(renderTrend(history), renderMetricGrid(history.latest.metrics), renderEvaluationTimeline(history));
}

export function renderEvaluationUnavailable(root, message, { canRun = false } = {}) {
  root.replaceChildren();
  const heading = element("div", "evaluation-heading");
  heading.append(
    element("span", "", "QUALITY EVALUATION / 07"),
    element("strong", "status-unavailable", "UNAVAILABLE"),
    runButton(canRun),
  );
  root.append(heading, element("p", "evaluation-empty", safeText(message)));
}

function renderTrend(history) {
  const box = element("section", "evaluation-trend");
  box.setAttribute("aria-label", "评估趋势窗口");
  box.append(
    trendCell("WINDOW", `${history.trend.sampleCount} / ${history.totalCount}`),
    trendCell("PASS", history.trend.passCount),
    trendCell("WARN", history.trend.warnCount),
    trendCell("FAIL", history.trend.failCount),
  );
  return box;
}

function renderMetricGrid(metrics) {
  const grid = element("div", "evaluation-metrics");
  metrics.forEach((metric, index) => {
    const card = element("article", `evaluation-metric status-${metric.status}`);
    card.append(
      element("code", "", `E-${String(index + 1).padStart(2, "0")}`),
      element("span", "metric-status", statusLabel(metric.status)),
      element("h3", "", metric.label),
      element("strong", "metric-value", metric.value),
      element("small", "", metric.detail),
    );
    if (metric.score !== null) {
      const progress = document.createElement("progress");
      progress.max = 1; progress.value = metric.score;
      progress.setAttribute("aria-label", `${metric.label} ${metric.value}`);
      card.append(progress);
    }
    grid.append(card);
  });
  return grid;
}

function renderEvaluationTimeline(history) {
  const details = element("details", "evaluation-history");
  details.append(element("summary", "", `评估历史 · WINDOW ${history.records.length}`));
  const list = element("ol");
  [...history.records].reverse().forEach((record) => {
    const item = element("li", `status-${record.overall}`);
    item.append(
      element("code", "", String(record.sequence).padStart(2, "0")),
      element("strong", "", statusLabel(record.overall)),
      element("span", "", record.createdAt),
      element("small", "", `${record.digest.slice(0, 12)}…`),
    );
    list.append(item);
  });
  details.append(list);
  return details;
}

function trendCell(label, value) {
  const cell = element("div");
  cell.append(element("span", "", label), element("strong", "", String(value)));
  return cell;
}

function runButton(enabled) {
  const button = element("button", "evaluation-run", "运行服务端评估");
  button.type = "button"; button.dataset.evaluationRun = "true";
  button.disabled = !enabled;
  if (!enabled) button.title = "决策终态后才能运行评估";
  return button;
}

function metricStatus(metric) {
  if (!metric || !METRIC_STATUS.has(metric.status)) throw new Error("Invalid metric status.");
  return metric.status;
}

function optionalScore(value) {
  if (value === null || value === undefined) return null;
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 0 || parsed > 1) throw new Error("Invalid metric score.");
  return parsed;
}

function optionalNonnegative(value) {
  if (value === null || value === undefined) return null;
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 0) throw new Error("Invalid metric value.");
  return parsed;
}

function number(value) {
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 0) throw new Error("Invalid metric count.");
  return parsed;
}

function cleanList(value) {
  if (!Array.isArray(value)) throw new Error("Invalid metric list.");
  return value.map(safeText);
}

function positiveInteger(value) { return Number.isInteger(value) && value >= 1; }
function nonnegativeInteger(value) { return Number.isInteger(value) && value >= 0; }
function formatScore(value) { const score = optionalScore(value); return score === null ? "N/M" : `${Math.round(score * 1000) / 10}%`; }
function formatUnit(value, unit) { const parsed = optionalNonnegative(value); return parsed === null ? "N/M" : `${parsed} ${unit}`; }
function statusLabel(status) { return { pass: "通过", warn: "警告", fail: "失败", not_measured: "未测量" }[status] || "未知"; }

function apiError(payload, status, fallback) {
  const error = new Error(safeText(payload?.error?.message || `${fallback} (${status}).`));
  error.status = status;
  return error;
}

function element(tag, className = "", text = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== "") node.textContent = text;
  return node;
}
