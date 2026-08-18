import { renderReport, safeText } from "./report.mjs";

const REQUIRED_FIELDS = [
  "schema_version", "decision_id", "version", "state", "case", "evidence",
  "ballots", "awaiting_confirmation", "awaiting_run", "terminal", "available_actions",
];
const KNOWN_ACTIONS = new Set(["confirm", "run", "cancel"]);
const DISCLOSED_BALLOT_STATES = new Set([
  "cross_review", "arbitrated", "completed", "insufficient_information", "degraded", "failed",
]);

export const STATE_PRESENTATION = Object.freeze({
  created: ["CREATED", "草案已创建", "决策仍在准备阶段。", "waiting"],
  normalized: ["NORMALIZED", "规范化已完成", "等待进入明确的用户确认边界。", "waiting"],
  waiting_for_user: ["WAITING FOR USER", "等待确认与冻结", "请核对问题、选项、约束和证据边界。", "waiting"],
  evidence_ready: ["EVIDENCE READY", "可以启动评估", "决策已冻结，但三方评估尚未开始。", "ready"],
  first_ballot: ["FIRST BALLOT", "独立评估进行中", "三方意见保持密封，不显示部分投票。", "processing"],
  cross_review: ["CROSS REVIEW", "有界交叉复核", "已释放的第一轮意见仅为临时意见。", "processing"],
  arbitrated: ["ARBITRATED", "确定性仲裁完成", "正在形成权威报告。", "processing"],
  completed: ["COMPLETED", "决策报告已完成", "多数意见与异议均已保存。", "complete"],
  insufficient_information: ["INSUFFICIENT", "信息不足", "当前证据不足以形成正式选择。", "waiting"],
  degraded: ["DEGRADED", "无法形成正式结论", "至少一个必要视角不可用。", "degraded"],
  failed: ["FAILED", "决策协议未完成", "请检查安全的恢复路径和审计信息。", "failed"],
  cancelled: ["CANCELLED", "决策已取消", "当前版本不会继续运行。", "cancelled"],
});

export function decisionWorkspaceView(document) {
  if (!document || typeof document !== "object") throw new Error("Invalid DecisionView document.");
  for (const field of REQUIRED_FIELDS) {
    if (!(field in document)) throw new Error(`DecisionView is missing ${field}.`);
  }
  if (document.schema_version !== "1.0") throw new Error("Unsupported DecisionView schema.");
  if (!STATE_PRESENTATION[document.state]) throw new Error("Unsupported decision state.");
  if (!document.case || typeof document.case !== "object") throw new Error("Invalid decision case.");
  for (const field of ["title", "raw_question", "question", "options", "user_constraints", "unknowns", "risk_level", "data_classification"]) {
    if (!(field in document.case)) throw new Error(`Decision case is missing ${field}.`);
  }
  if (!Array.isArray(document.case.options) || document.case.options.length < 2) throw new Error("Invalid decision options.");
  if (!Array.isArray(document.evidence) || !Array.isArray(document.ballots) || !Array.isArray(document.available_actions)) throw new Error("Invalid DecisionView collections.");

  const [stateCode, stateTitle, stateMessage, tone] = STATE_PRESENTATION[document.state];
  const ballots = DISCLOSED_BALLOT_STATES.has(document.state)
    ? document.ballots.map(ballotView)
    : [];
  return {
    decisionId: safeText(document.decision_id),
    version: Number(document.version),
    state: safeText(document.state),
    stateCode,
    stateTitle,
    stateMessage,
    tone,
    title: safeText(document.case.title),
    rawQuestion: safeText(document.case.raw_question),
    question: safeText(document.case.question),
    risk: safeText(document.case.risk_level).toUpperCase(),
    classification: safeText(document.case.data_classification).toUpperCase(),
    confirmedAt: safeText(document.case.confirmed_at || "Not confirmed"),
    options: document.case.options.map((option) => ({ id: safeText(option.id), label: safeText(option.label), description: safeText(option.description) })),
    constraints: document.case.user_constraints.map((item) => `${safeText(item.strength).toUpperCase()} · ${safeText(item.statement)}`),
    unknowns: cleanList(document.case.unknowns),
    evidence: document.evidence.map(evidenceView),
    ballots,
    actions: document.available_actions.filter((action) => KNOWN_ACTIONS.has(action)).map(safeText),
    report: document.report || null,
    terminal: Boolean(document.terminal),
    preliminary: document.state === "cross_review",
  };
}

