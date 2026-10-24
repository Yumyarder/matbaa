// A chapter's figures are stored as base64 on the session and only become
// real files when the EPUB is written, so the `src="images/<id>.png"` the
// chapter HTML carries — which is exactly what the EPUB needs — resolves to
// nothing in the browser and renders as a broken image. These helpers swap
// that path for a data URI at DISPLAY time only.
//
// The stored HTML must never be saved with a data URI in it: the EPUB
// packager matches each <img src> against the chapter's image ids, so a
// data URI both breaks that match and writes megabytes of base64 back into
// the session on every keystroke. Anything that inlines for an editable
// surface has to restore the paths before saving — see restoreImagePaths.

const SRC_ATTR = "data-matbaa-img";

function dataUri(base64) {
  return `data:image/png;base64,${base64}`;
}

/** Path -> data URI for every image a chapter carries. */
export function buildImageMap(images) {
  const map = new Map();
  for (const img of images || []) {
    if (img && img.id && img.base64) map.set(`images/${img.id}.png`, dataUri(img.base64));
  }
  return map;
}

/** For read-only surfaces (the Kindle preview's iframe srcDoc). */
export function inlineImageSrcs(html, images) {
  const map = buildImageMap(images);
  if (!map.size || !html) return html || "";
  let out = html;
  for (const [path, uri] of map) {
    out = out.split(`src="${path}"`).join(`src="${uri}"`);
  }
  return out;
}

/**
 * For the editable surface: swap each figure's src for a data URI while
 * remembering the original path on the element, so the exact path can be
 * put back before the HTML is read out and saved.
 */
export function inlineImagesInDom(root, images) {
  const map = buildImageMap(images);
  if (!root || !map.size) return;
  for (const img of root.querySelectorAll("img[src]")) {
    const path = img.getAttribute("src");
    const uri = map.get(path);
    if (uri) {
      img.setAttribute(SRC_ATTR, path);
      img.setAttribute("src", uri);
    }
  }
}

/** Undo inlineImagesInDom on a detached copy, before reading innerHTML. */
export function restoreImagePaths(root) {
  if (!root) return;
  for (const img of root.querySelectorAll(`img[${SRC_ATTR}]`)) {
    img.setAttribute("src", img.getAttribute(SRC_ATTR));
    img.removeAttribute(SRC_ATTR);
  }
}
