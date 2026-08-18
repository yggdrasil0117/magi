const root = document.documentElement;
const viewButtons = [...document.querySelectorAll("[data-view]")];
const panels = [...document.querySelectorAll("[data-panel]")];
const condition = document.querySelector("#header-condition");
const densityButton = document.querySelector("#density-toggle");

const conditions = {
  confirm: "WAITING FOR USER",
  report: "DECISION COMPLETE",
  degraded: "SYSTEM DEGRADED",
};

function selectView(view) {
  panels.forEach((panel) => { panel.hidden = panel.dataset.panel !== view; });
  viewButtons.forEach((button) => {
    const active = button.dataset.view === view;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  condition.textContent = conditions[view];
}

viewButtons.forEach((button) => {
  button.addEventListener("click", () => selectView(button.dataset.view));
});

densityButton.addEventListener("click", () => {
  const reading = root.dataset.density !== "reading";
  root.dataset.density = reading ? "reading" : "command";
  densityButton.setAttribute("aria-pressed", String(reading));
  densityButton.textContent = `阅读模式：${reading ? "开" : "关"}`;
});

selectView("confirm");