function evidenceView(item) {
  return {
    id: safeText(item.evidence_id), source: safeText(item.source), type: safeText(item.source_type),
    status: safeText(item.verification_status), capturedAt: safeText(item.captured_at),
    classification: safeText(item.classification), excerpt: safeText(item.excerpt), hash: safeText(item.content_hash),
  };
}

function ballotView(item) {
  return {
    agent: safeText(item.agent), round: Number(item.round), option: safeText(item.selected_option || "abstain"),
    stance: safeText(item.stance), rationale: cleanList(item.rationale_summary),
    changed: Boolean(item.changed_from_previous), reviewReason: safeText(item.review_reason),
  };
}

function cleanList(values) {
  if (!Array.isArray(values)) throw new Error("Invalid DecisionView list.");
  return values.filter(Boolean).map(safeText);
}

export function renderWorkspace(root, document) {
  const view = decisionWorkspaceView(document);
  root.replaceChildren();
  root.append(renderState(view), renderCase(view), renderDisclosure(view), renderEvidence(view));
  const reportRoot = element("section", "authoritative-report");
  if (view.report) renderReport(reportRoot, view.report);
  root.append(reportRoot, renderActions(view));
  root.hidden = false;
  updateShell(view);
}

function renderState(view) {
  const section = element("section", `state-banner tone-${view.tone}`);
  const index = element("div", "state-index");
  index.append(element("span", "", "STATE"), element("b", "", stateNumber(view.state)));
  const content = element("div");
  content.append(element("code", "", view.stateCode), element("h2", "", view.stateTitle), element("p", "", view.stateMessage));
  const seal = element("div", "state-seal");
  seal.append(element("span", "", "VERSION"), element("strong", "", `V${view.version}`), element("small", "", view.terminal ? "TERMINAL" : "ACTIVE"));
  section.append(index, content, seal);
  return section;
}

function renderCase(view) {
  const section = element("section", "case-grid");
  const question = panel("CASE / 01", "规范化问题");
  question.append(element("p", "question", view.question));
  if (view.rawQuestion !== view.question) question.append(labelValue("原始输入", view.rawQuestion));
  const options = panel("OPTIONS / 02", "候选方案");
  const list = element("ol", "option-list");
  view.options.forEach((item) => {
    const row = element("li");
    row.append(element("b", "", item.id), element("span", "", item.label));
    if (item.description) row.append(element("small", "", item.description));
    list.append(row);
  });
  options.append(list);
  const boundary = panel("BOUNDARY / 03", "约束与未知项", "wide");
  boundary.append(listBlock("用户约束", view.constraints), listBlock("未知项", view.unknowns));
  section.append(question, options, boundary);
  return section;
}

function renderDisclosure(view) {
  const section = panel("PERSPECTIVES / 04", "三方披露", "wide");
  const cells = element("div", "perspective-cells");
  for (const agent of ["melchior", "balthasar", "casper"]) {
    const ballot = view.ballots.find((item) => item.agent === agent);
    const cell = element("article", `perspective-cell ${agent}`);
    cell.append(element("code", "", agentCode(agent)), element("strong", "", agent.toUpperCase()));
    if (!ballot) {
      cell.append(element("span", "sealed", sealedLabel(view.state)));
    } else {
      cell.append(element("span", "ballot-option", `${view.preliminary ? "第一轮临时意见" : "最终意见"} · ${ballot.option}`));
      ballot.rationale.forEach((line) => cell.append(element("p", "", line)));
      if (ballot.reviewReason) cell.append(element("small", "", ballot.reviewReason));
    }
    cells.append(cell);
  }
  section.append(cells);
  return section;
}

