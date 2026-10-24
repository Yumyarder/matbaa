// The chapter opening (section label, title, author line) exactly as
// backend/app/builders/epub_builder.py writes it, so the Kindle preview and
// the editor show what ships in the .epub.

export function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function classParts(chapter) {
  const o = chapter.opener || null;
  const label = o && o.label_align
    ? ` align-${o.label_align} scale-${o.label_scale || "small"}${o.label_gap ? ` gap-${o.label_gap}` : ""}`
    : "";
  const title = o ? ` class="align-${o.title_align || "center"} scale-${o.title_scale || "medium"}"` : "";
  let wrapper = "opener";
  if (o) {
    wrapper += " measured" + (o.inline ? " inline" : "");
    wrapper += ` drop-${o.drop ?? 1} align-${o.title_align || "center"}`;
  }
  return { label, title, wrapper };
}

/** The opening lines as flat siblings (the editor needs them flat to read
 *  them back). */
export function openerParts(chapter) {
  if (!chapter || chapter.is_split_continuation) return { eyebrow: "", title: "", byline: "" };
  const c = classParts(chapter);
  return {
    eyebrow: chapter.eyebrow ? `<p class="chapter-eyebrow${c.label}">${escapeHtml(chapter.eyebrow)}</p>` : "",
    title: `<h1${c.title}>${escapeHtml(chapter.title || "")}</h1>`,
    byline: chapter.byline ? `<p class="chapter-byline opener-byline">${escapeHtml(chapter.byline)}</p>` : "",
  };
}

/** The opening wrapped the way the EPUB wraps it. */
export function openerHtml(chapter) {
  const p = openerParts(chapter);
  const inner = p.eyebrow + p.title + p.byline;
  if (!inner || chapter.kind !== "chapter") return inner;
  return `<div class="${classParts(chapter).wrapper}">${inner}</div>`;
}
