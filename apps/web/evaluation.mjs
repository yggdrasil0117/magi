import { safeText } from "./report.mjs";
import { tr } from "./i18n.mjs";

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
    scoreMetric("citation", tr("引用有效性", "Citation validity"), evaluation.citation_validity),
    scoreMetric("persona", tr("人格差异度", "Persona differentiation"), evaluation.persona_differentiation),
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
    value: score === null ? tr("未测量", "Not measured") : `${Math.round(score * 1000) / 10}%`,
    detail: key === "citation"
      ? `${number(metric.valid_reference_count)} / ${number(metric.reference_count)} ${tr("条引用", "REFERENCES")}`
      : `${number(metric.pair_count)} ${tr("组配对", "PAIRS")} · ${tr("最小值", "MIN")} ${formatScore(metric.minimum_pair_distance)}`,
  };
}

function arbitrationMetric(metric) {
  const status = metricStatus(metric);
  if (typeof metric.consistent !== "boolean") throw new Error("Invalid arbitration metric.");
  return {
    key: "arbitration", label: tr("裁决一致性", "Arbitration consistency"), status,
    score: metric.consistent ? 1 : 0,
    value: metric.consistent ? tr("一致", "Consistent") : tr("发生漂移", "Drift detected"),
    detail: metric.consistent
      ? `${tr("规则", "RULE")} ${safeText(metric.rule_version)}`
      : `${tr("不匹配", "MISMATCH")} ${cleanList(metric.mismatch_fields).join(" / ") || tr("未知", "UNKNOWN")}`,
  };
}

function latencyMetric(metric) {
  const status = metricStatus(metric);
  const p95 = optionalNonnegative(metric.p95_latency_ms);
  return {
    key: "latency", label: tr("P95 延迟", "P95 latency"), status, score: null,
    value: p95 === null ? tr("未测量", "Not measured") : `${p95} ms`,
    detail: `${number(metric.sample_count)} ${tr("个样本", "SAMPLES")} · ${tr("平均", "MEAN")} ${formatUnit(metric.mean_latency_ms, "ms")}`,
  };
}

function costMetric(metric) {
  const status = metricStatus(metric);
  const cost = optionalNonnegative(metric.total_cost_microusd);
  if (metric.pricing_digest !== null && metric.pricing_digest !== undefined
      && !HASH.test(metric.pricing_digest)) throw new Error("Invalid pricing digest.");
  return {
    key: "cost", label: tr("模型成本", "Model cost"), status, score: null,
    value: cost === null ? tr("未测量", "Not measured") : `USD ${(cost / 1_000_000).toFixed(6)}`,
    detail: `${number(metric.input_tokens)} ${tr("输入", "IN")} / ${number(metric.output_tokens)} ${tr("输出 Tokens", "OUT TOKENS")}`,
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
    element("span", "", tr("质量评估 / 07", "QUALITY EVALUATION / 07")),
    element("strong", `status-${history.latest?.overall || "empty"}`,
      history.latest ? `${statusLabel(history.latest.overall)} · ${history.totalCount} ${tr("条记录", "RECORDS")}` : tr("无记录", "NO RECORDS")),
    runButton(canRun),
  );
  root.append(heading);
  if (!history.latest) {
    root.append(element("p", "evaluation-empty", canRun
      ? tr("当前版本尚无评估记录。可运行一次服务端权威评估。", "This version has no evaluation record. You can run an authoritative server evaluation.")
      : tr("当前版本尚无评估记录；决策终态后才能运行评估。", "This version has no evaluation record; evaluation is available after the decision reaches a terminal state.")));
    return;
  }
  root.append(renderTrend(history), renderMetricGrid(history.latest.metrics), renderEvaluationTimeline(history));
}

export function renderEvaluationUnavailable(root, message, { canRun = false } = {}) {
  root.replaceChildren();
  const heading = element("div", "evaluation-heading");
  heading.append(
    element("span", "", tr("质量评估 / 07", "QUALITY EVALUATION / 07")),
    element("strong", "status-unavailable", tr("不可用", "UNAVAILABLE")),
    runButton(canRun),
  );
  root.append(heading, element("p", "evaluation-empty", safeText(message)));
}

function renderTrend(history) {
  const box = element("section", "evaluation-trend");
  box.setAttribute("aria-label", tr("评估趋势窗口", "Evaluation trend window"));
  box.append(
    trendCell(tr("窗口", "WINDOW"), `${history.trend.sampleCount} / ${history.totalCount}`),
    trendCell(tr("通过", "PASS"), history.trend.passCount),
    trendCell(tr("警告", "WARN"), history.trend.warnCount),
    trendCell(tr("失败", "FAIL"), history.trend.failCount),
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
  details.append(element("summary", "", `${tr("评估历史 · 窗口", "EVALUATION HISTORY · WINDOW")} ${history.records.length}`));
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
  const button = element("button", "evaluation-run", tr("运行服务端评估", "Run server evaluation"));
  button.type = "button"; button.dataset.evaluationRun = "true";
  button.disabled = !enabled;
  if (!enabled) button.title = tr("决策终态后才能运行评估", "Evaluation is available after the decision reaches a terminal state");
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
function statusLabel(status) { return { pass: tr("通过", "Pass"), warn: tr("警告", "Warning"), fail: tr("失败", "Fail"), not_measured: tr("未测量", "Not measured") }[status] || tr("未知", "Unknown"); }

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
