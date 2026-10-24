import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  askModel, fetchNotebook, fetchNotebookBook, fetchWords, importClippings, importFromKindle, kindleStatus,
  planNotebookBook, developPreview, developWrite, saveAnswer, saveNoteEdits,
  saveObsidianSettings, wordsFromKindle, writeNotebookBook,
} from "../api";
import obsidianMark from "../assets/obsidian-logo-gradient.svg";
import AskModal from "./AskModal";
import KindleCard from "./KindleCard";
import NoteChanges from "./NoteChanges";
import WordNotebook from "./WordNotebook";

// Obsidian's own mark, unaltered (obsidian.md/brand), beside its name only.
const ObsidianMark = () => <img className="obsidian-mark" src={obsidianMark} alt="" width="16" height="16" />;

const WORDS = "__kelimeler__";      // the Kelime Defteri, in the list beside the books

// Okuma Defteri (docs/MATBAA3.md, phase A): what the reader marked on the
// Kindle, placed in the book and written into their Obsidian vault in their
// own note format. Nothing is written before the reader has seen the plan.

function pageLabel(h) {
  const parts = [];
  if (h.page) parts.push(`s. ${h.page}`);
  const p = h.placement;
  if (p) parts.push([p.chapter_title, p.subheading].filter(Boolean).join(" / "));
  else if (h.section) parts.push(h.section);
  return parts.join(" · ");
}

function askPrompt(book, h) {
  const where = [h.placement?.chapter_title, h.page ? `s. ${h.page}` : null].filter(Boolean).join(", ");
  const passage = h.placement?.paragraph || h.quote || h.text;
  return [
    `"${book.title}"${book.author ? ` (${book.author})` : ""} kitabını okurken şu pasajda takıldım${where ? ` (${where})` : ""}:`,
    "",
    `> ${passage}`,
    "",
    h.text ? `Altını çizdiğim kısım: "${h.quote || h.text}"` : null,
    h.note ? `Notum: ${h.note}` : null,
    "",
    "Bu pasajı bana açıklar mısın? Yazarın burada ne demek istediğini ve geçen kavramları anlat; " +
      "emin olmadığın yerde bunu açıkça söyle, kitapta olmayan alıntı uydurma.",
  ].filter((l) => l !== null).join("\n");
}

function bookPack(book, items) {
  const lines = [
    `"${book.title}"${book.author ? ` (${book.author})` : ""} kitabından altını çizdiğim yerler ve notlarım aşağıda.`,
    "Bunlar üzerine benimle konuşmanı istiyorum: önce sorularımı yanıtla, sonra öne çıkan fikirleri ve " +
      "aralarındaki bağlantıları göster. Kitapta olmayan alıntı uydurma.",
    "",
  ];
  for (const h of items) {
    if (h.text) lines.push(`- "${h.quote || h.text}" (${pageLabel(h) || "yer yok"})`);
    if (h.note) lines.push(`  Notum${h.question ? " (soru)" : ""}: ${h.note}`);
  }
  return lines.join("\n");
}

const KIND_LABEL = { question: "soru", idea: "fikrim", link: "bağlantı", important: "önemli" };

function SignCard() {
  return (
    <details className="signs">
      <summary>Kindle işaret dili — notun ilk karakteri ne olduğunu söyler</summary>
      <ul>
        <li><code>?</code> soru — “Sorularım”a ve “Açık Sorular” sayfasına düşer</li>
        <li><code>!</code> kendi fikrim — notta <strong>Ben:</strong> diye yazılır, “Fikirlerim”de toplanır</li>
        <li><code>&gt;</code> bağlantı — <code>&gt; Gramsci, Hegemonya</code> → [[Gramsci]] · [[Hegemonya]]</li>
        <li><code>*</code> önemli — pasaj kalın yazılır</li>
        <li>İşaretsiz not olduğu gibi kalır; soru soruyorsa yine soru sayılır.</li>
      </ul>
    </details>
  );
}

