import { renderReport, safeText } from "./report.mjs";
import { commandPresentation, createCommandIntent, executeCommand } from "./commands.mjs";
import {
  createRedactionIntent,
  fetchAuditTrail,
  renderAuditTrail,
  renderAuditUnavailable,
  submitRedaction,
} from "./audit.mjs";
import {
  createAsyncIntent,
  fetchOperation,
  fetchOperationEvents,
  fetchOperationInbox,
  fetchDecisionCatalog,
  fetchDecisionHistory,
  submitAsyncOperation,
} from "./operations.mjs";

const REQUIRED_FIELDS = [
  "schema_version", "decision_id", "version", "state", "case", "evidence",
  "ballots", "awaiting_confirmation", "awaiting_run", "terminal", "available_actions",
];
const KNOWN_ACTIONS = new Set(["confirm", "run", "cancel"]);
const DISCLOSED_BALLOT_STATES = new Set([
  "cross_review", "arbitrated", "completed", "insufficient_information", "degraded", "failed",
]);
let currentView = null;
let currentToken = "";
let dialogAction = null;
let pendingIntent = null;
let operationController = null;
let pendingCreateIntent = null;
let pendingAuditIntent = null;

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
  currentView = view;
  root.replaceChildren();
  root.append(renderState(view), renderCase(view), renderDisclosure(view), renderEvidence(view));
  const reportRoot = element("section", "authoritative-report");
  if (view.report) renderReport(reportRoot, view.report);
  const auditRoot = element("section", "decision-audit");
  auditRoot.id = "decision-audit";
  renderAuditUnavailable(auditRoot, "需要 audit:read 权限以验证并读取规范审计链。");
  root.append(reportRoot, auditRoot, renderActions(view));
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
  copy.append(element("strong", "", view.actions.length ? "只执行服务端明确允许的命令" : "当前没有可执行命令"), element("p", "", view.actions.length ? "确认、运行与取消均先核对后果；运行任务支持断线恢复。" : "客户端不会根据状态自行推断权限。"));
  const controls = element("div", "gate-actions");
  if (view.actions.includes("confirm")) controls.append(commandButton("confirm", "确认并冻结", "primary"));
  if (view.actions.includes("cancel")) controls.append(commandButton("cancel", "取消决策", "danger"));
  if (view.actions.includes("run")) {
    controls.append(commandButton("run", "启动三方评估", "primary"));
  }
  section.append(code, copy, controls);
  return section;
}

function commandButton(action, label, style) {
  const button = element("button", `command-button ${style}`, label);
  button.type = "button";
  button.dataset.command = action;
  return button;
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

async function syncAudit(root, view, token, signal) {
  const auditRoot = root.querySelector("#decision-audit");
  if (!auditRoot) return;
  try {
    const trail = await fetchAuditTrail(view.decisionId, view.version, token, signal);
    renderAuditTrail(auditRoot, trail);
  } catch (error) {
    const message = error.status === 403
      ? "当前凭据没有 audit:read 权限；决策内容仍可正常使用。"
      : `审计链不可用：${safeText(error.message)}`;
    renderAuditUnavailable(auditRoot, message);
  }
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
      currentToken = form.elements.token.value;
      pendingIntent = null;
      pendingAuditIntent = null;
      renderWorkspace(root, payload);
      await syncAudit(root, currentView, currentToken, controller.signal);
      status.textContent = "已从 MAGI API 同步；令牌仍只保留在页面内存。";
    } catch (error) {
      status.className = "status-message error";
      status.textContent = error.name === "AbortError" ? "请求超时，请检查 API 连接。" : safeText(error.message);
    } finally {
      clearTimeout(timer);
      button.disabled = false;
    }
  });
  root.addEventListener("click", (event) => {
    const button = event.target.closest("[data-command]");
    if (button) openCommandDialog(button.dataset.command);
  });
  root.addEventListener("submit", async (event) => {
    const auditForm = event.target.closest("#audit-redaction-form");
    if (!auditForm) return;
    event.preventDefault();
    const button = auditForm.querySelector("button[type=submit]");
    button.disabled = true;
    try {
      pendingAuditIntent ||= createRedactionIntent(
        auditForm.dataset.decisionId,
        auditForm.dataset.version,
        {
          targetRecordId: auditForm.elements.target_record_id.value.trim(),
          fieldPath: auditForm.elements.field_path.value.trim(),
          reason: auditForm.elements.reason.value,
        },
      );
      await submitRedaction(pendingAuditIntent, currentToken);
      pendingAuditIntent = null;
      await syncAudit(root, currentView, currentToken);
      status.className = "status-message";
      status.textContent = "脱敏覆盖已追加；规范记录未被修改。";
    } catch (error) {
      status.className = "status-message error";
      status.textContent = `${safeText(error.message)} 重试会复用相同幂等键。`;
    } finally {
      button.disabled = false;
    }
  });
  bindCommandDialog(root, status);
  bindAsyncForms(root, status);
}

