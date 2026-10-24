// Each look (design language) is a whole stylesheet, not one sheet with
// overrides: Gece Matbaası is app.css exactly as it was; Haşiye is
// hasiye.css, an annotated edition on bone paper (DESIGN.md).
// Only the chosen one is on the page, as one <style> element, so neither
// can leak into the other.
import sade from "./styles/app.css?inline";
import hasiye from "./styles/hasiye.css?inline";

const KEY = "matbaa:ui";
const SHEETS = { gece: sade, hasiye };
// the names the choice was stored under before the looks had names
const OLD = { simple: "gece", cool: "hasiye" };
let current = "hasiye";

export function storedMode() {
  try {
    const stored = localStorage.getItem(KEY);
    const mode = OLD[stored] || stored;
    return mode in SHEETS ? mode : "hasiye";
  } catch {
    return "hasiye";
  }
}

export function applyTheme(mode) {
  current = mode in SHEETS ? mode : "hasiye";
  let style = document.getElementById("matbaa-theme");
  if (!style) {
    style = document.createElement("style");
    style.id = "matbaa-theme";
    document.head.appendChild(style);
  }
  style.textContent = SHEETS[current];
  document.documentElement.dataset.ui = current;
  try {
    localStorage.setItem(KEY, current);
  } catch {
    /* a private window: the choice lasts this visit */
  }
}

if (import.meta.hot) {
  import.meta.hot.accept(["./styles/app.css?inline", "./styles/hasiye.css?inline"], ([a, g]) => {
    if (a) SHEETS.gece = a.default;
    if (g) SHEETS.hasiye = g.default;
    applyTheme(current);
  });
}