// The answer the reader brought back for a question: pasted from ChatGPT
// (or proposed by a configured model), kept, and written into the note's
// collapsed "Yardımcı bağlam · AI" box on the next write.
function AnswerBox({ h, bookKey, llmOn, onSaved, setFlash }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(h.answer || "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const save = async (text, source = "chatgpt") => {
    setBusy(true);
    setErr(null);
    try {
      const r = await saveAnswer(h.id, text, source);
      onSaved(h.id, r.answer);
      setOpen(false);
      setFlash(text ? "Yanıt kaydedildi — bir sonraki yazmada notuna eklenecek" : "Yanıt kaldırıldı");
      setTimeout(() => setFlash(null), 2400);
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  const fromModel = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await askModel(bookKey, h.id);
      setDraft(r.answer);
      setOpen(true);
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  if (!open) {
    return (
      <div className="answer">
        {h.answer ? (
          <details className="answer__saved">
            <summary>Yanıt kayıtlı</summary>
            <p>{h.answer}</p>
            <button className="modal-link" onClick={() => { setDraft(h.answer); setOpen(true); }}>düzenle</button>
          </details>
        ) : (
          <button className="modal-link" onClick={() => setOpen(true)}>Yanıtı yapıştır</button>
        )}
        {llmOn && !h.answer && (
          <button className="modal-link" disabled={busy} onClick={fromModel}>
            {busy ? "Model düşünüyor…" : "Model yanıtlasın"}
          </button>
        )}
        {err && <span className="answer__err">{err}</span>}
      </div>
    );
  }
  return (
    <div className="answer answer--open">
      <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={5}
                placeholder="ChatGPT'nin yanıtını buraya yapıştır" aria-label="Sorunun yanıtı" />
      <div className="answer__actions">
        <button className="btn" disabled={busy} onClick={() => setOpen(false)}>Vazgeç</button>
        {h.answer && <button className="btn" disabled={busy} onClick={() => save("")}>Kaldır</button>}
        <button className="btn btn--primary" disabled={busy || !draft.trim()} onClick={() => save(draft)}>Kaydet</button>
      </div>
      {err && <span className="answer__err">{err}</span>}
    </div>
  );
}

// One of the reader's "!" ideas grown into its own note in "3 - Gelişen
// Notlar": their words and the passage, shown and editable before writing.
function DevelopBox({ h, bookKey, vaultOk, setFlash }) {
  const [draft, setDraft] = useState(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [done, setDone] = useState(null);

  const open = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await developPreview(bookKey, h.id);
      setDraft(r.text);
      setName(r.name);
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };
  const write = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await developWrite(bookKey, h.id, draft);
      setDone(r.name);
      setDraft(null);
      setFlash(`“${r.name}” Gelişen Notlar'a yazıldı`);
      setTimeout(() => setFlash(null), 2600);
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  if (done) return <span className="develop__done">Gelişen not: {done}</span>;
  if (draft === null) {
    return (
      <span className="develop">
        <button className="modal-link" disabled={busy || !vaultOk} onClick={open}>
          {busy ? "Hazırlanıyor…" : "Gelişen nota dönüştür"}
        </button>
        {err && <span className="answer__err">{err}</span>}
      </span>
    );
  }
  return (
    <div className="answer answer--open">
      <span className="develop__name">3 - Gelişen Notlar / {name}</span>
      <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={9} aria-label="Gelişen notun metni" />
      <div className="answer__actions">
        <button className="btn" disabled={busy} onClick={() => setDraft(null)}>Vazgeç</button>
        <button className="btn btn--primary" disabled={busy || !draft.trim()} onClick={write}>Kasaya yaz</button>
      </div>
      {err && <span className="answer__err">{err}</span>}
    </div>
  );
}

function copy(text, setFlash, label) {
  navigator.clipboard?.writeText(text).then(
    () => setFlash(label),
    () => setFlash("Kopyalanamadı"),
  );
  setTimeout(() => setFlash(null), 2200);
}

export default function ReadingNotebook({ onBack }) {
  const [data, setData] = useState(null);
  const [selected, setSelected] = useState(null);
  const [book, setBook] = useState(null);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const [flash, setFlash] = useState(null);
  const [dropped, setDropped] = useState(new Set());
  const [links, setLinks] = useState({});
  const [include, setInclude] = useState(new Set());
  const [plan, setPlan] = useState(null);
  const [result, setResult] = useState(null);
  const [vaultDraft, setVaultDraft] = useState(null);
  const [asking, setAsking] = useState(false);
  const fileRef = useRef(null);

  const load = (keepSelection = true) =>
    fetchNotebook().then((d) => {
      setData(d);
      if (!keepSelection || !selected) setSelected(d.books[0]?.key ?? null);
    }).catch((e) => setError(e.message));
  const [words, setWords] = useState(null);
  const loadWords = () => fetchWords().then(setWords).catch(() => {});

  useEffect(() => { load(false); loadWords(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // A Kindle plugged in while this screen is open is read at once: the
  // cable is the only way in for books sent with Send to Kindle, so it
  // should be the only thing the reader has to do.
  const [kindle, setKindle] = useState({ connected: false, ready: false, message: null });
  const kindleOn = kindle.ready;
  const wasOn = useRef(null);
  useEffect(() => {
    let alive = true;
    const probe = async () => {
      const st = await kindleStatus().catch(() => ({ connected: false, ready: false }));
      if (!alive) return;
      setKindle(st);
      // read it once it is plugged in and unlocked; a locked Kindle shows
      // its message and is read as soon as it opens up
      if (st.ready && wasOn.current !== true) {
        const d = await importFromKindle().catch(() => null);
        if (alive && d) afterImport(d, "Kindle bağlandı — ");
        const w = await wordsFromKindle().catch(() => null);
        if (alive && w) {
          setWords(w);
          if (w.imported) {
            setFlash(`Kindle'dan ${w.imported} yeni kelime`);
            setTimeout(() => setFlash(null), 2600);
          }
        }
      }
      wasOn.current = st.ready;
    };
    probe();
    // only while the screen is in view: no PowerShell every few seconds for
    // a window in the background (and no fan for it)
    const timer = setInterval(() => { if (!document.hidden) probe(); }, 8000);
    const onShow = () => { if (!document.hidden) probe(); };
    document.addEventListener("visibilitychange", onShow);
    return () => { alive = false; clearInterval(timer); document.removeEventListener("visibilitychange", onShow); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!selected || selected === WORDS) { setBook(null); return; }
    setBook(null);
    setPlan(null);
    setResult(null);
    setDropped(new Set());
    setLinks({});
    setInclude(new Set());
    fetchNotebookBook(selected).then(setBook).catch((e) => setError(e.message));
  }, [selected]);

  const reloadBook = () => fetchNotebookBook(selected).then(setBook).catch((e) => setError(e.message));

  // Turkish letters for notes typed without them: applied on the reader's
  // click only, one note or all of them, and undoable.
  const applyEdits = (changes, label) => run("edits", async () => {
    await saveNoteEdits(changes);
    await reloadBook();
    setPlan(null);
    setFlash(label);
    setTimeout(() => setFlash(null), 2200);
  });

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

  const afterImport = (d, prefix = "") => {
    if (!d) return;
    setData(d);
    setSelected((cur) => cur ?? d.books[0]?.key ?? null);
    setFlash(prefix + (d.imported ? `${d.imported} yeni kayıt alındı` : "yeni bir şey yok, hepsi zaten alınmış"));
    setTimeout(() => setFlash(null), 2600);
  };

  const body = () => ({ dropped: [...dropped], links, include: [...include] });
  const preview = () => run("plan", async () => { setResult(null); setPlan(await planNotebookBook(selected, body())); });
  const write = () => run("write", async () => {
    const r = await writeNotebookBook(selected, { ...body(), token: plan.token });
    setResult(r);
    setPlan(null);
    load();
  });

  const toggle = (set, setter, id) => {
    const next = new Set(set);
    next.has(id) ? next.delete(id) : next.add(id);
    setter(next);
    setPlan(null);
  };

  // A highlight older than the note, ticked or unticked inside the preview:
  // the preview is made again with it, so the tick and the changes below it
  // show at once (clearing the preview made the tick vanish with it).
  const toggleHeld = (id) => {
    const next = new Set(include);
    next.has(id) ? next.delete(id) : next.add(id);
    setInclude(next);
    run("plan", async () => {
      setPlan(await planNotebookBook(selected, { dropped: [...dropped], links, include: [...next] }));
    });
  };

  const items = book?.highlights ?? [];
  const counts = useMemo(() => ({
    highlights: items.filter((h) => h.text).length,
    notes: items.filter((h) => h.note).length,
    questions: items.filter((h) => h.question).length,
    ideas: items.filter((h) => h.note_kind === "idea").length,
  }), [items]);
  const settings = data?.settings;

  return (
    <div className="notebook">
      <header className="notebook__bar">
        <button className="btn" onClick={onBack}>← Matbaa</button>
        <div className="notebook__titles">
          <h1>Okuma Defteri</h1>
          <p>Kindle'da altını çizdiğin yerler ve notların, kitaptaki yerleriyle Obsidian'a.</p>
        </div>
        <div className="notebook__actions">
          <span className={`notebook__kindle ${kindleOn ? "is-on" : kindle.message ? "is-warn" : ""}`} role="status">
            {kindleOn ? "Kindle bağlı"
              : kindle.message ? kindle.message
                : "Kindle bağlı değil — kabloyla bağlayınca notlar kendiliğinden gelir"}
          </span>
          <button className="btn btn--primary" disabled={!!busy}
                  onClick={() => run("kindle", importFromKindle).then((d) => afterImport(d))}>
            {busy === "kindle" ? "Kindle okunuyor…" : "Kindle'dan al"}
          </button>
          <button className="btn" disabled={!!busy} onClick={() => fileRef.current?.click()}>Dosya yükle</button>
          <button className="btn" onClick={() => setAsking(true)}
                  title="Bütün kitaplarında bir şeyi ara ya da sor: “bunu daha önce nerede okumuştum?”">
            Kitaplığıma sor
          </button>
          <input ref={fileRef} type="file" accept=".txt,.html,.htm,.csv" hidden
                 onChange={(e) => {
                   const f = e.target.files?.[0];
                   e.target.value = "";
                   if (f) run("file", () => importClippings(f)).then((d) => afterImport(d));
                 }} />
        </div>
      </header>

      <div className="notebook__vault">
        <span className="notebook__label"><ObsidianMark />Obsidian kasası</span>
        {vaultDraft === null ? (
          <>
            <code className={settings?.vault_ok ? "" : "notebook__bad"}>{settings?.vault || "seçilmedi"}</code>
            {settings?.vault_problem && <span className="notebook__vault-problem">{settings.vault_problem}</span>}
            <button className="modal-link" onClick={() => setVaultDraft(settings?.vault || "")}>değiştir</button>
          </>
        ) : (
          <>
            <input className="notebook__vault-input" value={vaultDraft} onChange={(e) => setVaultDraft(e.target.value)}
                   placeholder="Obsidian kasanın klasörü, ör. D:\Belgeler\Obsidian" />
            <button className="btn" onClick={() => run("vault", async () => {
              await saveObsidianSettings({ vault: vaultDraft });
              setVaultDraft(null);
              await load();
            })}>Kaydet</button>
            <button className="modal-link" onClick={() => setVaultDraft(null)}>vazgeç</button>
          </>
        )}
        {flash && <span className="notebook__flash" role="status">{flash}</span>}
      </div>

      <KindleCard ready={kindleOn} />
      {asking && <AskModal onClose={() => setAsking(false)} />}

      {error && <p className="modal-panel__error notebook__error" role="alert">{error}</p>}

      <div className="notebook__split">
        <nav className="notebook__books" aria-label="Kitaplar">
          <button className={`notebook__book notebook__book--words ${selected === WORDS ? "is-active" : ""}`}
                  onClick={() => setSelected(WORDS)}>
            <span className="notebook__book-title">Kelime Defteri</span>
            <span className="notebook__book-meta">
              {words?.words?.length
                ? `${words.words.length} kelime · ${words.words.filter((w) => !w.in_note).length} yeni`
                : "Kindle'da baktığın kelimeler"}
            </span>
          </button>
          {(() => {
            const recent = (data?.books || []).filter((b) => b.session)
              .sort((a, b) => (a.session.date < b.session.date ? 1 : -1))[0];
            if (!recent) return null;
            const day = new Date(recent.session.date + "T12:00:00").toLocaleDateString("tr-TR",
              { day: "numeric", month: "long", year: "numeric" });
            return (
              <button className="notebook__recent" onClick={() => setSelected(recent.key)}>
                <span className="notebook__label">Son okuma · {day}</span>
                <span className="notebook__recent-title">{recent.title}</span>
                <span className="notebook__book-meta">
                  {[`${recent.session.highlights} vurgu`, recent.session.notes ? `${recent.session.notes} not` : null]
                    .filter(Boolean).join(" · ")}
                </span>
              </button>
            );
          })()}
          {data && data.books.length === 0 && (
            <p className="notebook__empty">
              Henüz vurgu yok. Kindle'ı kabloyla bağlayıp “Kindle'dan al”a bas, ya da My Clippings.txt /
              Amazon'un not dışa aktarımını yükle.
            </p>
          )}
          {data?.books.map((b) => (
            <button key={b.key} className={`notebook__book ${b.key === selected ? "is-active" : ""}`}
                    onClick={() => setSelected(b.key)}>
              <span className="notebook__book-title">{b.title}</span>
              <span className="notebook__book-meta">
                {[b.author, `${b.highlights} vurgu`, b.notes ? `${b.notes} not` : null,
                  b.questions ? `${b.questions} soru` : null].filter(Boolean).join(" · ")}
              </span>
              <span className="notebook__badges">
                {b.project && <span className="badge">Matbaa kitabı</span>}
                {b.note && <span className="badge badge--soft">notu var</span>}
              </span>
            </button>
          ))}
        </nav>

        <section className="notebook__detail">
          {selected === WORDS && (
            <WordNotebook data={words} vaultOk={!!settings?.vault_ok} busy={busy} run={run} onWritten={loadWords} />
          )}
          {!book && selected && selected !== WORDS && <p className="notebook__empty">Yükleniyor…</p>}
          {book && (
            <>
              <div className="notebook__head">
                <div>
                  <h2>{book.title}</h2>
                  <p className="notebook__book-meta">
                    {[book.author, `${counts.highlights} vurgu`, `${counts.notes} not`, `${counts.questions} soru`,
                      counts.ideas ? `${counts.ideas} fikir` : null]
                      .filter(Boolean).join(" · ")}
                    {book.project ? " · kitaptaki yerleri bulundu" : " · Matbaa'da bu kitap yok; vurgular Kindle'daki haliyle"}
                  </p>
                </div>
                {items.some((h) => h.note_suggestion) && (
                  <button className="btn" disabled={!!busy} onClick={() => applyEdits(
                    Object.fromEntries(items.filter((h) => h.note_suggestion).map((h) => [h.id, h.note_suggestion])),
                    "Notlarda Türkçe harfler düzeltildi")}>
                    Türkçe harfleri düzelt ({items.filter((h) => h.note_suggestion).length})
                  </button>
                )}
                <button className="btn" onClick={() => copy(bookPack(book, items.filter((h) => !dropped.has(h.id))),
                  setFlash, "Kitap paketi kopyalandı — ChatGPT'ye yapıştır")}>
                  Kitap paketi
                </button>
              </div>

              <SignCard />

              {book.limited > 0 && (
                <p className="notebook__warn">
                  Kindle bu kitapta “kırpma sınırına” ulaşmış: {book.limited} vurgunun metni My Clippings'e
                  yazılmamış. Eksiksiz liste için kitabın Not Defteri'nden “Notları dışa aktar” de; e-postayla
                  gelen HTML dosyasını “Dosya yükle”den ekle.
                </p>
              )}

              <ol className="notebook__items">
                {items.map((h) => {
                  const off = dropped.has(h.id);
                  const link = h.id in links ? links[h.id] : h.link;
                  return (
                    <li key={h.id} className={`hl ${off ? "hl--off" : ""}`}>
                      <label className="hl__keep" title={off ? "Ekle" : "Bunu yazma"}>
                        <input type="checkbox" checked={!off} onChange={() => toggle(dropped, setDropped, h.id)} />
                      </label>
                      <div className="hl__body">
                        {h.text && <blockquote className="hl__quote">{h.quote || h.text}</blockquote>}
                        {h.changed && (
                          <p className="hl__was">Kindle'da: {h.text} <em>(kitaptaki yazımla düzeltildi)</em></p>
                        )}
                        {h.note && h.note_kind !== "link" && h.note_text && (
                          <p className={`hl__note hl__note--${h.note_kind}`}>
                            {h.note_kind === "idea" && <strong>Ben: </strong>}{h.note_text}
                          </p>
                        )}
                        {h.seen_in?.length > 0 && (
                          <p className="hl__seen">daha önce: {h.seen_in.join(", ")}</p>
                        )}
                        {h.note_suggestion && (
                          <p className="hl__suggest">
                            Türkçe harflerle: <span>{h.note_suggestion}</span>{" "}
                            <button className="modal-link" disabled={!!busy}
                                    onClick={() => applyEdits({ [h.id]: h.note_suggestion }, "Not düzeltildi")}>uygula</button>
                          </p>
                        )}
                        {h.note_original && (
                          <p className="hl__suggest">
                            Kindle'daki hali: <span>{h.note_original}</span>{" "}
                            <button className="modal-link" disabled={!!busy}
                                    onClick={() => applyEdits({ [h.id]: null }, "Not Kindle'daki haline döndü")}>geri al</button>
                          </p>
                        )}
                        {h.note_kind === "link" && h.note_links?.length > 0 && (
                          <p className="hl__links">→ {h.note_links.map((l) => (
                            <span key={l.name} className="hl__chip">[[{l.name}]]{l.exists ? "" : " · yeni"}</span>
                          ))}</p>
                        )}
                        <div className="hl__meta">
                          <span>{pageLabel(h) || (book.project && h.text ? "yeri bulunamadı" : "")}</span>
                          {KIND_LABEL[h.note_kind] && (
                            <span className={`badge badge--${h.note_kind}`}>{KIND_LABEL[h.note_kind]}</span>
                          )}
                          {(h.question || h.note) && (
                            <button className="modal-link" onClick={() => copy(askPrompt(book, h), setFlash,
                              "Kopyalandı — ChatGPT'ye yapıştır")}>
                              ChatGPT'ye sor
                            </button>
                          )}
                          {h.note_kind === "idea" && (
                            <DevelopBox h={h} bookKey={book.key} vaultOk={!!settings?.vault_ok} setFlash={setFlash} />
                          )}
                          {h.question && (
                            <AnswerBox h={h} bookKey={book.key} llmOn={!!settings?.llm} setFlash={setFlash}
                                       onSaved={(id, answer) => {
                                         setBook({ ...book, highlights: book.highlights.map((x) =>
                                           x.id === id ? { ...x, answer } : x) });
                                         setPlan(null);
                                       }} />
                          )}
                          {h.text && h.text.split(/\s+/).length <= 4 && (
                            <span className="hl__link">
                              <span aria-hidden="true">[[</span>
                              <input value={link || ""} placeholder="bağlantı yok"
                                     onChange={(e) => { setLinks({ ...links, [h.id]: e.target.value }); setPlan(null); }} />
                              <span aria-hidden="true">]]</span>
                              {h.link_exists && link === h.link && <span className="badge badge--soft">notu var</span>}
                            </span>
                          )}
                        </div>
                      </div>
                    </li>
                  );
                })}
              </ol>

              <div className="notebook__footer">
                {!plan && !result && (
                  <button className="btn btn--primary" disabled={!!busy || !settings?.vault_ok} onClick={preview}>
                    {busy === "plan" ? "Hazırlanıyor…" : "Obsidian notunu önizle"}
                  </button>
                )}
                {!settings?.vault_ok && <span className="notebook__hint">Önce Obsidian kasasını seç.</span>}

                {plan && (
                  <div className="plan">
                    <p className="plan__summary">
                      <strong>{plan.note.name}</strong> {plan.note.exists ? "notuna" : "yeni not olarak"}{" "}
                      {plan.added} vurgu eklenecek
                      {plan.already ? `, ${plan.already} zaten notta` : ""}
                      {plan.placeholders.length ? `, ${plan.placeholders.length} yeni kavram notu (6 - Tags)` : ""}
                      {plan.answers ? `, ${plan.answers} yanıt notta` : ""}.
                      Notunda yazdıkların değişmez.
                    </p>
                    {plan.held_back.length > 0 && (
                      <div className="plan__held">
                        <p>
                          Notun açıldığı tarihten önce yapılmış ama notta olmayan {plan.held_back.length} vurgu
                          var — Kindle'da silinmiş, yeniden çizilmiş ya da nota hiç aktarılmamış olabilirler.
                          Notuna eklemek istediklerini işaretle; aşağıdaki değişiklikler hemen güncellenir:
                        </p>
                        {plan.held_back.map((h) => (
                          <label key={h.id} className="plan__held-item">
                            <input type="checkbox" checked={!!h.included} disabled={!!busy}
                                   onChange={() => toggleHeld(h.id)} />
                            <span>{h.text || h.note}</span>
                          </label>
                        ))}
                      </div>
                    )}
                    {plan.pages?.length > 0 && (
                      <p className="plan__tags">
                        Kasanda ilk kez şu sayfa{plan.pages.length > 1 ? "lar" : ""} da açılacak:{" "}
                        {plan.pages.map((p) => p.path.split(/[\\/]/).pop().replace(/\.md$/, "")).join(", ")}.
                        “Açık Sorular” bütün kitap notlarındaki işaretlenmemiş soruları, “Fikirlerim” kendi
                        fikirlerini tek yerde gösterir.
                      </p>
                    )}
                    {plan.placeholders.length > 0 && (
                      <p className="plan__tags">Yeni kavram notları: {plan.placeholders.map((p) =>
                        p.path.split(/[\\/]/).pop().replace(/\.md$/, "")).join(", ")}</p>
                    )}
                    <details className="plan__diff" open={!plan.note.exists}>
                      <summary>{plan.note.exists ? "Notuna eklenecekler" : "Notun tamamı"}</summary>
                      {plan.note.exists ? <NoteChanges diff={plan.note.diff} /> : <pre>{plan.note.text}</pre>}
                    </details>
                    <div className="modal-actions">
                      <button className="btn" onClick={() => setPlan(null)}>Geri</button>
                      <button className="btn" onClick={preview} disabled={!!busy}>Yenile</button>
                      <button className="btn btn--primary" onClick={write}
                              disabled={!!busy || (!plan.note.diff && plan.placeholders.length === 0
                                && !(plan.pages?.length))}>
                        {busy === "write" ? "Yazılıyor…" : <><ObsidianMark />Obsidian'a yaz</>}
                      </button>
                    </div>
                  </div>
                )}

                {result && (
                  <div className="plan">
                    <p className="plan__summary">
                      {result.written.length
                        ? `Yazıldı: ${result.written.map((p) => p.split(/[\\/]/).pop()).join(", ")}`
                        : "Yazılacak yeni bir şey yoktu."}
                    </p>
                    {result.conflicts.length > 0 && (
                      <p className="modal-panel__error">
                        Şunlar önizlemeden sonra değiştiği için yazılmadı: {result.conflicts.map((p) =>
                          p.split(/[\\/]/).pop()).join(", ")}. Önizlemeyi yenileyip tekrar dene.
                      </p>
                    )}
                    <button className="btn" onClick={() => setResult(null)}>Tamam</button>
                  </div>
                )}
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
