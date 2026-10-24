import React, { useState } from "react";
import BookReport from "./BookReport";

// Ranks a warning list the same way the converter itself does: content
// loss / a wrong chapter boundary first, a real-but-not-lossy defect next,
// a tolerated cosmetic note last — so the person reads the two or three
// entries that actually need attention before the rest, instead of a flat
// list where "the book lost a chapter" and "the language guess is unsure"
// look equally urgent.
const SEVERITY_ORDER = { critical: 0, warning: 1, info: 2 };
const SEVERITY_LABEL = { critical: "Kritik", warning: "Uyarı", info: "Bilgi" };

export default function ChapterList({
  chapters, selectedId, onSelect, warnings, chapterWarnings, onReorder, report, sessionId,
  onBeforeModel, onModelApplied,
}) {
  const [dragId, setDragId] = useState(null);
  const [overId, setOverId] = useState(null);

  const canReorder = typeof onReorder === "function";

  const reset = () => {
    setDragId(null);
    setOverId(null);
  };

  const handleDragStart = (chapterId) => (e) => {
    setDragId(chapterId);
    e.dataTransfer.effectAllowed = "move";
    // Firefox requires data to be set for drag to actually start
    e.dataTransfer.setData("text/plain", chapterId);
  };

  const handleDragOver = (chapterId) => (e) => {
    if (dragId === null) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    if (overId !== chapterId) setOverId(chapterId);
  };

  // Always recompute positions from the CURRENT `chapters` prop, never
  // from a remembered array index — if an unrelated autosave refreshed
  // the chapter list mid-drag, a stale numeric index could point at the
  // wrong chapter and silently duplicate or drop one on splice.
  const handleDrop = (targetId) => (e) => {
    e.preventDefault();
    if (!dragId || dragId === targetId) {
      reset();
      return;
    }
    const order = chapters.map((c) => c.id);
    const fromIdx = order.indexOf(dragId);
    const toIdx = order.indexOf(targetId);
    reset();
    if (fromIdx === -1 || toIdx === -1) return; // one of them no longer exists — bail out safely
    const reordered = [...order];
    const [moved] = reordered.splice(fromIdx, 1);
    reordered.splice(toIdx, 0, moved);
    onReorder(reordered);
  };

  // Computed before the chapter list, not after: on a book with dozens of
  // chapters the warnings panel used to sit below all of them, so the one
  // thing most worth seeing first — a critical, content-loss-shaped
  // warning — was the thing most likely to need scrolling past a whole
  // table of contents to even discover existed.
  const linkedMessages = new Set((chapterWarnings || []).map((cw) => cw.message));
  const unlinkedWarnings = (warnings || []).filter((w) => !linkedMessages.has(w.message));
  const warningEntries = [
    ...(chapterWarnings || []).map((cw, i) => ({
      key: `cw-${i}`,
      message: cw.message,
      severity: cw.severity || "warning",
      chapterId: cw.chapter_id,
    })),
    ...unlinkedWarnings.map((w, i) => ({
      key: `w-${i}`,
      message: w.message,
      severity: w.severity || "warning",
      chapterId: null,
    })),
  ];
  // Stable sort: entries of equal severity keep the order the converter
  // produced them in (each check's own internal ordering already means
  // something — e.g. worst-first within a check).
  warningEntries.sort((a, b) => (SEVERITY_ORDER[a.severity] ?? 1) - (SEVERITY_ORDER[b.severity] ?? 1));
  const warningCounts = warningEntries.reduce((acc, e) => {
    acc[e.severity] = (acc[e.severity] || 0) + 1;
    return acc;
  }, {});

  return (
    <div className="chapter-rail">
      <BookReport
        report={report}
        sessionId={sessionId}
        chapters={chapters}
        onSelectChapter={onSelect}
        onBeforeModel={onBeforeModel}
        onModelApplied={onModelApplied}
      />
      {warningEntries.length > 0 && (
        <div className="chapter-rail__warnings">
          <p className="chapter-rail__warnings-title">
            Ayrıştırıcı notları
            <span className="chapter-rail__warnings-counts">
              {Object.keys(SEVERITY_LABEL)
                .filter((s) => warningCounts[s])
                .map((s) => (
                  <span
                    key={s}
                    className={`chapter-rail__warning-count chapter-rail__warning-count--${s}`}
                    title={`${warningCounts[s]} ${SEVERITY_LABEL[s]}`}
                  >
                    {warningCounts[s]}
                  </span>
                ))}
            </span>
          </p>
          <ul>
            {warningEntries.map((e) => (
              <li key={e.key} className={`chapter-rail__warning-item chapter-rail__warning-item--${e.severity}`}>
                {e.chapterId ? (
                  <button className="chapter-rail__warning-link" onClick={() => onSelect(e.chapterId)}>
                    {e.message}
                  </button>
                ) : (
                  <span>{e.message}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="chapter-rail__label">
        İçindekiler
        {canReorder && <span className="chapter-rail__reorder-hint">sürükleyip sıralayın</span>}
      </div>
      <ol className="chapter-rail__list">
        {chapters.map((ch, i) => {
          // The book's own parts ("1. BÖLÜM") head the chapters under them,
          // as the printed contents page does.
          const section = (ch.toc_path || [])[0] || null;
          const prevSection = i > 0 ? ((chapters[i - 1].toc_path || [])[0] || null) : null;
          const nested = Boolean(section) && ch.kind !== "image";
          return (
          <React.Fragment key={ch.id}>
          {section && section !== prevSection && (
            <li className="chapter-rail__section" aria-hidden="true">{section}</li>
          )}
          <li
            key={ch.id}
            draggable={canReorder}
            onDragStart={canReorder ? handleDragStart(ch.id) : undefined}
            onDragOver={canReorder ? handleDragOver(ch.id) : undefined}
            onDrop={canReorder ? handleDrop(ch.id) : undefined}
            onDragEnd={canReorder ? reset : undefined}
            className={[
              "chapter-rail__li",
              nested ? "chapter-rail__li--nested" : "",
              ch.kind === "image" ? "chapter-rail__li--image" : "",
              dragId === ch.id ? "chapter-rail__li--dragging" : "",
              overId === ch.id && dragId !== ch.id ? "chapter-rail__li--over" : "",
            ].join(" ").trim()}
          >
            {canReorder && <span className="chapter-rail__handle" aria-hidden="true">⠿⠿</span>}
            <button
              className={`chapter-rail__item ${ch.id === selectedId ? "chapter-rail__item--active" : ""}`}
              onClick={() => onSelect(ch.id)}
            >
              <span className="chapter-rail__title">
                {ch.is_split_continuation ? `${ch.title} (devamı)` : ch.title}
                {ch.kind === "toc" && <em className="chapter-rail__kind"> · İçindekiler</em>}
                {ch.kind === "frontmatter" && <em className="chapter-rail__kind"> · Ön Bilgi</em>}
                {ch.kind === "image" && <em className="chapter-rail__kind"> · Görsel, menüde yok</em>}
              </span>
              {ch.footnotes.length > 0 && (
                <span className="chapter-rail__badge">{ch.footnotes.length}</span>
              )}
            </button>
          </li>
          </React.Fragment>
          );
        })}
      </ol>
    </div>
  );
}
