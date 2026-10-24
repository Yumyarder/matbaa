// The book stylesheet is written for a whole XHTML page: it styles html and
// body and every bare p and h1. Dropped into the app as-is it restyles the
// app itself — that is where the white strips around the editor came from.
// This rewrites it so every rule applies only inside `scope`, with the
// page-level html/body rules landing on the scope element itself.

function splitTopLevel(css) {
  const rules = [];
  let depth = 0;
  let start = 0;
  for (let i = 0; i < css.length; i++) {
    const ch = css[i];
    if (ch === "{") depth++;
    else if (ch === "}") {
      depth--;
      if (depth === 0) {
        rules.push(css.slice(start, i + 1).trim());
        start = i + 1;
      }
    } else if (ch === ";" && depth === 0) {
      rules.push(css.slice(start, i + 1).trim());
      start = i + 1;
    }
  }
  return rules.filter(Boolean);
}

function scopeSelector(selector, scope) {
  return selector
    .split(",")
    .map((part) => {
      const sel = part.trim();
      if (!sel) return "";
      // html / body (optionally with a class, e.g. body.image-page) are the
      // scope element itself.
      const page = sel.match(/^(?:html|body)((?:[.#:[][^\s]*)?)(.*)$/);
      if (page) return `${scope}${page[1]}${page[2]}`;
      return `${scope} ${sel}`;
    })
    .filter(Boolean)
    .join(", ");
}

export function scopeCss(css, scope) {
  if (!css) return "";
  return splitTopLevel(css.replace(/\/\*[\s\S]*?\*\//g, ""))
    .map((rule) => {
      if (rule.startsWith("@namespace") || rule.startsWith("@page") || rule.startsWith("@import")) return "";
      const open = rule.indexOf("{");
      if (open < 0) return "";
      const head = rule.slice(0, open).trim();
      const body = rule.slice(open + 1, -1);
      if (head.startsWith("@media") || head.startsWith("@supports")) {
        return `${head} {\n${scopeCss(body, scope)}\n}`;
      }
      if (head.startsWith("@")) return rule;
      return `${scopeSelector(head, scope)} {${body}}`;
    })
    .filter(Boolean)
    .join("\n");
}
