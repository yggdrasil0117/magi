const buttons = [...document.querySelectorAll("[data-screen]")];
const panels = [...document.querySelectorAll("[data-panel]")];

function selectScreen(name) {
  buttons.forEach((button) => {
    const selected = button.dataset.screen === name;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
  panels.forEach((panel) => {
    panel.hidden = panel.dataset.panel !== name;
  });
}

buttons.forEach((button) => {
  button.addEventListener("click", () => selectScreen(button.dataset.screen));
});

selectScreen("confirm");
