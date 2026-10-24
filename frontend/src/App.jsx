import React, { useCallback, useEffect, useRef, useState } from "react";
import ReadingNotebook from "./components/ReadingNotebook";
import UploadModule from "./components/UploadModule.jsx";
import PageReview from "./components/PageReview.jsx";
import Workbench from "./components/Workbench.jsx";
import PdfEditorPage from "./components/editor/PdfEditorPage.jsx";
import LibraryPage from "./components/LibraryPage.jsx";
import UiSwitch, { UiModeContext, useUiMode } from "./components/UiSwitch.jsx";
import {
  uploadPdf,
  startOcr,
  cancelOcr,
  fetchOcrStatus,
  convertPdf,
  convertProgress,
  updateChapter,
  updateMeta,
  exportEpub,
  splitChapter,
  reorderChapters,
  getSession,
} from "./api.js";

// The one piece of state genuinely worth surviving an accidental reload:
// once conversion succeeds, the session already lives server-side
// (session_store.py, in-memory) under this id — GET /api/session/{id}
// already exists for exactly this. Everything *before* conversion
// (the upload's page thumbnails, Page Review/PDF Editor choices) is not
// attempted here: it's materially larger (per-page thumbnail images) and
// there is no existing endpoint to re-derive it from just an upload id,
// so recovering it would mean adding new backend surface rather than
// reusing what's already there.
const SESSION_STORAGE_KEY = "matbaa:sessionId";