function renderEvidence(view) {
  const section = panel("EVIDENCE / 05", "公开证据", "wide");
  if (!view.evidence.length) {
    section.append(element("p", "empty", "当前 DecisionView 没有公开证据。"));
    return section;
  }
  const list = element("div", "evidence-list");
  view.evidence.forEach((item) => {
    const card = element("article", "evidence-row");
    card.append(element("code", "", item.id), element("strong", "", item.source), element("span", "", `${item.status} · ${item.classification}`), element("p", "", item.excerpt), element("small", "", `${item.type} · ${item.capturedAt} · ${item.hash.slice(0, 12)}…`));
    list.append(card);
  });
  section.append(list);
  return section;
}

function renderActions(view) {
  const section = element("section", "action-gate");
  const code = element("div", "gate-code");
  code.append(element("span", "", "AVAILABLE ACTIONS"), element("b", "", view.actions.length ? view.actions.join(" / ").toUpperCase() : "NONE"));
  const copy = element("div", "gate-copy");
  copy.append(element("strong", "", "UI-D4a 为只读生产基础层"), element("p", "", view.actions.length ? "服务端已声明可用操作；写入控件将在 UI-D4b 经二次确认设计后接入。" : "当前服务端未声明可执行操作。"));
  section.append(code, copy);
  return section;
}

function panel(index, title, className = "") {
  const article = element("article", `frame-panel ${className}`.trim());
  const header = element("header");
  header.append(element("span", "", index), element("h3", "", title));
  article.append(header);
  return article;
}

function labelValue(label, value) {
  const box = element("div", "label-value");
  box.append(element("small", "", label), element("p", "", value));
  return box;
}

function listBlock(label, values) {
  const box = element("div", "list-block");
  box.append(element("small", "", label));
  const list = element("ul");
  (values.length ? values : ["无"]).forEach((value) => list.append(element("li", "", value)));
  box.append(list);
  return box;
}

function updateShell(view) {
  setText("#decision-title", view.title);
  setText("#decision-identity", `${view.decisionId} / V${view.version}`);
  setText("#decision-risk", view.risk);
  setText("#decision-class", view.classification);
  setText("#system-condition", view.stateCode);
}

function setText(selector, value) {
  const node = document.querySelector(selector);
  if (node) node.textContent = value;
}

function stateNumber(state) {
  return String(Object.keys(STATE_PRESENTATION).indexOf(state) + 1).padStart(2, "0");
}

function agentCode(agent) { return { melchior: "M-01", balthasar: "B-02", casper: "C-03" }[agent]; }
function sealedLabel(state) { return state === "first_ballot" ? "SEALED / IN PROGRESS" : "NO RELEASED BALLOT"; }

function element(tag, className = "", text = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}

async function loadDecision(decisionId, version, token, signal) {
  const endpoint = `/api/v1/decisions/${encodeURIComponent(decisionId)}?version=${encodeURIComponent(version)}`;
  const response = await fetch(endpoint, { headers: { Authorization: `Bearer ${token}`, Accept: "application/json" }, cache: "no-store", credentials: "omit", signal });
  const payload = await response.json().catch(() => null);
  if (!response.ok) throw new Error(safeText(payload?.error?.message || `Decision request failed (${response.status}).`));
  return payload;
}

function bind() {
  const form = document.querySelector("#access-form");
  if (!form) return;
  const root = document.querySelector("#workspace-root");
  const status = document.querySelector("#status-message");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = form.querySelector("button[type=submit]");
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 10000);
    button.disabled = true;
    root.hidden = true;
    status.className = "status-message";
    status.textContent = "正在读取权威 DecisionView…";
    try {
      const payload = await loadDecision(form.elements.decision_id.value.trim(), form.elements.version.value, form.elements.token.value, controller.signal);
      renderWorkspace(root, payload);
      status.textContent = "已从 MAGI API 同步；令牌仍只保留在页面内存。";
    } catch (error) {
      status.className = "status-message error";
      status.textContent = error.name === "AbortError" ? "请求超时，请检查 API 连接。" : safeText(error.message);
    } finally {
      clearTimeout(timer);
      button.disabled = false;
    }
  });
}

if (typeof document !== "undefined") bind();
