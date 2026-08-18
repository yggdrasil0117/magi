import { safeText } from "./report.mjs";

const STATUSES = new Set(["accepted", "running", "succeeded", "failed"]);
const STAGES = new Set([
  "queued", "coordinator", "first_ballot", "cross_review",
  "arbitration", "reporting", "complete",
]);

export function operationView(document) {
  if (!document || document.schema_version !== "1.0") throw new Error("Unsupported operation receipt.");
  if (!STATUSES.has(document.status) || !STAGES.has(document.stage)) throw new Error("Invalid operation lifecycle.");
  const operationId = safeText(document.operation_id);
  const decisionId = safeText(document.decision_id);
  const version = Number(document.decision_version);
  const sequence = Number(document.last_event_sequence);
  if (!operationId || !decisionId || !Number.isInteger(version) || version < 1 || !Number.isInteger(sequence) || sequence < 1) {
    throw new Error("Invalid operation identity.");
  }
  return Object.freeze({
    operationId,
    decisionId,
    version,
    kind: safeText(document.kind),
    status: document.status,
    stage: document.stage,
    sequence,
    pollAfterMs: document.next_poll_after_ms == null ? null : Number(document.next_poll_after_ms),
    resultAvailable: Boolean(document.result_available),
    failureCode: safeText(document.failure_code),
  });
}

export function createAsyncIntent(kind, values, options = {}) {
  const uuid = safeText(options.uuid || globalThis.crypto?.randomUUID?.());
  if (!uuid) throw new Error("Secure operation identity is unavailable.");
  if (kind === "create") {
    const rawQuestion = safeText(values.rawQuestion);
    if (!rawQuestion || rawQuestion.length > 20000) throw new Error("Invalid decision question.");
    return freezeIntent({
      kind,
      endpoint: "/api/v1/decisions",
      idempotencyKey: `web-create-${uuid}`,
      body: {
        raw_question: rawQuestion,
        minimum_risk_level: safeText(values.risk || "low"),
        data_classification: safeText(values.classification || "internal"),
        evidence: [],
      },
    });
  }
  if (kind === "run") {
    if (!values?.actions?.includes("run")) throw new Error("Run is not available.");
    return freezeIntent({
      kind,
      endpoint: `/api/v1/decisions/${encodeURIComponent(values.decisionId)}/run`,
      idempotencyKey: `web-run-${uuid}`,
      body: { version: Number(values.version) },
    });
  }
  throw new Error("Unsupported asynchronous operation.");
}

function freezeIntent(intent) {
  return Object.freeze({ ...intent, body: Object.freeze(intent.body) });
}

export async function submitAsyncOperation(intent, token, signal) {
  const response = await request(intent.endpoint, token, signal, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": intent.idempotencyKey,
      Prefer: "respond-async",
    },
    body: JSON.stringify(intent.body),
  });
  if (response.status !== 202 || response.headers.get("preference-applied") !== "respond-async") {
    throw new Error("The API did not accept asynchronous execution.");
  }
  return operationView(await response.json());
}

export async function fetchOperation(operationId, token, signal) {
  const response = await request(`/api/v1/operations/${encodeURIComponent(operationId)}`, token, signal);
  return operationView(await response.json());
}

export async function fetchOperationInbox(token, signal) {
  const response = await request("/api/v1/operations?limit=50", token, signal);
  const payload = await response.json();
  if (!payload || payload.schema_version !== "1.0" || !Array.isArray(payload.operations)) {
    throw new Error("Invalid operation inbox.");
  }
  return Object.freeze({
    activeCount: Number(payload.active_count),
    failedCount: Number(payload.failed_count),
    operations: payload.operations.map(operationView),
  });
}

export async function fetchDecisionCatalog(token, signal) {
  const response = await request("/api/v1/decisions?limit=50", token, signal);
  const payload = await response.json();
  if (!payload || payload.schema_version !== "1.0" || !Array.isArray(payload.decisions)) {
    throw new Error("Invalid decision catalog.");
  }
  return Object.freeze({
    requiredActionCount: Number(payload.required_action_count),
    decisions: payload.decisions.map((item) => Object.freeze({
      decisionId: safeText(item.decision_id), version: Number(item.version),
      title: safeText(item.title), state: safeText(item.state),
      risk: safeText(item.risk_level), classification: safeText(item.data_classification),
      actions: Array.isArray(item.available_actions) ? item.available_actions.map(safeText) : [],
    })),
  });
}

export async function fetchDecisionHistory(decisionId, token, signal) {
  const response = await request(
    `/api/v1/decisions/${encodeURIComponent(decisionId)}/versions`, token, signal,
  );
  const payload = await response.json();
  if (!payload || payload.schema_version !== "1.0" || !Array.isArray(payload.versions)) {
    throw new Error("Invalid decision history.");
  }
  return Object.freeze({ decisionId: safeText(payload.decision_id), versions: payload.versions });
}

export async function fetchOperationEvents(operationId, after, token, signal) {
  const endpoint = `/api/v1/operations/${encodeURIComponent(operationId)}/events?after=${after}&limit=100`;
  const response = await request(endpoint, token, signal);
  const payload = await response.json();
  if (!payload || payload.schema_version !== "1.0" || !Array.isArray(payload.events)) throw new Error("Invalid operation event page.");
  return Object.freeze({
    events: payload.events.map((item) => Object.freeze({
      sequence: Number(item.sequence),
      type: safeText(item.event_type),
      stage: safeText(item.stage),
      messageCode: safeText(item.message_code),
      occurredAt: safeText(item.occurred_at),
    })),
    next: Number(payload.next_after_sequence),
    hasMore: Boolean(payload.has_more),
  });
}

async function request(endpoint, token, signal, options = {}) {
  const response = await fetch(endpoint, {
    ...options,
    headers: { Authorization: `Bearer ${token}`, Accept: "application/json", ...options.headers },
    cache: "no-store",
    credentials: "omit",
    signal,
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(safeText(payload?.error?.message || `Operation request failed (${response.status}).`));
  }
  return response;
}
