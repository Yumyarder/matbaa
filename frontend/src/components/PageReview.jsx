import React, { useEffect, useMemo, useState } from "react";
import { fetchScanIssues } from "../api.js";

// What the OCR banner says, by why the pages need reading.
const OCR_REASON_TITLE = {
  scan: "Bu PDF taranmış — sayfalardaki yazı OCR ile okunuyor.",
  "broken-text": "Bu PDF'in metin katmanı bozuk (harfler okunamıyor) — sayfalar OCR ile yeniden okunuyor.",
  "sparse-scan": "Bu taramanın kendi OCR katmanı metnin çoğunu kaçırmış — sayfalar yeniden okunuyor.",
};

// Per-page mode: "text" (default, extracted/editable), "image" (kept as a
// pixel-exact picture, never reflowed), "toc" (force İçindekiler parsing
// regardless of the automatic heuristic), "exclude" (dropped entirely).
export default function PageReview({
  preview,
  onConfirm,
  isConverting,
  conversionProgress,
  onOpenPdfEditor,
  modes,
  onChangeModes,
  coverIndex,
  onChangeCoverIndex,
  autoFigures,
  onChangeAutoFigures,
  ocrJob,
  onSkipOcr,
}) {
  const [issuePages, setIssuePages] = useState(new Set());
  useEffect(() => {
    let cancelled = false;
    fetchScanIssues(preview.upload_id)
      .then((data) => {
        if (!cancelled) setIssuePages(new Set((data.issues || []).map((i) => i.page_index)));
      })
      .catch(() => {
        /* best-effort — badges just won't show if the scan fails */
      });
    return () => {
      cancelled = true;
    };
  }, [preview.upload_id]);

  const setMode = (index, mode) => {
    onChangeModes((prev) => ({ ...prev, [index]: mode }));
    if (mode === "exclude" && coverIndex === index) {
      const fallback = preview.pages.find((p) => p.index !== index && modes[p.index] !== "exclude");
      if (fallback) onChangeCoverIndex(fallback.index);
    }
  };

  const counts = useMemo(() => {
    const c = { text: 0, image: 0, toc: 0, exclude: 0 };
    Object.values(modes).forEach((m) => c[m]++);
    return c;
  }, [modes]);

  const handleConfirm = () => {
    const excludedPages = Object.entries(modes).filter(([, m]) => m === "exclude").map(([i]) => Number(i));
    const imagePages = Object.entries(modes).filter(([, m]) => m === "image").map(([i]) => Number(i));
    const tocPages = Object.entries(modes).filter(([, m]) => m === "toc").map(([i]) => Number(i));
    onConfirm(excludedPages, coverIndex, imagePages, tocPages);
  };

  const modeLabel = { text: "Metin", image: "Görsel", toc: "İçindekiler", exclude: "Hariç" };
  // Converting before OCR has written the text layer would read pages that
  // still have no words on them.
  const ocrRunning = ocrJob?.state === "running";

  return (
    <div className="page-review">
      <div className="page-review__header">
        <div>
          <h1>Sayfaları gözden geçir</h1>
          <p className="page-review__hint">
            {preview.page_count} sayfa tarandı ve her biri için bir mod önerildi —
            <strong> {counts.text} Metin</strong>, <strong>{counts.image} Görsel</strong>,
            <strong> {counts.toc} İçindekiler</strong>, <strong>{counts.exclude} Hariç</strong>.
            Genelde elle değiştirmeniz gerekmez, ama her sayfanın altındaki
            düğmelerden istediğiniz zaman değiştirebilirsiniz. Kitaplık kapağı
            için de bir sayfa işaretli geliyor — değiştirmek isterseniz "Kapak yap"a basın.
          </p>
        </div>
        <div className="page-review__actions">
          {onChangeAutoFigures && (
            <label className="page-review__auto-figures" title="Metnin arasındaki fotoğraf ve şekilleri bulup, sayfanın metnini koruyarak kitaba yerleştirir">
              <input
                type="checkbox"
                checked={autoFigures !== false}
                onChange={(e) => onChangeAutoFigures(e.target.checked)}
              />
              Sayfa içi görselleri otomatik çıkar
            </label>
          )}
          {onOpenPdfEditor && (
            <details className="page-review__advanced">
              <summary>Gelişmiş</summary>
              <div className="page-review__advanced-body">
                <p>
                  Belirli bir sayfada elle düzeltme gerekirse: üst/alt bilgi bandı, resim olarak alınacak ya da
                  metne katılmayacak bölge, bölgesel OCR. Çoğu kitapta gerekmez; girip çıkmak seçimleri korur.
                </p>
                <button className="btn" onClick={onOpenPdfEditor}>PDF Editörü</button>
              </div>
            </details>
          )}
          <button
            className="btn btn--primary"
            onClick={handleConfirm}
            disabled={isConverting || ocrRunning}
            title={ocrRunning ? "Sayfalar okunurken dönüştürülürse metin çıkmaz — OCR'ın bitmesini bekleyin" : undefined}
          >
            {isConverting
              ? (conversionProgress?.stage
                ? `${conversionProgress.stage}${conversionProgress.total ? ` · ${conversionProgress.done}/${conversionProgress.total}` : ""}…`
                : "Dönüştürülüyor…")
              : ocrRunning
                ? "OCR bekleniyor…"
                : `Dönüştürmeye Başla (${counts.text + counts.image + counts.toc} sayfa)`}
          </button>
        </div>
      </div>

      {ocrJob && ocrJob.state !== "done" && (
        <div className={`page-review__ocr page-review__ocr--${ocrJob.state}`}>
          {ocrJob.state === "running" ? (
            <>
              <span className="page-review__ocr-title">
                {OCR_REASON_TITLE[ocrJob.reason] || OCR_REASON_TITLE.scan}
              </span>
              <span className="page-review__ocr-count">
                {ocrJob.done}/{ocrJob.total} sayfa
              </span>
              <span className="page-review__ocr-bar">
                <span style={{ transform: `scaleX(${ocrJob.total ? ocrJob.done / ocrJob.total : 0})` }} />
              </span>
              <span className="page-review__ocr-note">
                Bitince sayfa önerileri yenilenir. Beklemeden devam ederseniz metin çıkmayabilir.
              </span>
              {onSkipOcr && (
                <button className="btn" onClick={onSkipOcr}>
                  Beklemeden devam et
                </button>
              )}
            </>
          ) : (
            <>
              <span className="page-review__ocr-title">
                {ocrJob.state === "unavailable" ? "Bu PDF taranmış, metin çıkarılamıyor" : "OCR tamamlanamadı"}
              </span>
              <span className="page-review__ocr-note">{ocrJob.message}</span>
              {onSkipOcr && (
                <button className="btn" onClick={onSkipOcr}>
                  Anladım
                </button>
              )}
            </>
          )}
        </div>
      )}

      <div className="page-review__grid">
        {preview.pages.map((p) => {
          const mode = modes[p.index];
          const isCover = coverIndex === p.index && mode !== "exclude";
          return (
            <div
              key={p.index}
              className={`page-thumb page-thumb--${mode} ${isCover ? "page-thumb--cover" : ""}`}
            >
              <div className="page-thumb__img-wrap" title={p.text_snippet}>
                <img src={`data:image/png;base64,${p.thumbnail_base64}`} alt={`Sayfa ${p.index + 1}`} />
              </div>

              <div className="page-thumb__modes">
                {["text", "image", "toc", "exclude"].map((m) => (
                  <button
                    key={m}
                    className={`page-thumb__mode-btn ${mode === m ? "page-thumb__mode-btn--active" : ""}`}
                    onClick={() => setMode(p.index, m)}
                  >
                    {modeLabel[m]}
                  </button>
                ))}
              </div>

              {mode !== "exclude" && (
                <button
                  className="page-thumb__cover-btn"
                  onClick={() => onChangeCoverIndex(p.index)}
                  disabled={isCover}
                >
                  {isCover ? "★ Kapak" : "Kapak yap"}
                </button>
              )}

              <div className="page-thumb__badge">
                {mode === "exclude" ? "Hariç tutuldu" : `Sayfa ${p.index + 1}`}
              </div>
              {p.likely_junk && mode !== "exclude" && <div className="page-thumb__flag">Şüpheli</div>}
              {issuePages.has(p.index) && mode !== "exclude" && (
                <div className="page-thumb__flag page-thumb__flag--issue" title="Bu sayfada bozuk görünen bir başlık tespit edildi">
                  ⚠ Başlık
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