export default function App() {
  const [stage, setStage] = useState("upload"); // upload -> reviewing -> pdfEditor -> workbench
  const [uiMode, setUiMode] = useUiMode();
  const [preview, setPreview] = useState(null);
  const [session, setSession] = useState(null);
  const [maskRatios, setMaskRatiosState] = useState({ headerRatio: 0.045, footerRatio: 0.075 });
  // The mask lines are only an instruction once someone has dragged them.
  // Sending the defaults on every conversion made the backend crop the top
  // 4.5% of every page by position — deleting every section title printed
  // at the top of a page — instead of removing only what repeats.
  const [masksTouched, setMasksTouched] = useState(false);
  const setMaskRatios = useCallback((next) => {
    setMasksTouched(true);
    setMaskRatiosState(next);
  }, []);
  // On by default: a page's figures are part of the book, and hand-marking
  // every one of them per book is the work this replaces. The switch exists
  // so a book whose detection goes wrong has a way out that isn't deleting
  // figures one at a time in the Live Editor.
  const [autoFigures, setAutoFigures] = useState(true);
  // Lifted out of PageReview so navigating to the PDF Editor and back
  // doesn't wipe out manual Görsel/Metin/Hariç choices — PageReview used
  // to own this as local state, which meant it reset to the auto-suggested
  // defaults every time the component remounted.
  const [pageModes, setPageModes] = useState({});
  const [coverIndex, setCoverIndex] = useState(0);
  // Also lifted out of the PDF Editor for the same reason, and because
  // App.jsx is what actually calls /api/convert — region data (including
  // "Hariç Tut" boxes) needs to live somewhere the real conversion call
  // can reach it.
  const [regionsByPage, setRegionsByPage] = useState({});

  // A scanned PDF has no text until OCR has read it — see ocr_layer.py.
  // { state, done, total, message } while that pass runs on the server.
  const [ocrJob, setOcrJob] = useState(null);
  const ocrPollRef = useRef(null);

  const [isUploading, setIsUploading] = useState(false);
  const [isConverting, setIsConverting] = useState(false);
  // where a conversion is: {stage, done, total}, asked while it runs
  const [conversionProgress, setConversionProgress] = useState(null);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState(null);
  const [saveStatus, setSaveStatus] = useState("saved");
  const [isExporting, setIsExporting] = useState(false);
  const [isResuming, setIsResuming] = useState(true);

  // A converted session survives a reload — try to resume it before ever
  // showing the upload screen. A stale or missing id (backend restarted,
  // this is a genuinely fresh visit) just clears the key and falls
  // through to the normal upload flow; this is a silent best-effort, not
  // a user-facing failure.
  useEffect(() => {
    const savedId = sessionStorage.getItem(SESSION_STORAGE_KEY);
    if (!savedId) {
      setIsResuming(false);
      return;
    }
    let cancelled = false;
    getSession(savedId)
      .then((result) => {
        if (cancelled) return;
        setSession(result);
        setStage("workbench");
      })
      .catch(() => {
        sessionStorage.removeItem(SESSION_STORAGE_KEY);
      })
      .finally(() => {
        if (!cancelled) setIsResuming(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Nothing here survives a reload — the upload, every Page Review and PDF
  // Editor choice, and the converted session all live only in this
  // component's React state, with no localStorage/URL sync. A refresh or
  // an accidentally-closed tab past the upload screen silently discards
  // real work (drawn regions, approved OCR corrections, Live Editor
  // edits), so warn before letting the browser do that.
  useEffect(() => {
    if (stage === "upload") return;
    const handler = (e) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [stage]);

  // --- Request sequencing guard -----------------------------------------
  // Every mutating call (save, reorder, split, meta, bulk-replace) fetches
  // and applies the *entire* session from the server. If two of these are
  // in flight at once — e.g. you're still mid-autosave-debounce and you
  // drag-reorder the chapter list — their responses can arrive out of
  // order over a real network. Applying whichever one lands last, rather
  // than whichever was issued last, is exactly what silently reverted
  // edits and undid a reorder. issuedSeqRef/appliedSeqRef fixes that: a
  // response is only ever applied if no newer request has been issued
  // since, so a late, stale response is simply dropped instead of
  // clobbering fresher state.
  const issuedSeqRef = useRef(0);
  const appliedSeqRef = useRef(0);

  const beginRequest = () => ++issuedSeqRef.current;

  const applyIfCurrent = (seq, updatedSession) => {
    if (seq < appliedSeqRef.current) return false; // a newer request already landed
    appliedSeqRef.current = seq;
    setSession(updatedSession);
    return true;
  };

  // The page cards and their suggested modes, from an upload or from the
  // fresh read after OCR.
  // Pages and the cover the person has chosen by hand. A fresh read of the
  // pages (after OCR) updates every suggestion except these: finishing OCR
  // used to reset choices made while it ran.
  const touchedPagesRef = useRef(new Set());
  const coverTouchedRef = useRef(false);

  const changePageModes = useCallback((updater) => {
    setPageModes((prev) => {
      const next = typeof updater === "function" ? updater(prev) : updater;
      for (const k of Object.keys(next)) {
        if (next[k] !== prev[k]) touchedPagesRef.current.add(Number(k));
      }
      return next;
    });
  }, []);

  const changeCoverIndex = useCallback((index) => {
    coverTouchedRef.current = true;
    setCoverIndex(index);
  }, []);

  const applyPages = useCallback((pages, { keepChoices = false } = {}) => {
    if (!keepChoices) {
      touchedPagesRef.current = new Set();
      coverTouchedRef.current = false;
    }
    let modes = {};
    setPageModes((prev) => {
      modes = {};
      for (const p of pages) {
        modes[p.index] = keepChoices && touchedPagesRef.current.has(p.index)
          ? prev[p.index]
          : p.suggested_mode || "text";
      }
      return modes;
    });
    if (keepChoices && coverTouchedRef.current) return;
    // Prefer a page the backend already flagged as image-dominant
    // (almost always the real cover) over just "the first page".
    const suggested = {};
    for (const p of pages) suggested[p.index] = p.suggested_mode || "text";
    const firstImage = pages.find((p) => suggested[p.index] === "image");
    const firstIncluded = pages.find((p) => suggested[p.index] !== "exclude");
    setCoverIndex((firstImage || firstIncluded)?.index ?? 0);
  }, []);

  // A scanned PDF carries no text at all, so page review would suggest
  // "Görsel" for every page and converting would produce a book of
  // pictures with no words in it. OCR runs first, on the server, and the
  // page cards are then re-read from a PDF that has text on it.
  const watchOcr = useCallback(
    (uploadId) => {
      if (ocrPollRef.current) clearInterval(ocrPollRef.current);
      // The finished result is applied once and once only. Two polls can be
      // in flight at the end of a pass, and the second one landing after
      // the person has started marking pages threw their choices away.
      let applied = false;
      ocrPollRef.current = setInterval(async () => {
        try {
          const status = await fetchOcrStatus(uploadId);
          if (status.state === "done" || status.state === "error" || status.state === "unavailable") {
            if (ocrPollRef.current) {
              clearInterval(ocrPollRef.current);
              ocrPollRef.current = null;
            }
            if (applied) return;
            applied = true;
            setOcrJob(status);
            if (status.state === "done" && status.pages) {
              setPreview((prev) => (prev && prev.upload_id === uploadId ? { ...prev, pages: status.pages } : prev));
              applyPages(status.pages, { keepChoices: true });
            }
            return;
          }
          if (!applied) setOcrJob((prev) => ({ ...status, reason: prev?.reason }));
        } catch {
          // A poll that fails is not a failed OCR pass; the next one tells us.
        }
      }, 1500);
    },
    [applyPages]
  );

  useEffect(() => () => ocrPollRef.current && clearInterval(ocrPollRef.current), []);

  const handleFileSelected = useCallback(async (file) => {
    setError(null);
    setIsUploading(true);
    setProgress(0);
    setOcrJob(null);
    try {
      const result = await uploadPdf(file, setProgress);
      setPreview(result);
      applyPages(result.pages);
      setStage("reviewing");
      if (result.scanned_pages?.length) {
        if (!result.ocr_available) {
          setOcrJob({ state: "unavailable", done: 0, total: 0, message: result.ocr_message, reason: result.ocr_reason });
        } else {
          setOcrJob({ state: "running", done: 0, total: result.scanned_pages.length, message: null, reason: result.ocr_reason });
          startOcr(result.upload_id).catch(() => {});
          watchOcr(result.upload_id);
        }
      }
    } catch (err) {
      setError(err.message || "PDF yüklenirken bir sorun oluştu.");
    } finally {
      setIsUploading(false);
    }
  }, [applyPages, watchOcr]);

  const handleSkipOcr = useCallback(() => {
    if (ocrPollRef.current) {
      clearInterval(ocrPollRef.current);
      ocrPollRef.current = null;
    }
    if (preview?.upload_id && ocrJob?.state === "running") {
      cancelOcr(preview.upload_id).catch(() => {});
    }
    setOcrJob(null);
  }, [preview, ocrJob]);

  const handleConfirmPages = useCallback(
    async (excludedPages, coverPageIndex, imagePages, tocPages) => {
      if (!preview) return;
      setError(null);
      setIsConverting(true);
      let progressTimer = null;
      try {
        // Turn the PDF Editor's flat per-page region list into the three
        // shapes /api/convert expects — one per region action. An "ocr"
        // region only ever reaches here already approved: BoundingBoxLayer
        // only calls onAddRegion for one after the person reviewed the
        // candidate and pressed "Onayla".
        const excludedTextRegions = {};
        const imageRegions = [];
        const ocrRegions = [];
        for (const [pageIndexStr, regions] of Object.entries(regionsByPage)) {
          const pageIndex = Number(pageIndexStr);
          const excludeBboxes = [];
          for (const r of regions) {
            if (r.action === "exclude_text") {
              excludeBboxes.push(r.bbox);
            } else if (r.action === "image") {
              imageRegions.push({ page_index: pageIndex, bbox: r.bbox });
            } else if (r.action === "ocr") {
              ocrRegions.push({
                page_index: pageIndex,
                bbox: r.bbox,
                text: r.approvedText,
                confidence: r.confidence ?? null,
                source_text: r.sourceText ?? null,
              });
            }
          }
          if (excludeBboxes.length > 0) excludedTextRegions[pageIndexStr] = excludeBboxes;
        }
        const uploadId = preview.upload_id;
        progressTimer = setInterval(() => {
          convertProgress(uploadId).then(setConversionProgress).catch(() => {});
        }, 800);
        const result = await convertPdf(preview.upload_id, excludedPages, coverPageIndex, imagePages, tocPages, {
          headerMarginRatio: masksTouched ? maskRatios.headerRatio : null,
          footerMarginRatio: masksTouched ? maskRatios.footerRatio : null,
          excludedTextRegions,
          imageRegions,
          ocrRegions,
          autoFigures,
        });
        appliedSeqRef.current = beginRequest();
        setSession(result);
        setStage("workbench");
        sessionStorage.setItem(SESSION_STORAGE_KEY, result.session_id);
      } catch (err) {
        setError(err.message || "Dönüştürme sırasında bir sorun oluştu.");
      } finally {
        clearInterval(progressTimer);
        setConversionProgress(null);
        setIsConverting(false);
      }
    },
    [preview, maskRatios, masksTouched, regionsByPage, autoFigures]
  );

  const handleSaveChapter = useCallback(
    async (chapterId, patch) => {
      if (!session) return;
      setSaveStatus("saving");
      const seq = beginRequest();
      try {
        const updated = await updateChapter(session.session_id, chapterId, patch);
        applyIfCurrent(seq, updated);
        setSaveStatus("saved");
        return true;
      } catch {
        // Said plainly, with a way to retry: "Düzenleniyor" here used to
        // read as if nothing had gone wrong.
        setSaveStatus("error");
        return false;
      }
    },
    [session]
  );

  // A session the server already changed (a language model's corrections,
  // applied there) replaces the one on screen.
  const handleSessionReplace = useCallback(
    (updated) => {
      const seq = beginRequest();
      applyIfCurrent(seq, updated);
      setSaveStatus("saved");
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  const handleBulkReplace = useCallback(
    async (changedChapters) => {
      if (!session || changedChapters.length === 0) return;
      setSaveStatus("saving");
      const seq = beginRequest();
      try {
        let updated = session;
        for (const ch of changedChapters) {
          updated = await updateChapter(session.session_id, ch.id, {
            html: ch.html,
            title: ch.title,
            eyebrow: ch.eyebrow,
            footnotes: ch.footnotes,
          });
        }
        applyIfCurrent(seq, updated);
        setSaveStatus("saved");
      } catch {
        setSaveStatus("error");
      }
    },
    [session]
  );

  const handleSplitChapter = useCallback(
    async (chapterId, beforeHtml, afterHtml, newTitle) => {
      if (!session) return;
      const seq = beginRequest();
      const updated = await splitChapter(session.session_id, chapterId, beforeHtml, afterHtml, newTitle);
      applyIfCurrent(seq, updated);
      return updated;
    },
    [session]
  );

  const handleReorderChapters = useCallback(
    async (chapterIds) => {
      if (!session) return;
      setError(null);
      const seq = beginRequest();
      // Optimistic reorder so the drag feels instant; reconciled with the
      // server's response below (guarded, so a stale response can't
      // undo it if something else raced in after).
      const byId = Object.fromEntries(session.chapters.map((c) => [c.id, c]));
      setSession((s) => ({ ...s, chapters: chapterIds.map((id) => byId[id]) }));
      try {
        const updated = await reorderChapters(session.session_id, chapterIds);
        applyIfCurrent(seq, updated);
      } catch (err) {
        setError(err.message || "Sıralama kaydedilemedi.");
      }
    },
    [session]
  );

  const handleMetaChange = useCallback(
    async (patch) => {
      if (!session) return;
      const seq = beginRequest();
      setSession((s) => ({ ...s, ...patch }));
      try {
        const updated = await updateMeta(session.session_id, patch);
        applyIfCurrent(seq, updated);
      } catch {
        /* keep optimistic local state */
      }
    },
    [session]
  );

  const handleExport = useCallback(async (withNotes = false) => {
    if (!session) return;
    setError(null);
    setIsExporting(true);
    try {
      const name = `${session.book_title || "book"}${withNotes ? " (notlarımla)" : ""}.epub`;
      await exportEpub(session.session_id, name, withNotes === true);
    } catch (err) {
      setError(err.message || "Dışa aktarma başarısız oldu.");
    } finally {
      setIsExporting(false);
    }
  }, [session]);

  // The only other way out of the Workbench is a page reload — now behind
  // the beforeunload confirmation below, which is exactly the "are you
  // sure you want to leave this site" browser dialog a person shouldn't
  // need just to convert a second book. A converted session does survive
  // a reload now (see the resume effect above), but this is still a
  // plain reset rather than a "back": clearing the saved id here is what
  // stops a *later* fresh upload from being clobbered by the old session
  // resuming on the next reload.
  const handleStartOver = useCallback(() => {
    if (!window.confirm("Yeni bir PDF'e geçilsin mi? Bu kitap ve düzenlemeleriniz kaydedildi; açılış ekranındaki 'Son kitaplar' listesinden yeniden açabilirsiniz.")) {
      return;
    }
    sessionStorage.removeItem(SESSION_STORAGE_KEY);
    setStage("upload");
    setPreview(null);
    setSession(null);
    setPageModes({});
    setCoverIndex(0);
    setRegionsByPage({});
    setMaskRatiosState({ headerRatio: 0.045, footerRatio: 0.075 });
    setMasksTouched(false);
    setError(null);
  }, []);

  if (isResuming) {
    // Deliberately no spinner/branding here — this resolves in one local
    // network round-trip and either shows the Workbench or falls straight
    // through to the upload screen; a heavier loading state would flash
    // for a frame on every normal fresh visit for no benefit.
    return <div className="app-shell app-shell--resuming" aria-busy="true" />;
  }

  // a saved book, from the start screen's shelf or the library page
  const openProject = (id) => {
    getSession(id)
      .then((result) => {
        sessionStorage.setItem(SESSION_STORAGE_KEY, result.session_id);
        setSession(result);
        setStage("workbench");
      })
      .catch((e) => setError(e.message));
  };

  return (
    <UiModeContext.Provider value={uiMode}>
    <div className="app-shell" data-stage={stage}>
      <UiSwitch mode={uiMode} onChange={setUiMode} />
      {/* UploadModule renders `error` itself, embedded in its own layout —
          everywhere past it, a failure (a conversion that errored, an
          export that failed, a reorder the server rejected) used to just
          reset the button with no visible explanation at all, because
          nothing ever rendered `error` outside the upload screen. */}
      {error && stage !== "upload" && (
        <div className="app-error-banner" role="alert">
          <span>{error}</span>
          <button className="app-error-banner__dismiss" onClick={() => setError(null)} aria-label="Kapat">
            ×
          </button>
        </div>
      )}

      {stage === "upload" && (
        <UploadModule
          onFileSelected={handleFileSelected}
          onOpenProject={openProject}
          onOpenLibrary={() => { setError(null); setStage("library"); }}
          isConverting={isUploading}
          progress={progress}
          error={error}
          onOpenNotebook={() => { setError(null); setStage("notebook"); }}
        />
      )}

      {stage === "notebook" && <ReadingNotebook onBack={() => setStage("upload")} />}

      {stage === "library" && <LibraryPage onBack={() => setStage("upload")} onOpenProject={openProject} />}

      {stage === "reviewing" && preview && (
        <PageReview
          preview={preview}
          onConfirm={handleConfirmPages}
          isConverting={isConverting}
          conversionProgress={conversionProgress}
          onOpenPdfEditor={() => setStage("pdfEditor")}
          modes={pageModes}
          onChangeModes={changePageModes}
          ocrJob={ocrJob}
          onSkipOcr={handleSkipOcr}
          coverIndex={coverIndex}
          onChangeCoverIndex={changeCoverIndex}
          autoFigures={autoFigures}
          onChangeAutoFigures={setAutoFigures}
        />
      )}

      {stage === "pdfEditor" && preview && (
        <PdfEditorPage
          uploadId={preview.upload_id}
          pageCount={preview.page_count}
          ratios={maskRatios}
          onChangeRatios={setMaskRatios}
          onBack={() => setStage("reviewing")}
          pageModes={pageModes}
          regionsByPage={regionsByPage}
          onChangeRegions={setRegionsByPage}
        />
      )}

      {stage === "workbench" && session && (
        <Workbench
          session={session}
          onSaveChapter={handleSaveChapter}
          onBulkReplace={handleBulkReplace}
          onSessionReplace={handleSessionReplace}
          onSplitChapter={handleSplitChapter}
          onReorderChapters={handleReorderChapters}
          onMetaChange={handleMetaChange}
          onExport={handleExport}
          onStartOver={handleStartOver}
          saveStatus={saveStatus}
          isExporting={isExporting}
        />
      )}
    </div>
    </UiModeContext.Provider>
  );
}
