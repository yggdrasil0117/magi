import { renderReport, safeText } from "./report.mjs";
import { bindLanguageToggle, tr } from "./i18n.mjs";
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
import {
  createEvaluationIntent,
  fetchEvaluationHistory,
  renderEvaluationHistory,
  renderEvaluationUnavailable,
  submitEvaluation,
} from "./evaluation.mjs";

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
  created: [tr("已创建", "CREATED"), tr("草案已创建", "Draft created"), tr("决策仍在准备阶段。", "The decision is still being prepared."), "waiting"],
  normalized: [tr("已规范化", "NORMALIZED"), tr("规范化已完成", "Normalization complete"), tr("等待进入明确的用户确认边界。", "Waiting for explicit user confirmation."), "waiting"],
  waiting_for_user: [tr("等待用户", "WAITING FOR USER"), tr("等待确认与冻结", "Awaiting confirmation"), tr("请核对问题、选项、约束和证据边界。", "Review the question, options, constraints, and evidence boundary."), "waiting"],
  evidence_ready: [tr("证据就绪", "EVIDENCE READY"), tr("可以启动评估", "Ready to evaluate"), tr("决策已冻结，但三方评估尚未开始。", "The decision is frozen; perspective evaluation has not started."), "ready"],
  first_ballot: [tr("第一轮投票", "FIRST BALLOT"), tr("独立评估进行中", "Independent evaluation"), tr("三方意见保持密封，不显示部分投票。", "Perspectives remain sealed; partial ballots are not disclosed."), "processing"],
  cross_review: [tr("交叉复核", "CROSS REVIEW"), tr("有界交叉复核", "Bounded cross-review"), tr("已释放的第一轮意见仅为临时意见。", "Released first-round views remain preliminary."), "processing"],
  arbitrated: [tr("已仲裁", "ARBITRATED"), tr("确定性仲裁完成", "Deterministic arbitration complete"), tr("正在形成权威报告。", "Generating the authoritative report."), "processing"],
  completed: [tr("已完成", "COMPLETED"), tr("决策报告已完成", "Decision report complete"), tr("多数意见与异议均已保存。", "Majority rationale and dissent have been preserved."), "complete"],
  insufficient_information: [tr("信息不足", "INSUFFICIENT"), tr("信息不足", "Insufficient information"), tr("当前证据不足以形成正式选择。", "Current evidence is insufficient for a formal selection."), "waiting"],
  degraded: [tr("已降级", "DEGRADED"), tr("无法形成正式结论", "No formal conclusion"), tr("至少一个必要视角不可用。", "At least one required perspective is unavailable."), "degraded"],
  failed: [tr("失败", "FAILED"), tr("决策协议未完成", "Decision protocol incomplete"), tr("请检查安全的恢复路径和审计信息。", "Review recovery options and audit information."), "failed"],
  cancelled: [tr("已取消", "CANCELLED"), tr("决策已取消", "Decision cancelled"), tr("当前版本不会继续运行。", "This version will not continue."), "cancelled"],
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
    risk: enumLabel(document.case.risk_level),
    classification: enumLabel(document.case.data_classification),
    confirmedAt: safeText(document.case.confirmed_at || tr("未确认", "Not confirmed")),
    options: document.case.options.map((option) => ({ id: safeText(option.id), label: safeText(option.label), description: safeText(option.description) })),
    constraints: document.case.user_constraints.map((item) => `${enumLabel(item.strength)} · ${safeText(item.statement)}`),
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
    id: safeText(item.evidence_id), source: safeText(item.source), type: enumLabel(item.source_type),
    status: enumLabel(item.verification_status), capturedAt: safeText(item.captured_at),
    classification: enumLabel(item.classification), excerpt: safeText(item.excerpt), hash: safeText(item.content_hash),
  };
}

