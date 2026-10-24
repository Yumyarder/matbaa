import React, { useEffect, useState } from "react";
import { fetchLlmStatus, llmApply, llmPropose, reportBundleUrl, validateEpub } from "../api";

const SEVERITY_LABEL = { critical: "kritik", error: "hata", warning: "uyarı", info: "bilgi" };

// The book's own report (app/diagnosis.py): what kind of PDF it was, what
// the engine did with it, and what it could not resolve. Collapsed to one
// line by default so it never pushes the chapter list out of reach.
//
// Where a language model is configured (app/llm.py), an issue marked for
// one can have its chapter checked: the model proposes, the server checks
// the proposals against the text, and nothing changes until "Uygula".
export default function BookReport({
  report, sessionId, chapters, onSelectChapter, onBeforeModel, onModelApplied,
}) {
  const [open, setOpen] = useState(false);
  const [model, setModel] = useState(null);
  const [review, setReview] = useState(null); // { chapterId, proposals, merges } | { chapterId, busy } | { error }

  useEffect(() => {
    fetchLlmStatus().then(setModel).catch(() => setModel(null));
  }, []);

  if (!report) return null;
  const issues = report.issues || [];
  const needsModel = issues.some((i) => i.llm);
  const titleOf = (id) => (chapters || []).find((c) => c.id === id)?.title || id;

  const askModel = async (chapterId) => {
    setReview({ chapterId, busy: true });
    try {
      await onBeforeModel?.();
      const res = await llmPropose(sessionId, chapterId);
      setReview({ chapterId, ...res });
    } catch (e) {
      setReview({ chapterId, error: e.message });
    }
  };

  const apply = async () => {
    const { chapterId, proposals } = review;
    setReview({ chapterId, busy: true });
    try {
      const updated = await llmApply(sessionId, chapterId, proposals);
      onModelApplied?.(updated);
      setReview(null);
    } catch (e) {
      setReview({ chapterId, error: e.message });
    }
  };

  return (
    <section className="book-report">
      <button
        type="button"
        className="book-report__head"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="book-report__title">Kitap raporu</span>
        <span className={`book-report__score book-report__score--${scoreBand(report.score)}`}>
          {report.score}
        </span>
        <span className="book-report__summary">
          {issues.length === 0 ? "sorun yok" : `${issues.length} konu`}
        </span>
        <span className="book-report__chevron" aria-hidden="true">{open ? "▴" : "▾"}</span>
      </button>

      {open && (
        <div className="book-report__body">
          <p className="book-report__kind">{report.kind}</p>
          {(report.strategy || []).length > 0 && (
            <ul className="book-report__strategy">
              {report.strategy.map((s, i) => <li key={i}>{s}</li>)}
            </ul>
          )}

          {issues.length > 0 && (
            <ul className="book-report__issues">
              {issues.map((issue) => (
                <li key={issue.code} className={`book-report__issue book-report__issue--${issue.severity}`}>
                  <p className="book-report__issue-message">
                    <span className="book-report__badge">{SEVERITY_LABEL[issue.severity] || issue.severity}</span>
                    {issue.llm && <span className="book-report__badge book-report__badge--llm">dil modeli</span>}
                    {issue.message}
                  </p>
                  <p className="book-report__issue-suggestion">{issue.suggestion}</p>
                  {(issue.samples || []).length > 0 && (
                    <ul className="book-report__samples">
                      {issue.samples.map((s, i) => <li key={i}>{s}</li>)}
                    </ul>
                  )}
                  <div className="book-report__actions">
                    {(issue.chapter_ids || []).length > 0 && onSelectChapter && (
                      <button
                        type="button"
                        className="book-report__goto"
                        onClick={() => onSelectChapter(issue.chapter_ids[0])}
                      >
                        İlk geçtiği bölüme git
                      </button>
                    )}
                    {issue.llm && model?.available && (issue.chapter_ids || []).length > 0 && (
                      <button
                        type="button"
                        className="book-report__goto"
                        disabled={review?.busy}
                        onClick={() => askModel(issue.chapter_ids[0])}
                      >
                        “{titleOf(issue.chapter_ids[0])}” bölümünü dil modeline denetlet
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}

          {review && (
            <div className="book-report__review" aria-live="polite">
              {review.busy && <p>Dil modeli “{titleOf(review.chapterId)}” bölümünü okuyor…</p>}
              {review.error && <p className="book-report__error">{review.error}</p>}
              {review.proposals && (
                <ModelProposals review={review} onApply={apply} onCancel={() => setReview(null)} />
              )}
            </div>
          )}

          <EpubCheck sessionId={sessionId} onBeforeCheck={onBeforeModel} />

          {needsModel && sessionId && (
            <p className="book-report__bundle">
              {model?.available
                ? `Dil modeli: ${model.provider} · ${model.model}. Metin yalnız siz bir bölüm için istediğinizde gönderilir. `
                : "Dil modeli ayarlı değil (~/.matbaa/llm.json). "}
              İsterseniz <a href={reportBundleUrl(sessionId)} download>sorun paketini indirin</a>{" "}
              (rapor ve ilgili metin parçaları, JSON) ve kullandığınız bir dil modeline verin.
            </p>
          )}
        </div>
      )}
    </section>
  );
}

// The EPUB checked as it would be exported: a valid EPUB 3, and nothing a
// Kindle ignores or rejects. Run on request — it builds the whole book.
function EpubCheck({ sessionId, onBeforeCheck }) {
  const [state, setState] = useState(null); // null | "busy" | result | { error }
  if (!sessionId) return null;
  const run = async () => {
    setState("busy");
    try {
      await onBeforeCheck?.();
      setState(await validateEpub(sessionId));
    } catch (e) {
      setState({ error: e.message });
    }
  };
  const result = state && state !== "busy" && !state.error ? state : null;
  return (
    <div className="book-report__check">
      <div className="book-report__actions">
        <button type="button" className="book-report__goto" onClick={run} disabled={state === "busy"}>
          {state === "busy" ? "EPUB doğrulanıyor…" : "EPUB'ı doğrula (EPUB 3 ve Kindle uyumu)"}
        </button>
      </div>
      {state?.error && <p className="book-report__error">{state.error}</p>}
      {result && (
        <>
          <p className={`book-report__issue-message${result.valid ? "" : " book-report__error"}`}>
            {result.valid ? "Geçerli EPUB" : "Geçersiz EPUB"} · {result.counts.error} hata,
            {" "}{result.counts.warning} uyarı, {result.counts.info} bilgi
            {result.epubcheck ? " (EPUBCheck dahil)" : ""}
          </p>
          {result.findings.length > 0 && (
            <ul className="book-report__issues">
              {result.findings.slice(0, 40).map((f, i) => (
                <li key={i} className={`book-report__issue book-report__issue--${f.severity === "error" ? "critical" : f.severity}`}>
                  <p className="book-report__issue-message">
                    <span className="book-report__badge">{SEVERITY_LABEL[f.severity] || f.severity}</span>
                    {f.message}
                  </p>
                  {f.file && <p className="book-report__issue-suggestion">{f.file}</p>}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}

function ModelProposals({ review, onApply, onCancel }) {
  const { proposals, merges } = review;
  const replaces = proposals.replace || [];
  const nothing = replaces.length === 0 && (merges || []).length === 0;
  return (
    <div>
      {nothing ? (
        <p>Dil modeli bu bölümde düzeltilecek bir şey önermedi.</p>
      ) : (
        <>
          {(merges || []).length > 0 && (
            <>
              <p className="book-report__issue-message">{merges.length} paragraf bir öncekinin devamı olarak birleşecek:</p>
              <ul className="book-report__samples">
                {merges.map((m) => <li key={m.index}>…{m.before} ¶ {m.after}…</li>)}
              </ul>
            </>
          )}
          {replaces.length > 0 && (
            <>
              <p className="book-report__issue-message">{replaces.length} kelime düzeltilecek:</p>
              <ul className="book-report__samples">
                {replaces.map((r, i) => <li key={i}>{r.wrong} → {r.right}</li>)}
              </ul>
            </>
          )}
        </>
      )}
      <div className="book-report__actions">
        {!nothing && <button type="button" className="btn btn--primary" onClick={onApply}>Uygula</button>}
        <button type="button" className="btn" onClick={onCancel}>{nothing ? "Kapat" : "Vazgeç"}</button>
      </div>
    </div>
  );
}

function scoreBand(score) {
  if (score >= 85) return "good";
  if (score >= 60) return "fair";
  return "poor";
}
