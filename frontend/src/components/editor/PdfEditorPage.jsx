import React, { useCallback, useEffect, useMemo, useState } from "react";
import PageCanvas from "./PageCanvas.jsx";
import KindleSimulator from "../KindleSimulator.jsx";
import { fetchScanIssues, fetchPagePreviewHtml } from "../../api.js";

export default function PdfEditorPage({
  uploadId,
  pageCount,
  ratios,
  onChangeRatios,
  onBack,
  pageModes = {},
  regionsByPage,
  onChangeRegions,
}) {
  const [pageIndex, setPageIndex] = useState(0);
  const [showHyphenHighlights, setShowHyphenHighlights] = useState(true);
  const [issues, setIssues] = useState([]);
  const [queueMode, setQueueMode] = useState(false);
  const [showLivePreview, setShowLivePreview] = useState(true);
  const [previewData, setPreviewData] = useState(null);
  const [previewError, setPreviewError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    fetchScanIssues(uploadId, ratios.headerRatio, ratios.footerRatio)
      .then((data) => {
        if (!cancelled) setIssues(data.issues || []);
      })
      .catch(() => {
        /* best-effort — "next problem" nav just won't have anything to jump to */
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uploadId, ratios.headerRatio, ratios.footerRatio]);

  useEffect(() => {
    if (!showLivePreview) return;
    let cancelled = false;
    setPreviewData(null);
    setPreviewError(null);
    fetchPagePreviewHtml(uploadId, pageIndex, ratios.headerRatio, ratios.footerRatio)
      .then((data) => {
        if (!cancelled) setPreviewData(data);
      })
      .catch((err) => {
        if (!cancelled) setPreviewError(err.message || "Önizleme yüklenemedi.");
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uploadId, pageIndex, showLivePreview, ratios.headerRatio, ratios.footerRatio]);

  const relevantIssues = useMemo(
    () => issues.filter((i) => pageModes[i.page_index] !== "image" && pageModes[i.page_index] !== "exclude"),
    [issues, pageModes]
  );
  const skippedIssueCount = issues.length - relevantIssues.length;
  const issuePages = useMemo(
    () => relevantIssues.map((i) => i.page_index).sort((a, b) => a - b),
    [relevantIssues]
  );
  const issueForCurrentPage = relevantIssues.find((i) => i.page_index === pageIndex);

  const currentRegions = regionsByPage[pageIndex] || [];

  const handleAddRegion = (region) => {
    // A region can arrive after the page has already changed (an OCR result
    // kept on navigation), so it names its own page when it knows it.
    const { pageIndex: regionPage, ...rest } = region;
    const target = regionPage ?? pageIndex;
    onChangeRegions((prev) => ({
      ...prev,
      [target]: [...(prev[target] || []), rest],
    }));
  };

  const handleRemoveRegion = (id) => {
    onChangeRegions((prev) => ({
      ...prev,
      [pageIndex]: (prev[pageIndex] || []).filter((r) => r.id !== id),
    }));
  };

  const totalRegionCount = useMemo(
    () => Object.values(regionsByPage).reduce((sum, list) => sum + list.length, 0),
    [regionsByPage]
  );

  // A flat, page-ordered view across the whole book — reviewing what's
  // been marked used to mean paging back through every page by hand (or
  // reading a raw correction.json dump); this is the same data the actual
  // conversion request is built from, just human-readable and jump-able.
  const allRegions = useMemo(() => {
    const list = [];
    for (const [pageIndexStr, regions] of Object.entries(regionsByPage)) {
      for (const region of regions) {
        list.push({ pageIndex: Number(pageIndexStr), region });
      }
    }
    list.sort((a, b) => a.pageIndex - b.pageIndex);
    return list;
  }, [regionsByPage]);

  const REGION_LABEL = { exclude_text: "Hariç Tut", image: "Görsel", ocr: "OCR" };

  const handleRemoveRegionAt = (targetPageIndex, id) => {
    onChangeRegions((prev) => ({
      ...prev,
      [targetPageIndex]: (prev[targetPageIndex] || []).filter((r) => r.id !== id),
    }));
  };

  const goToNextIssue = useCallback(() => {
    if (issuePages.length === 0) return;
    const next = issuePages.find((p) => p > pageIndex);
    setPageIndex(next !== undefined ? next : issuePages[0]); // wrap around
  }, [issuePages, pageIndex]);

  const goPrev = useCallback(() => setPageIndex((i) => Math.max(0, i - 1)), []);
  const goNext = useCallback(() => setPageIndex((i) => Math.min(pageCount - 1, i + 1)), [pageCount]);

  // In queue mode, resolving the auto-opened popup (confirm, tag as
  // image, or skip) advances straight to the next flagged page — the
  // whole point is not having to manually navigate between problems.
  const handleAutoResolved = useCallback(() => {
    goToNextIssue();
  }, [goToNextIssue]);

  // Keyboard shortcuts — only while not typing into a text field (the OCR
  // review textarea, in particular, needs arrow keys and 'n' for editing).
  useEffect(() => {
    const handler = (e) => {
      const tag = document.activeElement?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      if (e.key === "ArrowLeft") goPrev();
      else if (e.key === "ArrowRight") goNext();
      else if (e.key === "n" || e.key === "N") goToNextIssue();
      else if (e.key === "s" || e.key === "S") setQueueMode((q) => !q);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [goPrev, goNext, goToNextIssue]);

  const startQueue = () => {
    setQueueMode(true);
    if (issuePages.length > 0 && !issuePages.includes(pageIndex)) {
      setPageIndex(issuePages[0]);
    }
  };

  // KindleSimulator expects a chapter-shaped object — is_split_continuation:
  // true suppresses its own title/eyebrow rendering, since our preview HTML
  // already includes its own <h1>/<h2> headings inline.
  const previewChapter = useMemo(() => {
    if (!previewData) return null;
    return {
      title: `Sayfa ${pageIndex + 1}`,
      eyebrow: null,
      html: previewData.html,
      kind: "chapter",
      is_split_continuation: true,
    };
  }, [previewData, pageIndex]);

  return (
    <div className="pdf-editor-page">
      <div className="pdf-editor-page__header">
        <div>
          <h1>PDF Editörü <span className="pdf-editor-page__beta">BETA</span></h1>
          <p className="pdf-editor-page__hint">
            Üst ve alt çizgileri sürükleyerek "güvenli bölge"yi işaretleyin. Sarı vurgular,
            satır sonundaki tireleri kaldırılıp birleştirilecek kelimelerdir. Bir bölge
            çizmek için sayfa üzerinde sürükleyin, sonra "Görsel", "OCR" ya da metne
            hiç karışmaması için "Hariç Tut" seçin.
            <br />
            Kısayollar: ← → sayfa, N sonraki sorun, S tarama modunu aç/kapat.
            {skippedIssueCount > 0 && (
              <>
                <br />
                Sayfa İncelemesi'nde zaten Görsel/Hariç işaretlenmiş {skippedIssueCount} sayfa,
                tarama sonuçlarından otomatik çıkarıldı.
              </>
            )}
          </p>
        </div>
        <button className="btn btn--primary" onClick={onBack}>
          ← Sayfa İncelemesine Dön
        </button>
      </div>

      <div className="pdf-editor-demo">
        <div className="pdf-editor-demo__nav">
          <button onClick={goPrev} disabled={pageIndex === 0}>
            ← Önceki
          </button>
          <span>
            Sayfa {pageIndex + 1} / {pageCount}
            {issueForCurrentPage && <span className="pdf-editor-demo__issue-tag"> ⚠ olası bozuk başlık</span>}
          </span>
          <button onClick={goNext} disabled={pageIndex >= pageCount - 1}>
            Sonraki →
          </button>
          <button
            onClick={goToNextIssue}
            disabled={issuePages.length === 0}
            title="N tuşuyla da gidebilirsiniz"
          >
            Sonraki Sorun ({issuePages.length}) →
          </button>
          <button
            className={queueMode ? "pdf-editor-demo__queue-btn--active" : ""}
            onClick={() => (queueMode ? setQueueMode(false) : startQueue())}
            disabled={issuePages.length === 0}
            title="S tuşuyla da açıp kapatabilirsiniz"
          >
            {queueMode ? "Tarama Modu: Açık" : "Tara ve İncele"}
          </button>
          <label className="pdf-editor-demo__toggle">
            <input
              type="checkbox"
              checked={showHyphenHighlights}
              onChange={(e) => setShowHyphenHighlights(e.target.checked)}
            />
            Tireleme vurgusunu göster
          </label>
          <label className="pdf-editor-demo__toggle">
            <input
              type="checkbox"
              checked={showLivePreview}
              onChange={(e) => setShowLivePreview(e.target.checked)}
            />
            Canlı önizleme göster
          </label>
          {currentRegions.length > 0 && (
            <span className="pdf-editor-demo__region-count">
              bu sayfada {currentRegions.length} bölge
            </span>
          )}
        </div>

        <div className="pdf-editor-demo__workspace">
          <PageCanvas
            uploadId={uploadId}
            pageIndex={pageIndex}
            headerRatio={ratios.headerRatio}
            footerRatio={ratios.footerRatio}
            onChangeRatios={onChangeRatios}
            showHyphenHighlights={showHyphenHighlights}
            regions={currentRegions}
            onAddRegion={handleAddRegion}
            onRemoveRegion={handleRemoveRegion}
            autoBbox={queueMode && issueForCurrentPage ? issueForCurrentPage.bbox : null}
            autoBboxKey={queueMode ? pageIndex : null}
            onAutoResolved={handleAutoResolved}
          />

          {showLivePreview && (
            <div className="pdf-editor-demo__preview-col">
              {previewError && <p className="pdf-editor-demo__preview-error">{previewError}</p>}
              {!previewError && (
                <KindleSimulator css={previewData?.css || ""} chapter={previewChapter} />
              )}
              <p className="pdf-editor-demo__preview-note">
                Yaklaşık önizleme — sayfalar arası birleştirme, dipnot bağlama ve İçindekiler
                tespiti burada uygulanmıyor. Gerçek sonuç için tam dönüştürmeyi kullanın.
              </p>
            </div>
          )}
        </div>

        <p className="pdf-editor-demo__ratios">
          header_margin_ratio: {ratios.headerRatio.toFixed(4)} · footer_margin_ratio:{" "}
          {ratios.footerRatio.toFixed(4)} · toplam bölge: {totalRegionCount}
        </p>

        {allRegions.length > 0 && (
          <div className="pdf-editor-corrections">
            <p className="pdf-editor-corrections__title">Tüm Düzeltmeler ({allRegions.length})</p>
            <ul>
              {allRegions.map(({ pageIndex: rPageIndex, region }) => (
                <li key={region.id} className={`pdf-editor-corrections__row pdf-editor-corrections__row--${region.action}`}>
                  <button
                    className="pdf-editor-corrections__page-link"
                    onClick={() => setPageIndex(rPageIndex)}
                    title="Bu sayfaya git"
                  >
                    Sayfa {rPageIndex + 1}
                  </button>
                  <span className="pdf-editor-corrections__kind">{REGION_LABEL[region.action] || region.action}</span>
                  {region.action === "ocr" && (
                    <span className="pdf-editor-corrections__text" title={region.approvedText}>
                      "{(region.approvedText || "").slice(0, 60)}
                      {(region.approvedText || "").length > 60 ? "…" : ""}"
                      {region.confidence != null && region.confidence < 70 && (
                        <span className="pdf-editor-corrections__low-confidence" title="Düşük güven skoru">
                          {" "}⚠ {region.confidence}/100
                        </span>
                      )}
                    </span>
                  )}
                  <button
                    className="pdf-editor-corrections__remove"
                    onClick={() => handleRemoveRegionAt(rPageIndex, region.id)}
                    title="Bu düzeltmeyi kaldır"
                    aria-label="Kaldır"
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