function ballotView(item) {
  return {
    agent: safeText(item.agent), round: Number(item.round), option: safeText(item.selected_option || "abstain"),
    stance: enumLabel(item.stance), rationale: cleanList(item.rationale_summary),
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
  const evaluationRoot = element("section", "decision-evaluation");
  evaluationRoot.id = "decision-evaluation";
  renderEvaluationUnavailable(
    evaluationRoot,
    tr("需要 evaluation:read 权限以读取服务端权威评估历史。", "evaluation:read permission is required to read authoritative evaluation history."),
    { canRun: view.terminal },
  );
  const auditRoot = element("section", "decision-audit");
  auditRoot.id = "decision-audit";
  renderAuditUnavailable(auditRoot, tr("需要 audit:read 权限以验证并读取规范审计链。", "audit:read permission is required to verify and read the canonical audit chain."));
  root.append(reportRoot, evaluationRoot, auditRoot, renderActions(view));
  root.hidden = false;
  updateShell(view);
}

function renderState(view) {
  const section = element("section", `state-banner tone-${view.tone}`);
  const index = element("div", "state-index");
  index.append(element("span", "", tr("状态", "STATE")), element("b", "", stateNumber(view.state)));
  const content = element("div");
  content.append(element("code", "", view.stateCode), element("h2", "", view.stateTitle), element("p", "", view.stateMessage));
  const seal = element("div", "state-seal");
  seal.append(element("span", "", tr("版本", "VERSION")), element("strong", "", `V${view.version}`), element("small", "", view.terminal ? tr("终态", "TERMINAL") : tr("进行中", "ACTIVE")));
  section.append(index, content, seal);
  return section;
}

function renderCase(view) {
  const section = element("section", "case-grid");
  const question = panel(tr("案例 / 01", "CASE / 01"), tr("规范化问题", "Normalized question"));
  question.append(element("p", "question", view.question));
  if (view.rawQuestion !== view.question) question.append(labelValue(tr("原始输入", "Original input"), view.rawQuestion));
  const options = panel(tr("选项 / 02", "OPTIONS / 02"), tr("候选方案", "Candidate options"));
  const list = element("ol", "option-list");
  view.options.forEach((item) => {
    const row = element("li");
    row.append(element("b", "", item.id), element("span", "", item.label));
    if (item.description) row.append(element("small", "", item.description));
    list.append(row);
  });
  options.append(list);
  const boundary = panel(tr("边界 / 03", "BOUNDARY / 03"), tr("约束与未知项", "Constraints and unknowns"), "wide");
  boundary.append(listBlock(tr("用户约束", "User constraints"), view.constraints), listBlock(tr("未知项", "Unknowns"), view.unknowns));
  section.append(question, options, boundary);
  return section;
}

function renderDisclosure(view) {
  const section = panel(tr("三方观点 / 04", "PERSPECTIVES / 04"), tr("三方披露", "Perspective disclosure"), "wide");
  const cells = element("div", "perspective-cells");
  for (const agent of ["melchior", "balthasar", "casper"]) {
    const ballot = view.ballots.find((item) => item.agent === agent);
    const cell = element("article", `perspective-cell ${agent}`);
    cell.append(element("code", "", agentCode(agent)), element("strong", "", agent.toUpperCase()));
    if (!ballot) {
      cell.append(element("span", "sealed", sealedLabel(view.state)));
    } else {
      cell.append(element("span", "ballot-option", `${view.preliminary ? tr("第一轮临时意见", "Preliminary view") : tr("最终意见", "Final view")} · ${ballot.option}`));
      ballot.rationale.forEach((line) => cell.append(element("p", "", line)));
      if (ballot.reviewReason) cell.append(element("small", "", ballot.reviewReason));
    }
    cells.append(cell);
  }
  section.append(cells);
  return section;
}

function renderEvidence(view) {
  const section = panel(tr("证据 / 05", "EVIDENCE / 05"), tr("公开证据", "Disclosed evidence"), "wide");
  if (!view.evidence.length) {
    section.append(element("p", "empty", tr("当前决策没有公开证据。", "This decision has no disclosed evidence.")));
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
  code.append(element("span", "", tr("可用操作", "AVAILABLE ACTIONS")), element("b", "", view.actions.length ? view.actions.map(actionLabel).join(" / ") : tr("无", "NONE")));
  const copy = element("div", "gate-copy");
  copy.append(element("strong", "", view.actions.length ? tr("只执行服务端明确允许的命令", "Only server-authorized commands are available") : tr("当前没有可执行命令", "No actions are currently available")), element("p", "", view.actions.length ? tr("确认、运行与取消均先核对后果；运行任务支持断线恢复。", "Confirm consequences before each command; background runs can be resumed.") : tr("客户端不会根据状态自行推断权限。", "The client never infers permissions from state.")));
  const controls = element("div", "gate-actions");
  if (view.actions.includes("confirm")) controls.append(commandButton("confirm", tr("确认并冻结", "Confirm and freeze"), "primary"));
  if (view.actions.includes("cancel")) controls.append(commandButton("cancel", tr("取消决策", "Cancel decision"), "danger"));
  if (view.actions.includes("run")) {
    controls.append(commandButton("run", tr("启动三方评估", "Run three-perspective evaluation"), "primary"));
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
  (values.length ? values : [tr("无", "None")]).forEach((value) => list.append(element("li", "", value)));
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
function sealedLabel(state) {
  return state === "first_ballot"
    ? tr("已密封 / 进行中", "SEALED / IN PROGRESS")
    : tr("尚无已公开投票", "NO RELEASED BALLOT");
}

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
      ? tr("当前凭据没有 audit:read 权限；决策内容仍可正常使用。", "The current credential lacks audit:read permission; the decision remains available.")
      : `${tr("审计链不可用", "Audit chain unavailable")}: ${safeText(error.message)}`;
    renderAuditUnavailable(auditRoot, message);
  }
}

async function syncEvaluation(root, view, token, signal) {
  const evaluationRoot = root.querySelector("#decision-evaluation");
  if (!evaluationRoot) return;
  try {
    const history = await fetchEvaluationHistory(
      view.decisionId,
      view.version,
      token,
      signal,
    );
    renderEvaluationHistory(evaluationRoot, history, { canRun: view.terminal });
    return true;
  } catch (error) {
    const message = error.status === 403
      ? tr("当前凭据没有 evaluation:read 权限；决策内容仍可正常使用。", "The current credential lacks evaluation:read permission; the decision remains available.")
      : `${tr("评估历史不可用", "Evaluation history unavailable")}: ${safeText(error.message)}`;
    renderEvaluationUnavailable(evaluationRoot, message, { canRun: view.terminal });
    return false;
  }
}

async function syncDiagnostics(root, view, token, signal) {
  await Promise.all([
    syncAudit(root, view, token, signal),
    syncEvaluation(root, view, token, signal),
  ]);
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
    status.textContent = tr("正在读取权威决策视图…", "Loading the authoritative decision view…");
    try {
      const payload = await loadDecision(
        form.elements.decision_id.value.trim(),
        form.elements.version.value,
        currentToken,
        controller.signal,
      );
      pendingIntent = null;
      pendingAuditIntent = null;
      renderWorkspace(root, payload);
      await syncDiagnostics(root, currentView, currentToken, controller.signal);
      status.textContent = tr("已从 MAGI API 同步；令牌仍只保留在页面内存。", "Synchronized with the MAGI API; the token remains in page memory only.");
    } catch (error) {
      status.className = "status-message error";
      status.textContent = error.name === "AbortError" ? tr("请求超时，请检查 API 连接。", "Request timed out. Check the API connection.") : safeText(error.message);
    } finally {
      clearTimeout(timer);
      button.disabled = false;
    }
  });
  root.addEventListener("click", async (event) => {
    const commandButton = event.target.closest("[data-command]");
    if (commandButton) {
      openCommandDialog(commandButton.dataset.command);
      return;
    }
    const evaluationButton = event.target.closest("[data-evaluation-run]");
    if (!evaluationButton || evaluationButton.disabled || !currentView) return;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15000);
    evaluationButton.disabled = true;
    status.className = "status-message";
    status.textContent = tr("正在运行服务端权威质量评估…", "Running the authoritative server evaluation…");
    try {
      const intent = createEvaluationIntent(currentView.decisionId, currentView.version);
      await submitEvaluation(intent, currentToken, controller.signal);
      const historyVisible = await syncEvaluation(
        root,
        currentView,
        currentToken,
        controller.signal,
      );
      status.textContent = historyVisible
        ? tr("评估已保存，指标卡与历史窗口已同步。", "Evaluation saved; metrics and history are synchronized.")
        : tr("评估已保存；当前凭据无法刷新评估历史。", "Evaluation saved; the current credential cannot refresh evaluation history.");
    } catch (error) {
      status.className = "status-message error";
      status.textContent = error.name === "AbortError"
        ? tr("评估请求超时；重新同步历史可确认是否已保存。", "Evaluation request timed out; refresh history to verify whether it was saved.")
        : safeText(error.message);
    } finally {
      clearTimeout(timer);
      evaluationButton.disabled = false;
    }
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
      status.textContent = tr("脱敏覆盖已追加；规范记录未被修改。", "Redaction overlay appended; canonical records were not modified.");
    } catch (error) {
      status.className = "status-message error";
      status.textContent = `${safeText(error.message)} ${tr("重试会复用相同幂等键。", "A retry will reuse the same idempotency key.")}`;
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
      status.textContent = tr("已有结果未知的命令等待安全重试或放弃，不能创建另一条命令。", "A command with an unknown outcome must be retried safely or abandoned before creating another command.");
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
  document.querySelector("#command-submit").textContent = pendingIntent ? tr("使用相同幂等键重试", "Retry with the same idempotency key") : tr("确认执行", "Confirm command");
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
    status.textContent = tr("已放弃本地待重试命令；服务端状态将在下次同步时确认。", "The local pending retry was abandoned; server state will be confirmed on the next synchronization.");
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
    status.textContent = dialogAction === "confirm" ? tr("正在提交确认命令…", "Submitting confirmation…") : tr("正在提交取消命令…", "Submitting cancellation…");
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
      await syncDiagnostics(root, currentView, currentToken, controller.signal);
      status.textContent = tr("命令已由 MAGI API 接受，工作区已同步到返回状态。", "The MAGI API accepted the command and the workspace is synchronized.");
      dialog.close();
    } catch (error) {
      status.className = "status-message error";
      status.textContent = error.name === "AbortError" ? tr("请求结果未知；请使用相同幂等键重试，或重新同步状态。", "The request outcome is unknown; retry with the same idempotency key or synchronize state.") : safeText(error.message);
      document.querySelector("#command-retry-note").hidden = false;
      document.querySelector("#command-abandon").hidden = false;
      document.querySelector("#cancel-reason").disabled = true;
      submit.textContent = tr("使用相同幂等键重试", "Retry with the same idempotency key");
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
      status.textContent = `${safeText(error.message)} ${tr("再次提交将复用相同幂等键。", "Submitting again will reuse the same idempotency key.")}`;
    } finally {
      button.disabled = false;
    }
  });

  operationForm.addEventListener("submit", async (event) => {
    event.preventDefault();
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
    await refreshHome(status);
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
      status.className = "status-message";
      status.textContent = tr("正在打开决策…", "Opening decision…");
      const [payload, history] = await Promise.all([
        loadDecision(button.dataset.decisionId, button.dataset.decisionVersion, currentToken),
        fetchDecisionHistory(button.dataset.decisionId, currentToken),
      ]);
      renderWorkspace(root, payload);
      renderDecisionHistory(history);
      await syncDiagnostics(root, currentView, currentToken);
      status.textContent = tr("已打开最新版决策；可用操作已显示在报告下方。", "The latest decision version is open; available actions appear below the report.");
      root.focus();
    } catch (error) {
      status.className = "status-message error";
      status.textContent = safeText(error.message);
    }
  });

  void refreshHome(status);
}

