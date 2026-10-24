import React, { useState } from "react";
import { askBook, checkAnswer, planAsk, writeAsk } from "../api";
import LlmSettings from "./LlmSettings";
import NoteChanges from "./NoteChanges";

// Kitapla sohbet: a question finds its passages in the book (or in every saved
// book); the passages and the question go to ChatGPT (copied) or to a
// configured model; the answer is checked against the book — its quotations
// must be the book's words, on the pages cited — and can be kept in the book's
// note, the question as the reader's own open task, the answer in the vault's
// collapsed AI box.
// Without a book (opened from the Okuma Defteri) it searches every saved book.
export default function AskModal({ session = null, onClose }) {
  const [question, setQuestion] = useState("");
  const [everywhere, setEverywhere] = useState(!session);
  const [result, setResult] = useState(null);
  const [answer, setAnswer] = useState("");
  const [verdict, setVerdict] = useState(null);
  const [plan, setPlan] = useState(null);
  const [written, setWritten] = useState(null);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const [flash, setFlash] = useState(null);
  const [settings, setSettings] = useState(false);

  const scope = () => ({ question, session_id: everywhere || !session ? null : session.session_id });
  const run = async (label, fn) => {
    setBusy(label);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError(e.message);
      return null;
    } finally {
      setBusy(null);
    }
  };
  const find = () => run("find", async () => {
    setVerdict(null); setPlan(null); setWritten(null); setAnswer("");
    setResult(await askBook(scope()));
  });
  const byModel = () => run("model", async () => {
    const r = await askBook({ ...scope(), model: true });
    setResult(r);
    setAnswer(r.answer || "");
    setVerdict(r.check || null);
  });
  const verify = () => run("check", async () => setVerdict(await checkAnswer({ ...scope(), answer })));
  const preview = () => run("plan", async () => setPlan(await planAsk({ ...scope(), answer })));
  const write = () => run("write", async () => {
    setWritten(await writeAsk({ ...scope(), answer, token: plan.token }));
    setPlan(null);
  });
  const copyPrompt = () => {
    navigator.clipboard?.writeText(result.prompt).then(
      () => setFlash("İstek kopyalandı — ChatGPT'ye yapıştır, yanıtını aşağıya getir"),
      () => setFlash("Kopyalanamadı"));
    setTimeout(() => setFlash(null), 3500);
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-panel modal-panel--wide" role="dialog" aria-label="Kitaba sor" onClick={(e) => e.stopPropagation()}>
        <h2>{session ? "Kitaba sor" : "Kitaplığıma sor"}</h2>
        <textarea className="ask__question" rows={2} value={question} placeholder="ör. Yazar müşterekleri nasıl tanımlıyor?"
                  onChange={(e) => setQuestion(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && question.trim()) { e.preventDefault(); find(); } }} />
        <div className="ask__row">
          {session ? (
            <label className="workbench__notes-toggle">
              <input type="checkbox" checked={everywhere} onChange={(e) => setEverywhere(e.target.checked)} />
              bütün kitaplarımda
            </label>
          ) : <span className="notebook__hint">Matbaa'da kayıtlı bütün kitaplarında arar.</span>}
          <button className="btn btn--primary" disabled={!question.trim() || !!busy} onClick={find}>
            {busy === "find" ? "Aranıyor…" : "Kitapta ara"}
          </button>
        </div>

        {result && (
          <>
            {result.passages.length === 0 && <p className="modal-panel__hint">Bu soruyla ilgili bir pasaj bulunamadı.</p>}
            <ol className="ask__passages">
              {result.passages.map((p, k) => (
                <li key={`${p.session_id}-${p.block}`}>
                  <span className="ask__where">
                    [{k + 1}] {everywhere ? `${p.book_title} · ` : ""}{p.page ? `s. ${p.page}` : "sayfasız"} · {p.chapter_title}
                  </span>
                  <span className="ask__text">{p.text}</span>
                </li>
              ))}
            </ol>
            {result.passages.length > 0 && (
              <div className="ask__row">
                <button className="btn" onClick={copyPrompt}>İsteği kopyala (ChatGPT için)</button>
                {result.llm ? (
                  <button className="btn" disabled={!!busy} onClick={byModel}>
                    {busy === "model" ? "Model yanıtlıyor…" : "Model yanıtlasın"}
                  </button>
                ) : (
                  <button className="modal-link" onClick={() => setSettings(true)}
                          title="İsteğe bağlı: kendi API anahtarın ya da bu bilgisayardaki bir model">
                    dil modeli ayarla
                  </button>
                )}
              </div>
            )}
            {flash && <p className="modal-panel__hint">{flash}</p>}
            {result.passages.length > 0 && (
              <>
                <textarea className="ask__answer" rows={5} value={answer} placeholder="ChatGPT'nin yanıtını buraya yapıştır"
                          onChange={(e) => { setAnswer(e.target.value); setVerdict(null); setPlan(null); }} />
                <div className="ask__row">
                  <button className="btn" disabled={!answer.trim() || !!busy} onClick={verify}>Kitapla denetle</button>
                  {!everywhere && (
                    <button className="btn" disabled={!answer.trim() || !!busy} onClick={preview}>Kitabın notuna kaydet…</button>
                  )}
                </div>
              </>
            )}
            {verdict && (
              <div className="ask__verdict">
                {verdict.uncited && <p className="modal-panel__error">Yanıt hiçbir sayfa göstermiyor (kaynaksız).</p>}
                {verdict.quotes.length === 0 && !verdict.uncited && <p className="modal-panel__hint">Yanıtta alıntı yok.</p>}
                {verdict.quotes.map((q, i) => (
                  <p key={i} className={q.found && q.page_ok !== false ? "ask__ok" : "ask__bad"}>
                    {q.found ? (q.page_ok === false ? "⚠" : "✓") : "✗"} “{q.text}” —{" "}
                    {q.found ? `kitapta, s. ${q.page || "?"}${q.page_ok === false ? " (yanıt başka sayfa gösteriyor)" : ""}`
                      : "kitapta bulunamadı"}
                  </p>
                ))}
              </div>
            )}
            {plan && (
              <div className="plan">
                <p className="plan__summary">
                  <strong>{plan.file.name}</strong> {plan.file.exists ? "notuna" : "yeni not olarak"}: soru açık bir
                  görev olarak, yanıt kapalı “Yardımcı bağlam · AI” kutusunda. Notunda yazdıkların değişmez.
                </p>
                <details className="plan__diff" open>
                  <summary>{plan.file.exists ? "Notuna eklenecekler" : "Notun tamamı"}</summary>
                  {plan.file.exists ? <NoteChanges diff={plan.file.diff} /> : <pre>{plan.file.text}</pre>}
                </details>
                <div className="modal-actions">
                  <button className="btn" onClick={() => setPlan(null)}>Geri</button>
                  <button className="btn btn--primary" disabled={!!busy || !plan.file.diff} onClick={write}>
                    {busy === "write" ? "Yazılıyor…" : "Obsidian'a yaz"}
                  </button>
                </div>
              </div>
            )}
            {written && (
              <p className="modal-panel__hint">
                {written.written.length ? `Yazıldı: ${written.written.map((p) => p.split(/[\\/]/).pop()).join(", ")}`
                  : written.conflicts.length ? "Not önizlemeden sonra değişti; yeniden önizle." : "Yazılacak yeni bir şey yoktu."}
              </p>
            )}
          </>
        )}
        {error && <p className="modal-panel__error">{error}</p>}
        <div className="modal-actions">
          <button className="btn" onClick={onClose}>Kapat</button>
        </div>
        {settings && (
          <LlmSettings onClose={() => setSettings(false)}
                       onSaved={(st) => setResult((r) => (r ? { ...r, llm: !!st?.available } : r))} />
        )}
      </div>
    </div>
  );
}
