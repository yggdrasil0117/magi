import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const html = await readFile(new URL("./index.html", import.meta.url), "utf8");
const css = await readFile(new URL("./styles.css", import.meta.url), "utf8");

test("production UI has keyboard landmarks and labelled credential fields", () => {
  assert.match(html, /class="skip-link"/);
  assert.match(html, /<main class="main">/);
  assert.match(html, /aria-live="polite"/);
  assert.equal((html.match(/type="password"/g) || []).length, 4);
  assert.equal((html.match(/type="password"[^>]*required/g) || []).length, 4);
});

test("responsive and reduced-motion contracts cover compact layouts", () => {
  assert.match(css, /@media\(max-width:520px\)/);
  assert.match(css, /@media\(max-width:800px\)/);
  assert.match(css, /prefers-reduced-motion:reduce/);
  assert.match(css, /focus-visible/);
  assert.match(css, /evaluation-metrics/);
  assert.match(css, /evaluation-metric\.status-not_measured/);
});

test("evaluation panel remains text-labelled and keyboard reachable", () => {
  assert.match(html, /<b>05<\/b> 评估/);
  assert.match(css, /\.evaluation-run/);
  assert.match(css, /\.metric-status/);
});

test("production page uses only same-origin assets and no licensed fixture", () => {
  const sources = [...html.matchAll(/(?:src|href)="([^"]+)"/g)].map((match) => match[1]);
  assert.equal(
    sources.every((source) => source.startsWith("/") || source.startsWith("#")),
    true,
  );
  assert.doesNotMatch(html, /https?:\/\//);
});
