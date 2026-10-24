import React, { useMemo, useRef } from "react";
import { inlineImageSrcs } from "../utils/chapterImages.js";
import { escapeHtml, openerHtml } from "../utils/chapterOpener.js";

// Kindle "Font Size 1" (the smallest of the 1-14 preset scale on a Paperwhite
// / Basic Kindle) renders body text at roughly 12.5px against a 1072-wide
// e-ink panel. We reproduce that ratio inside a fixed device frame so the
// preview is a faithful proxy for the shipped .epub, not just "a serif page".
const KINDLE_SCREEN_WIDTH = 360; // css px, scaled representation of 1072 device px
const KINDLE_SCREEN_HEIGHT = 486;
const KINDLE_FONT_SIZE1_PX = 12.5;

function buildSrcDoc(css, bodyHtml, chapter, fontFaces = "") {
  const opener = openerHtml(chapter);
  const bodyClass = chapter.kind === "frontmatter" ? "frontmatter-page" : chapter.kind === "toc" ? "toc-page" : "";
  return `<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<style>
  ${fontFaces}
  html { -webkit-text-size-adjust: 100%; }
  body { font-size: ${KINDLE_FONT_SIZE1_PX}px; }
  ${css}
  body { padding-top: 14px; padding-bottom: 14px; }
</style>
</head>
<body class="${bodyClass}">${opener}${bodyHtml}</body>
</html>`;
}

// The preview frame has no origin of its own (sandbox=""): the faces are
// fetched by their full address.
function absoluteFontUrls(fontFaces) {
  return fontFaces.replace(/url\("\/api\//g, `url("${window.location.origin}/api/`);
}

function buildImageSrcDoc(css, imageBase64, title) {
  return `<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<style>
  ${css}
  html, body { margin: 0; padding: 0; }
</style>
</head>
<body class="image-page">
  <div class="image-page-wrapper">
    <img src="data:image/png;base64,${imageBase64}" alt="${escapeHtml(title)}" />
  </div>
</body>
</html>`;
}

export default function KindleSimulator({ css, chapter, fontFaces = "", deviceModel = "Kindle 11. nesil · 6″" }) {
  const iframeRef = useRef(null);

  const isImagePage = chapter?.kind === "image";

  const srcDoc = useMemo(() => {
    if (!chapter) return "";
    if (isImagePage) return buildImageSrcDoc(css, chapter.image_base64, chapter.title);
    return buildSrcDoc(css, inlineImageSrcs(chapter.html, chapter.images), chapter, absoluteFontUrls(fontFaces));
  }, [css, chapter, isImagePage, fontFaces]);

  // The printed pages this chapter spans, from the book's own page marks —
  // what a Kindle shows in its footer as "Sayfa 43".
  const pageRange = useMemo(() => {
    const pages = [...(chapter?.html || "").matchAll(/id="page-(\d+)"/g)].map((m) => m[1]);
    if (!pages.length) return "";
    return pages.length === 1 ? `s. ${pages[0]}` : `s. ${pages[0]}–${pages[pages.length - 1]}`;
  }, [chapter]);

  return (
    <div className="kindle-rail">
      <div className="kindle-rail__label">
        <span className="ruler-mark">02</span>
        Kindle önizleme
        <span className="kindle-rail__model">{deviceModel} · yazı boyutu 1</span>
      </div>

      <div className="kindle-device">
        <div className="kindle-device__bezel">
          <div className="kindle-device__screen">
            {chapter ? (
              <iframe
                ref={iframeRef}
                title="kindle-preview"
                srcDoc={srcDoc}
                sandbox=""
                style={{ width: KINDLE_SCREEN_WIDTH, height: KINDLE_SCREEN_HEIGHT }}
              />
            ) : (
              <div className="kindle-device__empty">Bölüm seçilmedi</div>
            )}
          </div>
          <div className="kindle-device__statusbar">
            <span>{chapter ? chapter.title : "—"}</span>
            {pageRange && <span title="Kitabın basılı sayfa numaraları">{pageRange}</span>}
          </div>
        </div>
      </div>

      <p className="kindle-rail__hint">
        EPUB'a giden stil dosyasının aynısıyla çizilir: kenar boşlukları, girintiler ve dipnotlar dahil.
      </p>
    </div>
  );
}