function openCommandDialog(action) {
  const dialog = document.querySelector("#command-dialog");
  const presentation = commandPresentation(action);
  if (pendingIntent && pendingIntent.action !== action) {
    const status = document.querySelector("#status-message");
    status.className = "status-message error";
    status.textContent = "已有结果未知的命令等待安全重试或放弃，不能创建另一条命令。";
    return;
  }
  dialogAction = action;
  setText("#command-dialog-title", presentation.title);
  setText("#command-consequence", presentation.consequence);
  setText("#command-target", `${currentView.decisionId} / V${currentView.version}`);
  const reasonField = document.querySelector("#cancel-reason-field");
  const reason = document.querySelector("#cancel-reason");
  reasonField.hidden = action !== "cancel";
  reason.disabled = Boolean(pendingIntent);
  document.querySelector("#command-retry-note").hidden = !pendingIntent;
  document.querySelector("#command-abandon").hidden = !pendingIntent;
  document.querySelector("#command-submit").textContent = pendingIntent ? "使用相同幂等键重试" : "确认执行";
  if (!pendingIntent) reason.value = "";
  if (typeof dialog.showModal === "function") dialog.showModal();
  else dialog.setAttribute("open", "");
}

function bindCommandDialog(root, status) {
  const dialog = document.querySelector("#command-dialog");
  const form = document.querySelector("#command-form");
  document.querySelector("#command-close").addEventListener("click", () => dialog.close());
  document.querySelector("#command-abandon").addEventListener("click", () => {
    pendingIntent = null;
    dialog.close();
    status.className = "status-message";
    status.textContent = "已放弃本地待重试命令；服务端状态将在下次同步时确认。";
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const submit = document.querySelector("#command-submit");
    if (!pendingIntent) {
      pendingIntent = dialogAction === "run"
        ? createAsyncIntent("run", currentView)
        : createCommandIntent(dialogAction, currentView, {
          reason: document.querySelector("#cancel-reason").value,
        });
    }
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15000);
    submit.disabled = true;
    status.className = "status-message";
    status.textContent = `${dialogAction === "confirm" ? "确认" : "取消"}命令正在提交…`;
    try {
      if (dialogAction === "run") {
        const operation = await submitAsyncOperation(pendingIntent, currentToken, controller.signal);
        pendingIntent = null;
        dialog.close();
        await monitorOperation(operation, currentToken, root, status);
        return;
      }
      const payload = await executeCommand(pendingIntent, currentToken, controller.signal);
      pendingIntent = null;
      renderWorkspace(root, payload);
      await syncAudit(root, currentView, currentToken, controller.signal);
      status.textContent = "命令已由 MAGI API 接受，工作区已同步到返回状态。";
      dialog.close();
    } catch (error) {
      status.className = "status-message error";
      status.textContent = error.name === "AbortError" ? "请求结果未知；请使用相同幂等键重试，或重新同步状态。" : safeText(error.message);
      document.querySelector("#command-retry-note").hidden = false;
      document.querySelector("#command-abandon").hidden = false;
      document.querySelector("#cancel-reason").disabled = true;
      submit.textContent = "使用相同幂等键重试";
    } finally {
      clearTimeout(timer);
      submit.disabled = false;
    }
  });
}

