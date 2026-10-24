// Checks run in the browser while the interface is being designed; not part
// of the app (nothing imports this file, so the build leaves it out).
// From the dev server's page:
//   const dc = await import("/dev/design_check.js?t=" + Date.now());
//   dc.contrast(); dc.sizes(); dc.measure(".editor p"); dc.spacing();
//   dc.saveFingerprint("start"); ...change...; dc.compareFingerprint("start");
//   dc.blur(10)  /  dc.blur(0)
// The rules they check are the ones in docs/DESIGN.md.

export const SCALE = [10, 11, 11.5, 12, 13, 14, 16, 19, 24, 32, 40, 56];
export const SPACE = [0, 1, 2, 4, 8, 12, 16, 20, 24, 32, 40, 48, 64, 96];

// The book itself (the Kindle screen, the editor's page) keeps the EPUB's
// own styles; the interface rules do not apply inside it.
const BOOK = [".ui-strip", ".kindle-device__screen", ".editor-surface__body", "iframe"];

function visible(el) {
  const r = el.getBoundingClientRect();
  if (r.width === 0 || r.height === 0) return false;
  const s = getComputedStyle(el);
  return s.visibility !== "hidden" && s.display !== "none" && Number(s.opacity) > 0;
}

function textElements(skip = BOOK, root = document.body) {
  const out = [];
  const seen = new Set();
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const node = walker.currentNode;
    if (!node.nodeValue.trim()) continue;
    const el = node.parentElement;
    if (!el || seen.has(el)) continue;
    seen.add(el);
    if (skip.some((sel) => el.closest(sel))) continue;
    if (visible(el)) out.push(el);
  }
  return out;
}

function parseColor(value) {
  let m = value.match(/^rgba?\(([^)]+)\)/);
  if (m) {
    const p = m[1].split(/[\s,/]+/).filter(Boolean).map(Number);
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
  }
  m = value.match(/^color\(srgb ([^)]+)\)/);
  if (m) {
    const p = m[1].split(/[\s/]+/).filter(Boolean).map(Number);
    return { r: p[0] * 255, g: p[1] * 255, b: p[2] * 255, a: p.length > 3 ? p[3] : 1 };
  }
  return null;
}

function over(top, under) {
  const a = top.a + under.a * (1 - top.a);
  if (a === 0) return { r: 0, g: 0, b: 0, a: 0 };
  const mix = (k) => (top[k] * top.a + under[k] * under.a * (1 - top.a)) / a;
  return { r: mix("r"), g: mix("g"), b: mix("b"), a };
}

function background(el) {
  const layers = [];
  let image = false;
  for (let node = el; node; node = node.parentElement) {
    const s = getComputedStyle(node);
    if (s.backgroundImage && s.backgroundImage !== "none") image = true;
    const c = parseColor(s.backgroundColor);
    if (c && c.a > 0) {
      layers.push(c);
      if (c.a >= 1) break;
    }
  }
  let bg = { r: 255, g: 255, b: 255, a: 1 };
  for (let i = layers.length - 1; i >= 0; i--) bg = over(layers[i], bg);
  return { bg, image };
}

