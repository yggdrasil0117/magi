import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { isAllowedDecisionApiPath, upstreamPath } from "./proxy-contract.mjs";

const root = dirname(fileURLToPath(import.meta.url));
const port = Number(process.env.MAGI_WEB_PORT || "3000");
const upstream = new URL(process.env.MAGI_API_URL || "http://127.0.0.1:8000");
const maxResponseBytes = 1_000_000;
const staticFiles = new Map([
  ["/", ["index.html", "text/html; charset=utf-8"]],
  ["/workspace.mjs", ["workspace.mjs", "text/javascript; charset=utf-8"]],
  ["/report.mjs", ["report.mjs", "text/javascript; charset=utf-8"]],
  ["/styles.css", ["styles.css", "text/css; charset=utf-8"]],
  ["/assets/magi-mark.svg", ["prototypes/assets/magi-fallback-mark.svg", "image/svg+xml"]],
]);

if (
  !["http:", "https:"].includes(upstream.protocol)
  || upstream.username
  || upstream.password
  || upstream.search
  || upstream.hash
) {
  throw new Error("MAGI_API_URL must be an HTTP URL without embedded credentials");
}
if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error("Invalid MAGI_WEB_PORT");

const securityHeaders = {
  "cache-control": "no-store",
  "content-security-policy": "default-src 'self'; connect-src 'self'; style-src 'self'; script-src 'self'; base-uri 'none'; frame-ancestors 'none'",
  "referrer-policy": "no-referrer",
  "x-content-type-options": "nosniff",
  "x-frame-options": "DENY",
};

createServer(async (request, response) => {
  try {
    const requestUrl = new URL(request.url || "/", "http://localhost");
    if (request.method === "GET" && staticFiles.has(requestUrl.pathname)) {
      const [filename, contentType] = staticFiles.get(requestUrl.pathname);
      const body = await readFile(join(root, filename));
      response.writeHead(200, { ...securityHeaders, "content-type": contentType });
      response.end(body);
      return;
    }
    if (request.method === "GET" && isAllowedDecisionApiPath(requestUrl.pathname)) {
      await proxyDecisionResource(request, response, requestUrl);
      return;
    }
    response.writeHead(404, { ...securityHeaders, "content-type": "text/plain; charset=utf-8" });
    response.end("Not found.\n");
  } catch {
    response.writeHead(502, { ...securityHeaders, "content-type": "application/json" });
    response.end(JSON.stringify({ error: { code: "web_proxy_failed", message: "The decision API could not be reached." } }));
  }
}).listen(port, "127.0.0.1", () => {
  process.stdout.write(`MAGI decision workspace: http://127.0.0.1:${port}\n`);
});

async function proxyDecisionResource(request, response, requestUrl) {
  const target = new URL(upstreamPath(requestUrl), upstream);
  const headers = { accept: "application/json" };
  if (request.headers.authorization) headers.authorization = request.headers.authorization;
  const upstreamResponse = await fetch(target, { headers, redirect: "error", cache: "no-store" });
  const body = await boundedBody(upstreamResponse);
  response.writeHead(upstreamResponse.status, {
    ...securityHeaders,
    "content-type": upstreamResponse.headers.get("content-type") || "application/json",
  });
  response.end(body);
}

async function boundedBody(upstreamResponse) {
  const declared = Number(upstreamResponse.headers.get("content-length") || "0");
  if (declared > maxResponseBytes) throw new Error("decision response exceeds limit");
  if (!upstreamResponse.body) return Buffer.alloc(0);
  const reader = upstreamResponse.body.getReader();
  const chunks = [];
  let total = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > maxResponseBytes) {
      await reader.cancel();
      throw new Error("decision response exceeds limit");
    }
    chunks.push(Buffer.from(value));
  }
  return Buffer.concat(chunks, total);
}