function bindAsyncForms(root, status) {
  const createForm = document.querySelector("#create-form");
  const operationForm = document.querySelector("#operation-form");
  const inboxForm = document.querySelector("#inbox-form");
  const saved = sessionStorage.getItem("magi.operation.id");
  if (saved) operationForm.elements.operation_id.value = safeText(saved);

  createForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = createForm.querySelector("button[type=submit]");
    button.disabled = true;
    currentToken = createForm.elements.token.value;
    try {
      pendingCreateIntent ||= createAsyncIntent("create", {
          rawQuestion: createForm.elements.raw_question.value,
          risk: createForm.elements.risk.value,
          classification: createForm.elements.classification.value,
        });
      const operation = await submitAsyncOperation(pendingCreateIntent, currentToken);
      pendingCreateIntent = null;
      await monitorOperation(operation, currentToken, root, status);
    } catch (error) {
      status.className = "status-message error";
      status.textContent = `${safeText(error.message)} 再次提交将复用相同幂等键。`;
    } finally {
      button.disabled = false;
    }
  });

  operationForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    currentToken = operationForm.elements.token.value;
    try {
      const operation = await fetchOperation(
        operationForm.elements.operation_id.value.trim(), currentToken,
      );
      await monitorOperation(operation, currentToken, root, status);
    } catch (error) {
      status.className = "status-message error";
      status.textContent = safeText(error.message);
    }
  });

  inboxForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    currentToken = inboxForm.elements.token.value;
    try {
      const [inbox, catalog] = await Promise.all([
        fetchOperationInbox(currentToken), fetchDecisionCatalog(currentToken),
      ]);
      renderOperationInbox(inbox);
      renderDecisionCatalog(catalog);
      status.className = "status-message";
      status.textContent = `任务收件箱已同步：${inbox.activeCount} 个进行中，${inbox.failedCount} 个失败。`;
    } catch (error) {
      status.className = "status-message error";
      status.textContent = safeText(error.message);
    }
  });

  document.querySelector("#operation-inbox").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-operation-id]");
    if (!button) return;
    try {
      const operation = await fetchOperation(button.dataset.operationId, currentToken);
      await monitorOperation(operation, currentToken, root, status);
    } catch (error) {
      status.className = "status-message error";
      status.textContent = safeText(error.message);
    }
  });
  document.querySelector("#decision-catalog").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-decision-id]");
    if (!button) return;
    try {
      const history = await fetchDecisionHistory(button.dataset.decisionId, currentToken);
      renderDecisionHistory(history);
    } catch (error) {
      status.className = "status-message error";
      status.textContent = safeText(error.message);
    }
  });
}

function renderOperationInbox(inbox) {
  const root = document.querySelector("#operation-inbox");
  root.replaceChildren();
  const heading = element("header", "inbox-heading");
  heading.append(
    element("span", "", "AUTHORIZED OPERATION INBOX"),
    element("strong", "", `${inbox.activeCount} ACTIVE / ${inbox.failedCount} FAILED`),
  );
  root.append(heading);
  if (!inbox.operations.length) {
    root.append(element("p", "empty", "当前主体没有后台任务。"));
  }
  inbox.operations.forEach((operation) => {
    const button = element("button", `inbox-operation status-${operation.status}`);
    button.type = "button";
    button.dataset.operationId = operation.operationId;
    button.append(
      element("code", "", operation.operationId),
      element("strong", "", `${operation.kind === "create_decision" ? "创建" : "运行"} · ${stageLabel(operation.stage)}`),
      element("span", "", `${operation.status.toUpperCase()} / V${operation.version}`),
    );
    root.append(button);
  });
  root.hidden = false;
}