function luminance({ r, g, b }) {
  const f = (v) => {
    v /= 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}

export function ratio(fg, bg) {
  const [hi, lo] = [luminance(fg), luminance(bg)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

function label(el) {
  const cls = [...el.classList].slice(0, 2).join(".");
  return el.tagName.toLowerCase() + (cls ? "." + cls : "");
}

// Text below 4.5:1 (3:1 when large: 24px, or 18.66px bold) against what is
// actually behind it, composited through translucent ancestors.
export function contrast(skip = BOOK) {
  const fails = [];
  for (const el of textElements(skip)) {
    const s = getComputedStyle(el);
    const { bg, image } = background(el);
    const fg = over(parseColor(s.color) || { r: 0, g: 0, b: 0, a: 1 }, bg);
    const size = parseFloat(s.fontSize);
    const large = size >= 24 || (size >= 18.66 && Number(s.fontWeight) >= 700);
    const need = large ? 3 : 4.5;
    const r = ratio(fg, bg);
    if (r < need) {
      fails.push({ el: label(el), text: el.textContent.trim().slice(0, 40), ratio: +r.toFixed(2), need, image });
    }
  }
  return fails.sort((a, b) => a.ratio - b.ratio);
}

// The type sizes on screen, with how many elements use each; anything off
// the scale is listed with an example.
export function sizes(skip = BOOK) {
  const counts = {};
  const off = {};
  for (const el of textElements(skip)) {
    const px = Math.round(parseFloat(getComputedStyle(el).fontSize) * 10) / 10;
    counts[px] = (counts[px] || 0) + 1;
    if (!SCALE.includes(px) && !off[px]) off[px] = label(el) + " “" + el.textContent.trim().slice(0, 30) + "”";
  }
  return { counts, off, distinct: Object.keys(counts).length };
}

// Characters per line of the elements matching `selector`, from their width
// and the average advance of their own font on a Turkish sample.
export function measure(selector) {
  const sample = "Kitabın yapısı çıkarılırken paragraflar, dipnotlar ve başlıklar ayrılır.";
  const ctx = document.createElement("canvas").getContext("2d");
  return [...document.querySelectorAll(selector)].filter(visible).slice(0, 8).map((el) => {
    const s = getComputedStyle(el);
    ctx.font = `${s.fontStyle} ${s.fontWeight} ${s.fontSize} ${s.fontFamily}`;
    const avg = ctx.measureText(sample).width / sample.length;
    const width = el.clientWidth - parseFloat(s.paddingLeft) - parseFloat(s.paddingRight);
    return { el: label(el), cpl: Math.round(width / avg) };
  });
}

// Paddings, margins and gaps that are not on the spacing scale.
export function spacing(skip = BOOK) {
  const props = ["paddingTop", "paddingRight", "paddingBottom", "paddingLeft",
    "marginTop", "marginRight", "marginBottom", "marginLeft", "rowGap", "columnGap"];
  const off = {};
  for (const el of document.body.querySelectorAll("*")) {
    if (skip.some((sel) => el.closest(sel)) || !visible(el)) continue;
    const s = getComputedStyle(el);
    for (const p of props) {
      const v = parseFloat(s[p]);
      if (!Number.isFinite(v) || v <= 0 || v > 96 || SPACE.includes(Math.round(v))) continue;
      const key = Math.round(v);
      (off[key] = off[key] || []).length < 3 && off[key].push(label(el) + ":" + p);
    }
  }
  return off;
}

const PROPS = ["font-family", "font-size", "font-weight", "font-style", "line-height", "letter-spacing",
  "text-transform", "color", "background-color", "background-image", "border-top-width",
  "border-top-style", "border-top-color", "border-right-width", "border-bottom-width",
  "border-left-width", "border-radius", "padding-top", "padding-right", "padding-bottom",
  "padding-left", "margin-top", "margin-bottom", "display", "position", "box-shadow", "opacity",
  "text-align", "row-gap", "column-gap", "flex-direction"];

// Every element's computed look, keyed by its tag, classes and order, so a
// change of mechanism can be shown to leave a stylesheet's result as it was.
export function fingerprint(skip = [".ui-strip"]) {
  const map = {};
  const seen = {};
  for (const el of document.body.querySelectorAll("*")) {
    if (skip.some((sel) => el.closest(sel))) continue;
    const base = el.tagName.toLowerCase() + "." + [...el.classList].sort().join(".");
    seen[base] = (seen[base] || 0) + 1;
    const s = getComputedStyle(el);
    map[base + "#" + seen[base]] = PROPS.map((p) => s.getPropertyValue(p)).join("|");
  }
  return map;
}

export function saveFingerprint(name, skip) {
  const map = fingerprint(skip);
  localStorage.setItem("dc:" + name, JSON.stringify(map));
  return Object.keys(map).length;
}

export function compareFingerprint(name, skip) {
  const before = JSON.parse(localStorage.getItem("dc:" + name) || "{}");
  const now = fingerprint(skip);
  const diffs = [];
  for (const key of new Set([...Object.keys(before), ...Object.keys(now)])) {
    if (before[key] === now[key]) continue;
    if (!before[key] || !now[key]) {
      diffs.push({ key, change: before[key] ? "gone" : "new" });
      continue;
    }
    const a = before[key].split("|");
    const b = now[key].split("|");
    const props = PROPS.filter((_, i) => a[i] !== b[i]).map((p, i) => p);
    diffs.push({ key, props: props.map((p) => `${p}: ${a[PROPS.indexOf(p)]} -> ${b[PROPS.indexOf(p)]}`) });
  }
  return { elements: Object.keys(now).length, diffs: diffs.slice(0, 40), total: diffs.length };
}

// Shrink the rendered page into a capture frame of `width` CSS pixels while
// it keeps laying out at the real viewport (media queries unchanged): for
// screenshots from a browser pane smaller than the viewport being checked.
export function fit(width = 800) {
  const s = width ? width / innerWidth : 1;
  document.body.style.transformOrigin = "0 0";
  document.body.style.transform = width ? `scale(${s})` : "";
  document.body.style.width = width ? `${innerWidth}px` : "";
  document.body.style.height = width ? `${innerHeight}px` : "";
  return s;
}

// The squint test: blur the whole page to see which masses lead the eye.
export function blur(px = 10) {
  document.documentElement.style.filter = px ? `blur(${px}px)` : "";
  return px;
}
