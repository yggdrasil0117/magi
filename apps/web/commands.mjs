import { safeText } from "./report.mjs";

const MUTATIONS = Object.freeze({
  confirm: {
    title: "确认并冻结当前版本",
    consequence: "确认后问题、选项、约束和证据边界不可修改；不会启动模型评估。",
  },
  cancel: {
    title: "取消当前决策版本",
    consequence: "取消会停止当前未完成工作流，但不会删除案例、证据或已有审计记录。",
  },
  run: {
    title: "启动三方评估",
    consequence: "任务将在后台执行三人格独立评估、交叉复核与确定性仲裁；页面可断开后恢复。",
  },
});

export function commandPresentation(action) {
  const item = MUTATIONS[action];
  if (!item) throw new Error("Unsupported Web command.");
  return item;
}

export function createCommandIntent(action, view, options = {}) {
  commandPresentation(action);
  if (!view?.actions?.includes(action)) throw new Error("Command is not available.");
  const id = safeText(view.decisionId);
  const version = Number(view.version);
  if (!id || !Number.isInteger(version) || version < 1) throw new Error("Invalid command identity.");
  const uuid = safeText(options.uuid || globalThis.crypto?.randomUUID?.());
  if (!uuid) throw new Error("Secure command identity is unavailable.");
  const idempotencyKey = `web-${action}-${uuid}`;
  let body;
  if (action === "confirm") {
    const now = options.now || new Date();
    if (!(now instanceof Date) || Number.isNaN(now.valueOf())) throw new Error("Invalid confirmation time.");
    body = { version, confirmed_at: now.toISOString() };
  } else {
    const reason = safeText(options.reason);
    if (reason.length > 2000) throw new Error("Cancellation reason is too long.");
    body = { version, reason: reason || null };
  }
  return Object.freeze({
    action,
    decisionId: id,
    version,
    idempotencyKey,
    endpoint: `/api/v1/decisions/${encodeURIComponent(id)}/${action}`,
    body: Object.freeze(body),
  });
}

export async function executeCommand(intent, token, signal) {
  const response = await fetch(intent.endpoint, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/json",
      "Content-Type": "application/json",
      "Idempotency-Key": intent.idempotencyKey,
    },
    body: JSON.stringify(intent.body),
    cache: "no-store",
    credentials: "omit",
    signal,
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const error = new Error(safeText(payload?.error?.message || `Command request failed (${response.status}).`));
    error.code = safeText(payload?.error?.code || "command_failed");
    error.status = response.status;
    throw error;
  }
  return payload;
}