function renderDecisionCatalog(catalog) {
  const root = document.querySelector("#decision-catalog");
  root.replaceChildren();
  const heading = element("header", "inbox-heading");
  heading.append(
    element("span", "", "AUTHORIZED DECISION CATALOG"),
    element("strong", "", `${catalog.requiredActionCount} REQUIRE ACTION`),
  );
  root.append(heading);
  catalog.decisions.forEach((decision) => {
    const button = element("button", "inbox-operation");
    button.type = "button";
    button.dataset.decisionId = decision.decisionId;
    button.append(
      element("code", "", `${decision.decisionId} / V${decision.version}`),
      element("strong", "", decision.title),
      element("span", "", `${decision.state.toUpperCase()} · ${decision.actions.join(" / ") || "READ"}`),
    );
    root.append(button);
  });
  if (!catalog.decisions.length) root.append(element("p", "empty", "暂无已编目决策。"));
  root.hidden = false;
}

function renderDecisionHistory(history) {
  const root = document.querySelector("#version-history");
  root.replaceChildren(element("code", "", `VERSION HISTORY / ${history.decisionId}`));
  const grid = element("div", "history-grid");
  history.versions.forEach((view) => {
    const card = element("article", "history-version");
    card.append(
      element("strong", "", `V${view.version} · ${safeText(view.state).toUpperCase()}`),
      element("span", "", safeText(view.case?.title)),
      element("p", "", safeText(view.case?.question)),
      element("small", "", `${safeText(view.case?.risk_level).toUpperCase()} / ${safeText(view.case?.data_classification).toUpperCase()}`),
    );
    grid.append(card);
  });
  root.append(grid);
  root.hidden = false;
}

async function monitorOperation(initial, token, root, status) {
  operationController?.abort();
  operationController = new AbortController();
  const signal = operationController.signal;
  let operation = initial;
  let cursor = 0;
  const eventLog = [];
  sessionStorage.setItem("magi.operation.id", operation.operationId);
  document.querySelector("#operation-form").elements.operation_id.value = operation.operationId;
  while (!signal.aborted) {
    const page = await fetchOperationEvents(operation.operationId, cursor, token, signal);
    cursor = page.next;
    eventLog.push(...page.events);
    renderOperationMonitor(operation, eventLog);
    status.className = "status-message";
    status.textContent = `后台任务：${stageLabel(operation.stage)} / ${operation.status}`;
    if (operation.status === "succeeded") {
      sessionStorage.removeItem("magi.operation.id");
      const payload = await loadDecision(operation.decisionId, operation.version, token, signal);
      renderWorkspace(root, payload);
      await syncAudit(root, currentView, token, signal);
      status.textContent = "后台任务完成，已载入权威 DecisionView。";
      return;
    }
    if (operation.status === "failed") {
      sessionStorage.removeItem("magi.operation.id");
      status.className = "status-message error";
      status.textContent = `后台任务未完成：${operation.failureCode || "operation_failed"}`;
      return;
    }
    await delay(Math.min(Math.max(operation.pollAfterMs || 1000, 250), 10000), signal);
    operation = await fetchOperation(operation.operationId, token, signal);
  }
}

function renderOperationMonitor(operation, events) {
  const monitor = document.querySelector("#operation-monitor");
  monitor.replaceChildren();
  const heading = element("div", "operation-heading");
  heading.append(
    element("code", "", `OPERATION ${operation.operationId}`),
    element("strong", "", stageLabel(operation.stage)),
    element("span", "", `${operation.status.toUpperCase()} · V${operation.version}`),
  );
  const rail = element("ol", "operation-stages");
  ["queued", "coordinator", "first_ballot", "cross_review", "arbitration", "reporting", "complete"]
    .forEach((stage) => {
      const item = element("li", stage === operation.stage ? "active" : "", stageLabel(stage));
      rail.append(item);
    });
  const log = element("div", "operation-events");
  events.forEach((event) => log.append(element("span", "", `${event.sequence} · ${stageLabel(event.stage)} · ${event.messageCode}`)));
  monitor.append(heading, rail, log);
  monitor.hidden = false;
}

function stageLabel(stage) {
  return {
    queued: "排队", coordinator: "问题规范化", first_ballot: "独立评估",
    cross_review: "交叉复核", arbitration: "确定性仲裁", reporting: "形成报告",
    complete: "完成",
  }[stage] || safeText(stage);
}

function delay(milliseconds, signal) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, milliseconds);
    signal.addEventListener("abort", () => {
      clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    }, { once: true });
  });
}

if (typeof document !== "undefined") bind();
