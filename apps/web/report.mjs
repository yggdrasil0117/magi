const REQUIRED_FIELDS = [
  "decision_id",
  "version",
  "status",
  "vote_count",
  "ballot_count",
  "majority_rationale",
  "evidence_refs",
  "assumptions",
  "unresolved_questions",
  "risks",
  "conditions",
  "recommended_next_step",
  "review_audit",
];

export function reportView(report) {
  if (!report || typeof report !== "object") throw new Error("Invalid report document.");
  for (const field of REQUIRED_FIELDS) {
    if (!(field in report)) throw new Error(`Report is missing ${field}.`);
  }
  return {
    identity: `${safeText(report.decision_id)} · v${Number(report.version)}`,
    status: reportStatus(report.status),
    selected: report.selected_option
      ? `${safeText(report.selected_option_label || report.selected_option)} [${safeText(report.selected_option)}]`
      : tr("未选择方案", "No selected option"),
    ballots: Number(report.ballot_count),
    votes: Object.entries(report.vote_count)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([option, count]) => `${safeText(option)}: ${Number(count)}`),
    majority: cleanList(report.majority_rationale),
    minority: report.minority_report
      ? [
          `${safeText(report.minority_report.agent)} · ${stanceLabel(report.minority_report.stance)} · ${safeText(report.minority_report.selected_option || tr("弃权", "abstain"))}`,
          ...cleanList(report.minority_report.rationale_summary),
        ]
      : [],
    evidence: cleanList(report.evidence_refs),
    assumptions: cleanList(report.assumptions),
    questions: cleanList(report.unresolved_questions),
    risks: cleanList(report.risks),
    conditions: cleanList(report.conditions),
    nextStep: safeText(report.recommended_next_step),
    audit: report.review_audit.map((entry) => ({
      agent: safeText(entry.agent),
      action: entry.changed ? tr("已修订", "REVISED") : tr("已保留", "RETAINED"),
      reason: safeText(entry.reason),
    })),
    generatedAt: safeText(report.generated_at),
    protocol: safeText(report.protocol_version),
    rule: safeText(report.rule_version),
  };
}

export function safeText(value) {
  return String(value ?? "")
    .replace(/\p{C}+/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function cleanList(values) {
  if (!Array.isArray(values)) throw new Error("Invalid report list.");
  return values.filter(Boolean).map(safeText);
}

function reportStatus(status) {
  return {
    consensus: tr("共识", "CONSENSUS"), majority: tr("多数通过", "MAJORITY"),
    conditional_rejection: tr("有条件否决", "CONDITIONAL REJECTION"),
    insufficient_information: tr("信息不足", "INSUFFICIENT INFORMATION"),
    degraded: tr("降级", "DEGRADED"), failed: tr("失败", "FAILED"),
  }[status] || safeText(status).toUpperCase();
}

function stanceLabel(stance) {
  return { support: tr("支持", "SUPPORT"), oppose: tr("反对", "OPPOSE"), abstain: tr("弃权", "ABSTAIN") }[stance] || safeText(stance).toUpperCase();
}

export function renderReport(root, report) {
  const view = reportView(report);
  root.replaceChildren();
  root.append(summary(view));
  const grid = element("div", "report-grid");
  grid.append(
    listCard(tr("投票统计", "VOTE COUNT"), view.votes),
    listCard(tr("多数意见理由", "MAJORITY RATIONALE"), view.majority),
    listCard(tr("少数意见报告", "MINORITY REPORT"), view.minority),
    listCard(tr("证据引用", "EVIDENCE REFERENCES"), view.evidence),
    listCard(tr("假设", "ASSUMPTIONS"), view.assumptions),
    listCard(tr("未解决问题", "UNRESOLVED QUESTIONS"), view.questions),
    listCard(tr("风险", "RISKS"), view.risks),
    listCard(tr("条件", "CONDITIONS"), view.conditions),
    textCard(tr("建议的下一步", "RECOMMENDED NEXT STEP"), view.nextStep, "wide next-step"),
    auditCard(view.audit),
    textCard(
      tr("来源信息", "PROVENANCE"),
      tr(`生成于 ${view.generatedAt} · 协议 ${view.protocol} · 规则 ${view.rule}`, `Generated ${view.generatedAt} · Protocol ${view.protocol} · Rule ${view.rule}`),
      "wide",
    ),
  );
  root.append(grid);
  root.hidden = false;
}

function summary(view) {
  const panel = element("div", "report-summary");
  panel.append(
    summaryCell(tr("最终状态", "FINAL STATUS"), view.status.toUpperCase(), "primary"),
    summaryCell(tr("选择结果", "SELECTED"), view.selected),
    summaryCell(tr("投票数", "BALLOTS"), String(view.ballots)),
    summaryCell(tr("决策", "DECISION"), view.identity, "warning"),
  );
  return panel;
}

function summaryCell(label, value, className = "") {
  const cell = element("div", `summary-cell ${className}`.trim());
  cell.append(element("span", "meta-key", label), element("strong", "", value));
  return cell;
}

function listCard(title, items) {
  const card = element("article", "report-card");
  card.append(element("h3", "", title));
  if (!items.length) {
    card.append(element("p", "empty", tr("无记录。", "None recorded.")));
    return card;
  }
  const list = element("ul");
  for (const item of items) list.append(element("li", "", item));
  card.append(list);
  return card;
}

function textCard(title, value, className = "") {
  const card = element("article", `report-card ${className}`.trim());
  card.append(element("h3", "", title), element("p", "", value));
  return card;
}

function auditCard(entries) {
  const card = element("article", "report-card wide");
  card.append(element("h3", "", tr("复核审计", "REVIEW AUDIT")));
  if (!entries.length) {
    card.append(element("p", "empty", tr("无需交叉复核。", "No cross-review was required.")));
    return card;
  }
  for (const entry of entries) {
    const row = element("div", "audit-row");
    row.append(
      element("span", "audit-agent", entry.agent),
      element("span", "audit-action", entry.action),
      element("span", "", entry.reason),
    );
    card.append(row);
  }
  return card;
}

function element(tag, className = "", text = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}

async function loadReport(decisionId, version, token, signal) {
  const endpoint = `/api/v1/decisions/${encodeURIComponent(decisionId)}/report?version=${encodeURIComponent(version)}`;
  const response = await fetch(endpoint, {
    headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
    cache: "no-store",
    credentials: "omit",
    signal,
  });
  const document = await response.json().catch(() => null);
  if (!response.ok) {
    const message = document?.error?.message || `Report request failed (${response.status}).`;
    throw new Error(safeText(message));
  }
  return document;
}

function bind() {
  const form = document.querySelector("#report-form");
  const root = document.querySelector("#report-root");
  const status = document.querySelector("#status-message");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = form.querySelector("button");
    button.disabled = true;
    root.hidden = true;
    status.className = "status-message";
    status.textContent = tr("正在载入权威报告…", "Loading authoritative report…");
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 10000);
    try {
      const report = await loadReport(
        form.elements.decision_id.value.trim(),
        form.elements.version.value,
        form.elements.token.value,
        controller.signal,
      );
      renderReport(root, report);
      status.textContent = "Report loaded from the MAGI API.";
    } catch (error) {
      status.className = "status-message error";
      status.textContent = error.name === "AbortError" ? "Report request timed out." : safeText(error.message);
    } finally {
      clearTimeout(timer);
      button.disabled = false;
    }
  });
}

if (typeof document !== "undefined" && document.querySelector("#report-form")) bind();
import { tr } from "./i18n.mjs";
