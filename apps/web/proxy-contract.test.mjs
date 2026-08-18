import assert from "node:assert/strict";
import test from "node:test";

import { isAllowedApiOperation, isAllowedDecisionApiPath, upstreamPath } from "./proxy-contract.mjs";

const id = "11111111-1111-4111-8111-111111111111";

test("proxy allows only versioned decision reads and JSON reports", () => {
  assert.equal(isAllowedDecisionApiPath(`/api/v1/decisions/${id}`), true);
  assert.equal(isAllowedDecisionApiPath(`/api/v1/decisions/${id}/report`), true);
  assert.equal(isAllowedDecisionApiPath(`/api/v1/decisions/${id}/confirm`), false);
  assert.equal(isAllowedDecisionApiPath("/api/v1/decisions/not-a-uuid"), false);
  assert.equal(isAllowedDecisionApiPath(`/api/v1/decisions/${id}/report.md`), false);
});

test("proxy strips the local API prefix and retains only query parameters", () => {
  const request = new URL(`/api/v1/decisions/${id}?version=3`, "http://localhost");
  assert.equal(upstreamPath(request), `/v1/decisions/${id}?version=3`);
  assert.throws(
    () => upstreamPath(new URL(`/api/v1/decisions/${id}/run`, "http://localhost")),
    /not allowlisted/,
  );
  assert.throws(
    () => upstreamPath(new URL(`/api/v1/decisions/${id}?debug=true`, "http://localhost")),
    /query is not allowlisted/,
  );
  assert.throws(
    () => upstreamPath(new URL(`/api/v1/decisions/${id}?version=0`, "http://localhost")),
    /version is invalid/,
  );
});

test("proxy permits only confirm and cancel mutations", () => {
  assert.equal(isAllowedApiOperation("POST", `/api/v1/decisions/${id}/confirm`), true);
  assert.equal(isAllowedApiOperation("POST", `/api/v1/decisions/${id}/cancel`), true);
  assert.equal(isAllowedApiOperation("POST", `/api/v1/decisions/${id}/run`), false);
  assert.equal(isAllowedApiOperation("POST", "/api/v1/decisions"), false);
  assert.equal(isAllowedApiOperation("GET", `/api/v1/decisions/${id}/confirm`), false);
  assert.equal(
    upstreamPath(new URL(`/api/v1/decisions/${id}/confirm`, "http://localhost"), "POST"),
    `/v1/decisions/${id}/confirm`,
  );
  assert.throws(
    () => upstreamPath(new URL(`/api/v1/decisions/${id}/cancel?version=1`, "http://localhost"), "POST"),
    /query|Mutation/,
  );
});
