const UUID = "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89aAbB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}";
const DECISION = new RegExp(`^/api/v1/decisions/${UUID}$`);
const REPORT = new RegExp(`^/api/v1/decisions/${UUID}/report$`);
const AUDIT = new RegExp(`^/api/v1/decisions/${UUID}/audit$`);
const AUDIT_REDACTIONS = new RegExp(`^/api/v1/decisions/${UUID}/audit/redactions$`);
const EVALUATIONS = new RegExp(`^/api/v1/decisions/${UUID}/evaluations$`);
const CONFIRM = new RegExp(`^/api/v1/decisions/${UUID}/confirm$`);
const CANCEL = new RegExp(`^/api/v1/decisions/${UUID}/cancel$`);
const RUN = new RegExp(`^/api/v1/decisions/${UUID}/run$`);
const OPERATIONS = new RegExp(`^/api/v1/operations/${UUID}$`);
const OPERATION_EVENTS = new RegExp(`^/api/v1/operations/${UUID}/events$`);
const OPERATION_INBOX = "/api/v1/operations";
const DECISION_INBOX = "/api/v1/decisions";
const DECISION_VERSIONS = new RegExp(`^/api/v1/decisions/${UUID}/versions$`);

export function isAllowedDecisionApiPath(pathname) {
  return DECISION.test(pathname) || REPORT.test(pathname)
    || AUDIT.test(pathname) || EVALUATIONS.test(pathname);
}

export function isAllowedApiOperation(method, pathname) {
  if (method === "GET") {
    return isAllowedDecisionApiPath(pathname)
      || pathname === DECISION_INBOX
      || DECISION_VERSIONS.test(pathname)
      || pathname === OPERATION_INBOX
      || OPERATIONS.test(pathname)
      || OPERATION_EVENTS.test(pathname);
  }
  if (method === "POST") {
    return pathname === "/api/v1/decisions"
      || CONFIRM.test(pathname)
      || CANCEL.test(pathname)
      || RUN.test(pathname)
      || AUDIT_REDACTIONS.test(pathname)
      || EVALUATIONS.test(pathname);
  }
  return false;
}

export function upstreamPath(requestUrl, method = "GET") {
  if (!isAllowedApiOperation(method, requestUrl.pathname)) {
    throw new Error("API path is not allowlisted");
  }
  const eventQuery = OPERATION_EVENTS.test(requestUrl.pathname);
  const inboxQuery = requestUrl.pathname === OPERATION_INBOX;
  const decisionInboxQuery = requestUrl.pathname === DECISION_INBOX;
  const evaluationQuery = EVALUATIONS.test(requestUrl.pathname);
  const allowedKeys = eventQuery
    ? new Set(["after", "limit"])
    : (inboxQuery || decisionInboxQuery) ? new Set(["limit"])
      : evaluationQuery ? new Set(["version", "limit"]) : new Set(["version"]);
  const keys = [...requestUrl.searchParams.keys()];
  if (keys.some((key) => !allowedKeys.has(key)) || keys.some((key) => requestUrl.searchParams.getAll(key).length > 1)) {
    throw new Error("API query is not allowlisted");
  }
  const version = requestUrl.searchParams.get("version");
  if (version !== null && !/^[1-9][0-9]*$/.test(version)) {
    throw new Error("API version is invalid");
  }
  if (eventQuery) {
    const after = requestUrl.searchParams.get("after");
    const limit = requestUrl.searchParams.get("limit");
    if (after !== null && !/^(0|[1-9][0-9]*)$/.test(after)) throw new Error("API cursor is invalid");
    if (limit !== null && (!/^[1-9][0-9]*$/.test(limit) || Number(limit) > 100)) throw new Error("API limit is invalid");
  }
  if (inboxQuery || decisionInboxQuery || evaluationQuery) {
    const limit = requestUrl.searchParams.get("limit");
    if (limit !== null && (!/^[1-9][0-9]*$/.test(limit) || Number(limit) > 100)) throw new Error("API limit is invalid");
  }
  if (method !== "GET" && requestUrl.search) {
    throw new Error("Mutation query is not allowed");
  }
  return requestUrl.pathname.slice(4) + requestUrl.search;
}
