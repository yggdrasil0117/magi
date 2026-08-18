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
    status: safeText(report.status),
    selected: report.selected_option
      ? `${safeText(report.selected_option_label || report.selected_option)} [${safeText(report.selected_option)}]`
      : "No selected option",
    ballots: Number(report.ballot_count),
    votes: Object.entries(report.vote_count)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([option, count]) => `${safeText(option)}: ${Number(count)}`),
    majority: cleanList(report.majority_rationale),
    minority: report.minority_report
      ? [
          `${safeText(report.minority_report.agent)} · ${safeText(report.minority_report.stance)} · ${safeText(report.minority_report.selected_option || "abstain")}`,
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
      action: entry.changed ? "REVISED" : "RETAINED",
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

export function renderReport(root, report) {
  const view = reportView(report);
  root.replaceChildren();
  root.append(summary(view));
  const grid = element("div", "report-grid");
  grid.append(
    listCard("VOTE COUNT", view.votes),
    listCard("MAJORITY RATIONALE", view.majority),
    listCard("MINORITY REPORT", view.minority),
    listCard("EVIDENCE REFERENCES", view.evidence),
    listCard("ASSUMPTIONS", view.assumptions),
    listCard("UNRESOLVED QUESTIONS", view.questions),
    listCard("RISKS", view.risks),
    listCard("CONDITIONS", view.conditions),
    textCard("RECOMMENDED NEXT STEP", view.nextStep, "wide next-step"),
    auditCard(view.audit),
    textCard(
      "PROVENANCE",
      `Generated ${view.generatedAt} · Protocol ${view.protocol} · Rule ${view.rule}`,
      "wide",
    ),
  );
  root.append(grid);
  root.hidden = false;
}

function summary(view) {
  const panel = element("div", "report-summary");
  panel.append(
    summaryCell("FINAL STATUS", view.status.toUpperCase(), "primary"),
    summaryCell("SELECTED", view.selected),
    summaryCell("BALLOTS", String(view.ballots)),
    summaryCell("DECISION", view.identity, "warning"),
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
    card.append(element("p", "empty", "None recorded."));
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
  card.append(element("h3", "", "REVIEW AUDIT"));
  if (!entries.length) {
    card.append(element("p", "empty", "No cross-review was required."));
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
    status.textContent = "Loading authoritative report…";
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
