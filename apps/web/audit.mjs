import { safeText } from "./report.mjs";

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
    element("span", "", "AUDIT CHAIN / 06"),
    element("strong", "", `${trail.integrity} · ${trail.records.length} RECORDS`),
  );
  const timeline = element("ol", "audit-timeline");
  trail.records.forEach((record) => {
    const item = element("li", record.redacted.length ? "redacted" : "");
    item.append(
      element("code", "", String(record.sequence).padStart(2, "0")),
      element("strong", "", record.kind === "decision_state" ? "DECISION STATE" : "REDACTION"),
      element("span", "", `${record.phase} · ${record.classification}`),
      element("small", "", `${record.occurredAt} · ${record.hash.slice(0, 12)}…`),
    );
    if (record.redacted.length) item.append(element("em", "", `REDACTED ${record.redacted.join(" / ")}`));
    timeline.append(item);
  });
  root.append(heading, timeline, redactionForm(trail));
}

export function renderAuditUnavailable(root, message) {
  root.replaceChildren(
    element("div", "audit-heading", "AUDIT CHAIN / 06"),
    element("p", "audit-unavailable", safeText(message)),
  );
}

function redactionForm(trail) {
  const details = element("details", "audit-redaction");
  details.append(element("summary", "", "追加脱敏覆盖（需要 audit:redact）"));
  const form = element("form");
  form.id = "audit-redaction-form";
  form.dataset.decisionId = trail.decisionId;
  form.dataset.version = String(trail.version);
  form.append(
    field("TARGET RECORD ID", "target_record_id", "text"),
    field("JSON POINTER", "field_path", "text", "/case/raw_question"),
    field("REASON", "reason", "text"),
  );
  const confirm = element("label", "audit-confirm");
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox"; checkbox.name = "confirmed"; checkbox.required = true;
  confirm.append(checkbox, element("span", "", "确认仅追加覆盖事件，不删除规范记录"));
  const button = element("button", "", "追加脱敏事件");
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

function element(tag, className = "", text = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}