async function refreshHome(status) {
  status.className = "status-message";
  status.textContent = tr("正在同步决策目录…", "Synchronizing the decision catalog…");
  try {
    const [inbox, catalog] = await Promise.all([
      fetchOperationInbox(currentToken), fetchDecisionCatalog(currentToken),
    ]);
    renderOperationInbox(inbox);
    renderDecisionCatalog(catalog);
    status.textContent = catalog.decisions.length
      ? tr(`已载入 ${catalog.decisions.length} 个决策；点击任意条目即可查看。`, `${catalog.decisions.length} decisions loaded. Select any item to view it.`)
      : tr("尚无决策。只需在左侧描述问题即可开始。", "No decisions yet. Describe a question on the left to begin.");
  } catch (error) {
    status.className = "status-message error";
    status.textContent = tr("尚未获得访问权限。请展开左侧“连接设置”，输入一次访问令牌。", "Access has not been granted. Open Connection settings and enter an access token once.");
  }
}

function renderOperationInbox(inbox) {
  const root = document.querySelector("#operation-inbox");
  root.replaceChildren();
  const heading = element("header", "inbox-heading");
  heading.append(
    element("span", "", tr("已授权任务收件箱", "AUTHORIZED OPERATION INBOX")),
    element("strong", "", `${inbox.activeCount} ${tr("进行中", "ACTIVE")} / ${inbox.failedCount} ${tr("失败", "FAILED")}`),
  );
  root.append(heading);
  if (!inbox.operations.length) {
    root.append(element("p", "empty", tr("当前主体没有后台任务。", "There are no background operations for this principal.")));
  }
  inbox.operations.forEach((operation) => {
    const button = element("button", `inbox-operation status-${operation.status}`);
    button.type = "button";
    button.dataset.operationId = operation.operationId;
    button.append(
      element("code", "", operation.operationId),
      element("strong", "", `${operation.kind === "create_decision" ? tr("创建", "CREATE") : tr("运行", "RUN")} · ${stageLabel(operation.stage)}`),
      element("span", "", `${operationStatusLabel(operation.status)} / V${operation.version}`),
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
    element("span", "", tr("已授权决策目录", "AUTHORIZED DECISION CATALOG")),
    element("strong", "", `${catalog.requiredActionCount} ${tr("项需要操作", "REQUIRE ACTION")}`),
  );
  root.append(heading);
  catalog.decisions.forEach((decision) => {
    const button = element("button", "inbox-operation");
    button.type = "button";
    button.dataset.decisionId = decision.decisionId;
    button.dataset.decisionVersion = String(decision.version);
    button.append(
      element("code", "", `${decision.decisionId} / V${decision.version}`),
      element("strong", "", decision.title),
      element("span", "", `${decisionStateLabel(decision.state)} · ${decision.actions.map(actionLabel).join(" / ") || tr("只读", "READ")}`),
    );
    root.append(button);
  });
  if (!catalog.decisions.length) root.append(element("p", "empty", tr("暂无已编目决策。", "No cataloged decisions.")));
  root.hidden = false;
}

function renderDecisionHistory(history) {
  const root = document.querySelector("#version-history");
  root.replaceChildren(element("code", "", `${tr("版本历史", "VERSION HISTORY")} / ${history.decisionId}`));
  const grid = element("div", "history-grid");
  history.versions.forEach((view) => {
    const card = element("article", "history-version");
    card.append(
      element("strong", "", `V${view.version} · ${decisionStateLabel(view.state)}`),
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
    status.textContent = `${tr("后台任务", "Background operation")}: ${stageLabel(operation.stage)} / ${operation.status}`;
    if (operation.status === "succeeded") {
      sessionStorage.removeItem("magi.operation.id");
      const payload = await loadDecision(operation.decisionId, operation.version, token, signal);
      renderWorkspace(root, payload);
      await syncDiagnostics(root, currentView, token, signal);
      status.textContent = tr("后台任务完成，已载入权威决策视图。", "Background operation complete; the authoritative decision view is loaded.");
      return;
    }
    if (operation.status === "failed") {
      sessionStorage.removeItem("magi.operation.id");
      status.className = "status-message error";
      status.textContent = operationFailureMessage(operation.failureCode);
      return;
    }
    await delay(Math.min(Math.max(operation.pollAfterMs || 1000, 250), 10000), signal);
    operation = await fetchOperation(operation.operationId, token, signal);
  }
}

function operationFailureMessage(code) {
  if (code === "operation_execution_failed") {
    return tr("MAGI 未能生成符合协议的结果。系统已安全停止；请再次提交，或把问题描述得更具体。", "MAGI could not generate a protocol-compliant result. The system stopped safely; submit again or make the question more specific.");
  }
  return `${tr("后台任务未完成", "Background operation incomplete")}: ${safeText(code || "operation_failed")}`;
}

function renderOperationMonitor(operation, events) {
  const monitor = document.querySelector("#operation-monitor");
  monitor.replaceChildren();
  const heading = element("div", "operation-heading");
  heading.append(
    element("code", "", `${tr("后台任务", "OPERATION")} ${operation.operationId}`),
    element("strong", "", stageLabel(operation.stage)),
    element("span", "", `${operationStatusLabel(operation.status)} · V${operation.version}`),
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
    queued: tr("排队", "Queued"), coordinator: tr("问题规范化", "Normalization"), first_ballot: tr("独立评估", "Independent evaluation"),
    cross_review: tr("交叉复核", "Cross-review"), arbitration: tr("确定性仲裁", "Arbitration"), reporting: tr("形成报告", "Reporting"),
    complete: tr("完成", "Complete"),
  }[stage] || safeText(stage);
}

function actionLabel(action) {
  return { confirm: tr("确认", "CONFIRM"), run: tr("运行", "RUN"), cancel: tr("取消", "CANCEL") }[action] || safeText(action);
}

function operationStatusLabel(status) {
  return { accepted: tr("已接受", "ACCEPTED"), running: tr("运行中", "RUNNING"), succeeded: tr("成功", "SUCCEEDED"), failed: tr("失败", "FAILED") }[status] || safeText(status);
}

function decisionStateLabel(state) {
  return STATE_PRESENTATION[state]?.[0] || safeText(state);
}

function enumLabel(value) {
  const labels = {
    low: tr("普通", "LOW"), medium: tr("中等", "MEDIUM"), high: tr("高", "HIGH"), critical: tr("关键", "CRITICAL"),
    public: tr("公开", "PUBLIC"), internal: tr("内部", "INTERNAL"), sensitive: tr("敏感", "SENSITIVE"), restricted: tr("受限", "RESTRICTED"),
    hard: tr("硬约束", "HARD"), soft: tr("软约束", "SOFT"),
    support: tr("支持", "SUPPORT"), oppose: tr("反对", "OPPOSE"), abstain: tr("弃权", "ABSTAIN"),
    verified: tr("已验证", "VERIFIED"), user_asserted: tr("用户声明", "USER ASSERTED"), unverified: tr("未验证", "UNVERIFIED"),
    user: tr("用户", "USER"), url: tr("网址", "URL"), file: tr("文件", "FILE"), note: tr("备注", "NOTE"),
  };
  return labels[value] || safeText(value).toUpperCase();
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

if (typeof document !== "undefined") {
  bindLanguageToggle(document);
  bind();
}
