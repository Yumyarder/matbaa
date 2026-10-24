import React, { useEffect, useRef, useState } from "react";
import { runRegionOcr } from "../../api.js";

let regionIdCounter = 0;

function buildOcrRegion(popup, pageIndex) {
  return {
    id: `r${++regionIdCounter}`,
    pageIndex,
    bbox: popup.pdfBbox,
    action: "ocr",
    approvedText: popup.text.trim(),
    confidence: popup.confidence ?? null,
    // Kept alongside the approved text so the correction stays reviewable —
    // only shown for comparison; conversion uses approvedText exclusively.
    sourceText: popup.sourceText || null,
  };
}

// Draw-a-box tool: click+drag on the canvas to select a region, then a
// popup offers "Görsel" (tag the region as image-only) or "OCR" (run
// Tesseract on just that crop, review/edit the text, then approve). Drawn
// regions are reported to the parent via onAddRegion/onRemoveRegion —
// this component holds no region state of its own beyond the in-progress
// draft box and the active popup.
//
// autoBbox/autoBboxKey let a parent (the scan-and-review queue) open the
// same popup flow WITHOUT the user drawing anything — pass a PDF-space
// bbox and bump autoBboxKey (e.g. to the page index) whenever a new one
// should open. onAutoResolved fires when that auto-opened popup closes
// (confirmed, image-tagged, or cancelled), so the queue knows to advance.
export default function BoundingBoxLayer({
  uploadId,
  pageIndex,
  width,
  height,
  pageWidthPt,
  pageHeightPt,
  regions,
  onAddRegion,
  onRemoveRegion,
  autoBbox,
  autoBboxKey,
  onAutoResolved,
}) {
  const containerRef = useRef(null);
  const [draft, setDraft] = useState(null); // {x0,y0,x1,y1} in screen px, while dragging
  const [popup, setPopup] = useState(null); // {screenBox, pdfBbox, status, text, error, isAuto}

  // An OCR result that has been read but not yet approved used to vanish
  // the moment this layer unmounted — which happens on every page turn,
  // since the canvas shows a loading state in between, and on leaving the
  // editor. The text the person had just watched come back never reached
  // the book. Anything still under review when the layer goes away is now
  // kept, exactly as it stands in the box; "İptal" is the only way to
  // throw it away. The region carries its own page, because by the time
  // this runs the editor is already showing the next one.
  const popupRef = useRef(popup);
  popupRef.current = popup;
  const onAddRegionRef = useRef(onAddRegion);
  onAddRegionRef.current = onAddRegion;
  useEffect(
    () => () => {
      const p = popupRef.current;
      if (p && p.status === "review" && (p.text || "").trim()) {
        onAddRegionRef.current?.(buildOcrRegion(p, pageIndex));
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []
  );

  const scaleX = pageWidthPt ? width / pageWidthPt : 1;
  const scaleY = pageHeightPt ? height / pageHeightPt : 1;

  const screenToPdfBbox = (sx0, sy0, sx1, sy1) => [
    Math.min(sx0, sx1) / scaleX,
    Math.min(sy0, sy1) / scaleY,
    Math.max(sx0, sx1) / scaleX,
    Math.max(sy0, sy1) / scaleY,
  ];

  useEffect(() => {
    if (!autoBbox) return;
    const [x0, y0, x1, y1] = autoBbox;
    setPopup({
      screenBox: { x0: x0 * scaleX, y0: y0 * scaleY, x1: x1 * scaleX, y1: y1 * scaleY },
      pdfBbox: autoBbox,
      status: "choosing",
      text: "",
      error: null,
      isAuto: true,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoBboxKey]);

  const getLocalPoint = (e) => {
    const rect = containerRef.current.getBoundingClientRect();
    return {
      x: Math.min(Math.max(e.clientX - rect.left, 0), width),
      y: Math.min(Math.max(e.clientY - rect.top, 0), height),
    };
  };

  const handleMouseDown = (e) => {
    if (popup) return; // finish or cancel the open popup before starting a new box
    const p = getLocalPoint(e);
    setDraft({ x0: p.x, y0: p.y, x1: p.x, y1: p.y });
  };

  const handleMouseMove = (e) => {
    if (!draft) return;
    const p = getLocalPoint(e);
    setDraft((d) => ({ ...d, x1: p.x, y1: p.y }));
  };

  const handleMouseUp = () => {
    if (!draft) return;
    const w = Math.abs(draft.x1 - draft.x0);
    const h = Math.abs(draft.y1 - draft.y0);
    if (w < 8 || h < 8) {
      setDraft(null); // too small — likely an accidental click, not a real box
      return;
    }
    const screenBox = {
      x0: Math.min(draft.x0, draft.x1),
      y0: Math.min(draft.y0, draft.y1),
      x1: Math.max(draft.x0, draft.x1),
      y1: Math.max(draft.y0, draft.y1),
    };
    setPopup({
      screenBox,
      pdfBbox: screenToPdfBbox(draft.x0, draft.y0, draft.x1, draft.y1),
      status: "choosing", // "choosing" | "loading" | "review" | "error"
      text: "",
      error: null,
      isAuto: false,
    });
    setDraft(null);
  };

  const resolvePopup = () => {
    const wasAuto = popup?.isAuto;
    setPopup(null);
    if (wasAuto) onAutoResolved?.();
  };

  const chooseImage = () => {
    onAddRegion({ id: `r${++regionIdCounter}`, bbox: popup.pdfBbox, action: "image" });
    resolvePopup();
  };

  const chooseExclude = () => {
    onAddRegion({ id: `r${++regionIdCounter}`, bbox: popup.pdfBbox, action: "exclude_text" });
    resolvePopup();
  };

  const chooseOcr = async () => {
    setPopup((p) => ({ ...p, status: "loading" }));
    try {
      const { text, confidence, source_text: sourceText } = await runRegionOcr(uploadId, pageIndex, popup.pdfBbox);
      setPopup((p) => ({ ...p, status: "review", text, confidence, sourceText: sourceText || "" }));
    } catch (err) {
      setPopup((p) => ({ ...p, status: "error", error: err.message || "OCR başarısız oldu." }));
    }
  };

  const confirmOcr = () => {
    if (!(popup.text || "").trim()) return;
    onAddRegion(buildOcrRegion(popup, pageIndex));
    // Cleared before resolvePopup so the unmount safety net above can
    // never add the same region a second time.
    popupRef.current = null;
    resolvePopup();
  };

  return (
    <div
      ref={containerRef}
      className="bbox-layer"
      style={{ width, height }}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
    >
      <svg className="bbox-layer__svg" width={width} height={height}>
        {regions.map((r) => {
          const x0 = r.bbox[0] * scaleX;
          const y0 = r.bbox[1] * scaleY;
          const x1 = r.bbox[2] * scaleX;
          const y1 = r.bbox[3] * scaleY;
          return (
            <g key={r.id} className={`bbox-layer__region bbox-layer__region--${r.action}`}>
              <rect x={x0} y={y0} width={x1 - x0} height={y1 - y0} />
              <text x={x0 + 4} y={y0 + 13}>
                {r.action === "image" ? "Görsel" : r.action === "exclude_text" ? "Hariç" : "OCR"}
                {r.action === "ocr" && r.confidence != null && r.confidence < 70 ? " ⚠" : ""}
              </text>
            </g>
          );
        })}
        {draft && (
          <rect
            className="bbox-layer__draft"
            x={Math.min(draft.x0, draft.x1)}
            y={Math.min(draft.y0, draft.y1)}
            width={Math.abs(draft.x1 - draft.x0)}
            height={Math.abs(draft.y1 - draft.y0)}
          />
        )}
        {popup && (
          <rect
            className="bbox-layer__draft"
            x={popup.screenBox.x0}
            y={popup.screenBox.y0}
            width={popup.screenBox.x1 - popup.screenBox.x0}
            height={popup.screenBox.y1 - popup.screenBox.y0}
          />
        )}
      </svg>

      {regions.map((r) => (
        <button
          key={`del-${r.id}`}
          className="bbox-layer__delete"
          style={{ left: r.bbox[2] * scaleX - 18, top: r.bbox[1] * scaleY - 2 }}
          onClick={(e) => {
            e.stopPropagation();
            onRemoveRegion(r.id);
          }}
          title="Bu bölgeyi kaldır"
        >
          ×
        </button>
      ))}

      {popup && (
        <div
          className="bbox-popup"
          style={{ left: popup.screenBox.x0, top: popup.screenBox.y1 + 6 }}
          onMouseDown={(e) => e.stopPropagation()}
        >
          {popup.status === "choosing" && (
            <div className="bbox-popup__row">
              <button className="bbox-popup__btn bbox-popup__btn--image" onClick={chooseImage}>
                🖼 Görsel
              </button>
              <button className="bbox-popup__btn bbox-popup__btn--ocr" onClick={chooseOcr}>
                🔤 OCR
              </button>
              <button className="bbox-popup__btn bbox-popup__btn--exclude" onClick={chooseExclude}>
                ✂ Hariç Tut
              </button>
              <button className="bbox-popup__btn bbox-popup__btn--cancel" onClick={resolvePopup}>
                {popup.isAuto ? "Atla" : "İptal"}
              </button>
            </div>
          )}

          {popup.status === "loading" && <p className="bbox-popup__status">OCR çalışıyor…</p>}

          {popup.status === "error" && (
            <>
              <p className="bbox-popup__error">{popup.error}</p>
              <button className="bbox-popup__btn bbox-popup__btn--cancel" onClick={resolvePopup}>
                Kapat
              </button>
            </>
          )}

          {popup.status === "review" && (
            <>
              {/* OCR never overwrites the PDF's own text on its own — this
                  is the approval step, and it always shows what extraction
                  already produces here so the choice is informed, not a
                  leap of faith. Approving replaces it in the EPUB; the PDF
                  itself is untouched either way. */}
              <p className="bbox-popup__source-label">Kaynak metin (PDF'ten çıkarılan):</p>
              <p className="bbox-popup__source-text">
                {popup.sourceText ? popup.sourceText : <em>(bu bölgede metin bulunamadı)</em>}
              </p>
              {popup.confidence != null && popup.confidence < 70 && (
                <p className="bbox-popup__warning">
                  ⚠ Düşük güven skoru ({popup.confidence}/100) — metni dikkatlice kontrol edin.
                </p>
              )}
              <p className="bbox-popup__source-label">OCR adayı — onaylarsanız bunu kullanır:</p>
              <textarea
                className="bbox-popup__textarea"
                value={popup.text}
                onChange={(e) => setPopup((p) => ({ ...p, text: e.target.value }))}
                rows={3}
                autoFocus
              />
              <p className="bbox-popup__hint">
                Sayfayı değiştirirseniz bu metin yine de kitaba eklenir. Eklemek istemiyorsanız "Vazgeç"e basın.
              </p>
              <div className="bbox-popup__row">
                <button className="bbox-popup__btn bbox-popup__btn--cancel" onClick={resolvePopup}>
                  Vazgeç
                </button>
                <button
                  className="bbox-popup__btn bbox-popup__btn--confirm"
                  onClick={confirmOcr}
                  disabled={!(popup.text || "").trim()}
                  title={(popup.text || "").trim() ? "" : "Boş metin kitaba eklenemez"}
                >
                  Onayla ve Kitaba Ekle
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
