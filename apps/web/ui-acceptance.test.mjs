import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const html = await readFile(new URL("./index.html", import.meta.url), "utf8");
const css = await readFile(new URL("./styles.css", import.meta.url), "utf8");

test("production UI has keyboard landmarks and one optional credential field", () => {
  assert.match(html, /class="skip-link"/);
  assert.match(html, /<main class="main">/);
  assert.match(html, /aria-live="polite"/);
  assert.equal((html.match(/type="password"/g) || []).length, 1);
  assert.equal((html.match(/type="password"[^>]*required/g) || []).length, 0);
  assert.match(html, /本地自动鉴权时留空/);
});

test("default decision creation asks only for a plain-language question", () => {
  const createForm = html.match(/<form id="create-form">([\s\S]*?)<\/form>/)?.[1] || "";
  assert.match(createForm, /name="raw_question"[^>]*required/);
  assert.equal((createForm.match(/required/g) || []).length, 1);
  assert.match(createForm, /<details class="form-advanced">/);
  assert.doesNotMatch(createForm, /type="password"/);
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
  assert.match(html, /<b>05<\/b> <i[^>]*>评估<\/i>/);
  assert.match(css, /\.evaluation-run/);
  assert.match(css, /\.metric-status/);
});

test("global language switch covers static Chinese and English labels", () => {
  assert.match(html, /id="language-toggle"/);
  assert.match(html, /data-zh="新建决策" data-en="NEW DECISION"/);
  assert.match(html, /data-zh="概览" data-en="OVERVIEW"/);
  assert.match(html, /data-zh="确认执行" data-en="Confirm command"/);
});

test("production page uses only same-origin assets and no licensed fixture", () => {
  const sources = [...html.matchAll(/(?:src|href)="([^"]+)"/g)].map((match) => match[1]);
  assert.equal(
    sources.every((source) => source.startsWith("/") || source.startsWith("#")),
    true,
  );
  assert.doesNotMatch(html, /https?:\/\//);
});
