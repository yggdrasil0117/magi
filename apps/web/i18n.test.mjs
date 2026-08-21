import assert from "node:assert/strict";
import test from "node:test";

import { currentLanguage, setLanguage, tr } from "./i18n.mjs";

test("language layer switches all dynamic labels between Chinese and English", () => {
  assert.equal(currentLanguage(), "zh-CN");
  assert.equal(tr("决策", "Decision"), "决策");
  setLanguage("en");
  assert.equal(tr("决策", "Decision"), "Decision");
  setLanguage("zh-CN");
});

test("language layer rejects unsupported locales", () => {
  assert.throws(() => setLanguage("mixed"), /Unsupported/);
});
