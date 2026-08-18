const UUID = "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89aAbB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}";
const DECISION = new RegExp(`^/api/v1/decisions/${UUID}$`);
const REPORT = new RegExp(`^/api/v1/decisions/${UUID}/report$`);
const CONFIRM = new RegExp(`^/api/v1/decisions/${UUID}/confirm$`);
const CANCEL = new RegExp(`^/api/v1/decisions/${UUID}/cancel$`);

export function isAllowedDecisionApiPath(pathname) {
  return DECISION.test(pathname) || REPORT.test(pathname);
}

export function isAllowedApiOperation(method, pathname) {
  if (method === "GET") return isAllowedDecisionApiPath(pathname);
  if (method === "POST") return CONFIRM.test(pathname) || CANCEL.test(pathname);
  return false;
}

export function upstreamPath(requestUrl, method = "GET") {
  if (!isAllowedApiOperation(method, requestUrl.pathname)) {
    throw new Error("API path is not allowlisted");
  }
  const keys = [...requestUrl.searchParams.keys()];
  if (keys.some((key) => key !== "version") || requestUrl.searchParams.getAll("version").length > 1) {
    throw new Error("API query is not allowlisted");
  }
  const version = requestUrl.searchParams.get("version");
  if (version !== null && !/^[1-9][0-9]*$/.test(version)) {
    throw new Error("API version is invalid");
  }
  if (method !== "GET" && requestUrl.search) {
    throw new Error("Mutation query is not allowed");
  }
  return requestUrl.pathname.slice(4) + requestUrl.search;
}
