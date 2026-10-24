import React, { useMemo, useState } from "react";
import { planWords, writeWords } from "../api";
import NoteChanges from "./NoteChanges";

// Kelime Defteri: the words looked up on the Kindle (its Vocabulary Builder),
// each with the sentence it stood in, its printed page and its meaning from
// the Turkish Wiktionary, written into one vault note on the reader's click.

function Sentence({ text, word }) {
  if (!text) return null;
  const at = text.toLocaleLowerCase("tr").indexOf(word.toLocaleLowerCase("tr"));
  if (at < 0) return <span>“{text}”</span>;
  return (
    <span>“{text.slice(0, at)}<strong>{text.slice(at, at + word.length)}</strong>{text.slice(at + word.length)}”</span>
  );
}

export default function WordNotebook({ data, vaultOk, busy, run, onWritten }) {
  const words = data?.words || [];
  const fresh = words.filter((w) => !w.in_note);
  const [off, setOff] = useState(new Set());
  const [plan, setPlan] = useState(null);
  const [result, setResult] = useState(null);

  const books = useMemo(() => {
    const out = [];
    for (const w of words) {
      let b = out.find((x) => x.name === w.book);
      if (!b) out.push((b = { name: w.book, words: [] }));
      b.words.push(w);
    }
    return out;
  }, [words]);

  const include = () => fresh.filter((w) => !off.has(w.id)).map((w) => w.id);
  const preview = () => run("words-plan", async () => { setResult(null); setPlan(await planWords(include())); });
  const write = () => run("words-write", async () => {
    const r = await writeWords(include(), plan.token);
    setResult(r);
    setPlan(null);
    onWritten?.();
  });
  const toggle = (id) => {
    const next = new Set(off);
    next.has(id) ? next.delete(id) : next.add(id);
    setOff(next);
    setPlan(null);
  };

  return (
    <>
      <div className="notebook__head">
        <div>
          <h2>Kelime Defteri</h2>
          <p className="notebook__book-meta">
            Kindle'da sözlükte baktığın kelimeler, geçtikleri cümle ve sayfayla. Anlamlar Türkçe Vikisözlük'ten.
            {words.length ? ` · ${words.length} kelime, ${fresh.length} yeni` : ""}
          </p>
        </div>
      </div>

      {!data?.dictionary && (
        <p className="notebook__warn">Türkçe sözlük bu bilgisayarda henüz yok; anlamlar boş kalır.</p>
      )}
      {words.length === 0 && (
        <p className="notebook__empty">
          Henüz kelime yok. Kindle'da bir kelimeye basılı tutup anlamına baktığında buraya gelir. Türkçe kitaplarda
          bunun için Matbaa'nın Türkçe sözlüğü Kindle'da olmalı (yukarıdaki “Kindle'ım” kartından).
        </p>
      )}

      {books.map((b) => (
        <section key={b.name} className="words__book">
          <h3>{b.name}</h3>
          <ol className="notebook__items">
            {b.words.map((w) => (
              <li key={w.id} className={`hl ${off.has(w.id) && !w.in_note ? "hl--off" : ""}`}>
                <label className="hl__keep" title={w.in_note ? "Notta" : off.has(w.id) ? "Ekle" : "Bunu yazma"}>
                  <input type="checkbox" checked={w.in_note || !off.has(w.id)} disabled={w.in_note}
                         onChange={() => toggle(w.id)} />
                </label>
                <div className="hl__body">
                  <p className="word__head">
                    <strong>{w.word}</strong>
                    {w.headword && w.headword.toLocaleLowerCase("tr") !== w.word.toLocaleLowerCase("tr") && (
                      <span className="word__lemma"> ({w.headword})</span>
                    )}
                    {w.meaning && <span className="word__meaning"> — {w.meaning}</span>}
                  </p>
                  {w.sentence && <p className="word__sentence"><Sentence text={w.sentence} word={w.word} /></p>}
                  <div className="hl__meta">
                    {w.page && <span>s. {w.page}</span>}
                    {w.added && <span>{new Date(w.added).toLocaleDateString("tr-TR")}</span>}
                    {w.in_note && <span className="badge badge--soft">notta</span>}
                    {w.learnt && <span className="badge">öğrenildi</span>}
                  </div>
                </div>
              </li>
            ))}
          </ol>
        </section>
      ))}

      {words.length > 0 && (
        <div className="notebook__footer">
          {!plan && !result && (
            <button className="btn btn--primary" disabled={!!busy || !vaultOk || include().length === 0}
                    onClick={preview}>
              {busy === "words-plan" ? "Hazırlanıyor…" : fresh.length ? "Kelime Defteri'ni önizle" : "Hepsi notta"}
            </button>
          )}
          {!vaultOk && <span className="notebook__hint">Önce Obsidian kasasını seç.</span>}
          {plan && (
            <div className="plan">
              <p className="plan__summary">
                <strong>{plan.file.name}</strong> {plan.file.exists ? "notuna" : "yeni not olarak"} {plan.added} kelime
                eklenecek{plan.already ? `, ${plan.already} zaten notta` : ""}. Notunda yazdıkların değişmez.
              </p>
              <details className="plan__diff" open={!plan.file.exists}>
                <summary>{plan.file.exists ? "Notuna eklenecekler" : "Notun tamamı"}</summary>
                {plan.file.exists ? <NoteChanges diff={plan.file.diff} /> : <pre>{plan.file.text}</pre>}
              </details>
              <div className="modal-actions">
                <button className="btn" onClick={() => setPlan(null)}>Geri</button>
                <button className="btn btn--primary" onClick={write} disabled={!!busy || !plan.file.diff}>
                  {busy === "words-write" ? "Yazılıyor…" : "Obsidian'a yaz"}
                </button>
              </div>
            </div>
          )}
          {result && (
            <div className="plan">
              <p className="plan__summary">
                {result.written.length ? `Yazıldı: ${result.written.map((p) => p.split(/[\\/]/).pop()).join(", ")}`
                  : "Yazılacak yeni bir şey yoktu."}
              </p>
              {result.conflicts.length > 0 && (
                <p className="modal-panel__error">
                  Not önizlemeden sonra değiştiği için yazılmadı; önizlemeyi yenileyip tekrar dene.
                </p>
              )}
              <button className="btn" onClick={() => setResult(null)}>Tamam</button>
            </div>
          )}
        </div>
      )}
    </>
  );
}
