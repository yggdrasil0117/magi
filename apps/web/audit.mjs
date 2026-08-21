import { safeText } from "./report.mjs";
import { tr } from "./i18n.mjs";

const HASH = /^[a-f0-9]{64}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export function auditTrailView(document) {
  if (!document || document.schema_version !== "1.0") throw new Error("Unsupported audit schema.");
  if (document.integrity_status !== "verified") throw new Error("Audit integrity is not verified.");
  if (!Array.isArray(document.records) || document.record_count !== document.records.length) {
    throw new Error("Invalid audit record collection.");
  }
  return {
    decisionId: safeText(document.decision_id),
    version: Number(document.decision_version),
    integrity: "VERIFIED",
    records: document.records.map((record, index) => auditRecordView(record, index + 1)),
  };
}

function auditRecordView(record, expectedSequence) {
  if (record.sequence !== expectedSequence || !["decision_state", "redaction"].includes(record.kind)) {
    throw new Error("Invalid audit sequence.");
  }
  if (![record.payload_hash, record.previous_hash, record.record_hash].every((hash) => HASH.test(hash))) {
    throw new Error("Invalid audit hash.");
  }
  const payload = record.payload && typeof record.payload === "object" ? record.payload : {};
  const redacted = Array.isArray(record.redacted_fields) ? record.redacted_fields.map(safeText) : [];
  return {
    id: safeText(record.record_id),
    sequence: record.sequence,
    kind: record.kind,
    classification: safeText(record.classification).toUpperCase(),
    occurredAt: safeText(record.occurred_at),
    hash: record.record_hash,
    phase: safeText(payload.phase || payload.reason || "—"),
    actor: safeText(payload.actor || "SYSTEM"),
    redacted,
  };
}

export async function fetchAuditTrail(decisionId, version, token, signal) {
  const endpoint = `/api/v1/decisions/${encodeURIComponent(decisionId)}/audit?version=${encodeURIComponent(version)}`;
  const response = await fetch(endpoint, {
    headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
    cache: "no-store", credentials: "omit", signal,
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const error = new Error(safeText(payload?.error?.message || `Audit request failed (${response.status}).`));
    error.status = response.status;
    throw error;
  }
  return auditTrailView(payload);
}

export function createRedactionIntent(decisionId, version, fields) {
  if (!UUID.test(fields.targetRecordId || "")) throw new Error("Invalid audit record ID.");
  if (!/^\/(?!\/)(?!.*~)[^/]+(?:\/[^/]+)*$/.test(fields.fieldPath || "")) {
    throw new Error("Invalid redaction path.");
  }
  const reason = safeText(fields.reason).trim();
  if (!reason || reason.length > 1000) throw new Error("Invalid redaction reason.");
  return Object.freeze({
    endpoint: `/api/v1/decisions/${encodeURIComponent(decisionId)}/audit/redactions`,
    key: crypto.randomUUID(),
    body: Object.freeze({
      version: Number(version), target_record_id: fields.targetRecordId,
      field_paths: Object.freeze([fields.fieldPath]), reason,
    }),
  });
}

export async function submitRedaction(intent, token, signal) {
  const response = await fetch(intent.endpoint, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`, Accept: "application/json",
      "Content-Type": "application/json", "Idempotency-Key": intent.key,
    },
    body: JSON.stringify(intent.body), cache: "no-store", credentials: "omit", signal,
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) throw new Error(safeText(payload?.error?.message || `Redaction failed (${response.status}).`));
  return payload;
}

export function renderAuditTrail(root, trail) {
  root.replaceChildren();
  const heading = element("div", "audit-heading");
  heading.append(
    element("span", "", tr("审计链 / 06", "AUDIT CHAIN / 06")),
    element("strong", "", `${trail.integrity} · ${trail.records.length} ${tr("条记录", "RECORDS")}`),
  );
  const timeline = element("ol", "audit-timeline");
  trail.records.forEach((record) => {
    const item = element("li", record.redacted.length ? "redacted" : "");
    item.append(
      element("code", "", String(record.sequence).padStart(2, "0")),
      element("strong", "", record.kind === "decision_state" ? tr("决策状态", "DECISION STATE") : tr("脱敏", "REDACTION")),
      element("span", "", `${phaseLabel(record.phase)} · ${classificationLabel(record.classification)}`),
      element("small", "", `${record.occurredAt} · ${record.hash.slice(0, 12)}…`),
    );
    if (record.redacted.length) item.append(element("em", "", `${tr("已脱敏", "REDACTED")} ${record.redacted.join(" / ")}`));
    timeline.append(item);
  });
  root.append(heading, timeline, redactionForm(trail));
}

export function renderAuditUnavailable(root, message) {
  root.replaceChildren(
    element("div", "audit-heading", tr("审计链 / 06", "AUDIT CHAIN / 06")),
    element("p", "audit-unavailable", safeText(message)),
  );
}

function redactionForm(trail) {
  const details = element("details", "audit-redaction");
  details.append(element("summary", "", tr("追加脱敏覆盖（需要 audit:redact）", "Append redaction overlay (requires audit:redact)")));
  const form = element("form");
  form.id = "audit-redaction-form";
  form.dataset.decisionId = trail.decisionId;
  form.dataset.version = String(trail.version);
  form.append(
    field(tr("目标记录 ID", "TARGET RECORD ID"), "target_record_id", "text"),
    field(tr("JSON 路径", "JSON POINTER"), "field_path", "text", "/case/raw_question"),
    field(tr("原因", "REASON"), "reason", "text"),
  );
  const confirm = element("label", "audit-confirm");
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox"; checkbox.name = "confirmed"; checkbox.required = true;
  confirm.append(checkbox, element("span", "", tr("确认仅追加覆盖事件，不删除规范记录", "Confirm that this appends an overlay without deleting canonical records")));
  const button = element("button", "", tr("追加脱敏事件", "Append redaction event"));
  button.type = "submit";
  form.append(confirm, button);
  details.append(form);
  return details;
}

function field(label, name, type, value = "") {
  const wrapper = element("label");
  const input = document.createElement("input");
  input.name = name; input.type = type; input.required = true; input.value = value;
  wrapper.append(element("span", "", label), input);
  return wrapper;
}

function phaseLabel(phase) {
  return {
    waiting_for_user: tr("等待用户", "WAITING FOR USER"), evidence_ready: tr("证据就绪", "EVIDENCE READY"),
    first_ballot: tr("第一轮投票", "FIRST BALLOT"), cross_review: tr("交叉复核", "CROSS REVIEW"),
    completed: tr("已完成", "COMPLETED"), cancelled: tr("已取消", "CANCELLED"),
  }[phase] || safeText(phase).toUpperCase();
}

function classificationLabel(value) {
  return { public: tr("公开", "PUBLIC"), internal: tr("内部", "INTERNAL"), sensitive: tr("敏感", "SENSITIVE"), restricted: tr("受限", "RESTRICTED") }[value] || safeText(value).toUpperCase();
}

function element(tag, className = "", text = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}
