const STORAGE_KEY = "magi.language";
const SUPPORTED = new Set(["zh-CN", "en"]);

function initialLanguage() {
  const saved = globalThis.localStorage?.getItem?.(STORAGE_KEY);
  if (SUPPORTED.has(saved)) return saved;
  if (typeof globalThis.window === "undefined") return "zh-CN";
  return globalThis.navigator?.language?.toLowerCase().startsWith("zh") ? "zh-CN" : "en";
}

let language = initialLanguage();

export function currentLanguage() {
  return language;
}

export function tr(chinese, english) {
  return language === "zh-CN" ? chinese : english;
}

export function setLanguage(next) {
  if (!SUPPORTED.has(next)) throw new Error("Unsupported interface language.");
  language = next;
  globalThis.localStorage?.setItem?.(STORAGE_KEY, next);
}

export function applyStaticTranslations(root = document) {
  root.documentElement.lang = language;
  root.querySelectorAll("[data-zh][data-en]").forEach((node) => {
    node.textContent = language === "zh-CN" ? node.dataset.zh : node.dataset.en;
  });
  root.querySelectorAll("[data-placeholder-zh][data-placeholder-en]").forEach((node) => {
    node.placeholder = language === "zh-CN"
      ? node.dataset.placeholderZh
      : node.dataset.placeholderEn;
  });
  const toggle = root.querySelector("#language-toggle");
  if (toggle) {
    toggle.textContent = language === "zh-CN" ? "EN" : "中文";
    toggle.setAttribute(
      "aria-label",
      language === "zh-CN" ? "Switch to English" : "切换到中文",
    );
  }
}

export function bindLanguageToggle(root = document) {
  applyStaticTranslations(root);
  root.querySelector("#language-toggle")?.addEventListener("click", () => {
    setLanguage(language === "zh-CN" ? "en" : "zh-CN");
    globalThis.location?.reload?.();
  });
}
