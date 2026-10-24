import React, { useEffect, useMemo, useRef, useState } from "react";
import { fetchNotebook, fetchNotebookBook, fetchProjects, fetchStartQuote } from "../api";
import CounterPanel from "./CounterPanel.jsx";
import Icon from "./Icon.jsx";
import ShelfCard, { ALPHABET, authorOf, initial } from "./ShelfCard.jsx";

// The Haşiye start screen, set as an edition's front matter: a running head,
// the contents down the left margin, the call to bring a PDF, a rail of the
// Turkish alphabet that sorts the shelf, the last book read with a passage
// the reader marked, and the shelf of cloth-bound editions.
function Cross() {
  return <span className="ed-cross" aria-hidden="true" />;
}

// A line from the latest book (Vikisöz), else Trotsky's (app/quote_lookup.py),
// with whose it is under it.
function Quoted({ quote }) {
  if (!quote) return null;
  return (
    <figure className="ed__quote">
      <blockquote className="ed__passage">{quote.text}</blockquote>
      <figcaption className="ed__quote-by">
        {quote.author}{quote.kind === "fallback" ? `, ${quote.source}` : ""}
        {quote.url && <> · <a href={quote.url} target="_blank" rel="noreferrer">{quote.source}</a></>}
      </figcaption>
    </figure>
  );
}

function Register({ corner }) {
  return (
    <svg className={`ed-register ed-register--${corner}`} viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="6.5" fill="none" stroke="currentColor" strokeWidth="1" />
      <path d="M12 1v22M1 12h22" stroke="currentColor" strokeWidth="1" />
    </svg>
  );
}

export default function HasiyeStart({ onFileSelected, isConverting, progress, error, onOpenProject, onOpenNotebook,
                                     onOpenLibrary }) {
  const [projects, setProjects] = useState(null);
  const [recent, setRecent] = useState(null);
  const [quote, setQuote] = useState(null);
  useEffect(() => { fetchStartQuote().then((d) => setQuote(d.quote)).catch(() => setQuote(null)); }, []);
  const [letter, setLetter] = useState(null);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef(null);
  const shelfRef = useRef(null);
  const rowRef = useRef(null);

  const loadProjects = () => fetchProjects().then(setProjects).catch(() => setProjects([]));
  useEffect(() => { loadProjects(); }, []);

  // the last book read on the Kindle, and the first passage marked in it
  useEffect(() => {
    let live = true;
    fetchNotebook()
      .then(async (data) => {
        const book = (data?.books || []).filter((b) => b.session)
          .sort((a, b) => (a.session.date < b.session.date ? 1 : -1))[0];
        if (!book) return;
        const detail = await fetchNotebookBook(book.key).catch(() => null);
        const marked = (detail?.highlights || []).find((h) => (h.quote || h.text || "").length > 40);
        if (live) setRecent({ ...book, passage: marked });
      })
      .catch(() => {});
    return () => { live = false; };
  }, []);

  const letters = useMemo(() => new Set((projects || []).map((p) => initial(p.book_title))), [projects]);
  const shown = (projects || []).filter((p) => !letter || initial(p.book_title) === letter);

  const choose = () => !isConverting && inputRef.current?.click();
  const dropProps = {
    onDragOver: (e) => { e.preventDefault(); setDragging(true); },
    onDragLeave: (e) => { if (!e.currentTarget.contains(e.relatedTarget)) setDragging(false); },
    onDrop: (e) => {
      e.preventDefault();
      setDragging(false);
      const file = e.dataTransfer.files?.[0];
      if (file) onFileSelected(file);
    },
  };
  const toShelf = () => shelfRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  const pick = (l) => { setLetter(letter === l ? null : l); toShelf(); };
  const scrollRow = (dir) => rowRef.current?.scrollBy({ left: dir * 640, behavior: "smooth" });
  const day = recent?.session?.date
    ? new Date(recent.session.date + "T12:00:00").toLocaleDateString("tr-TR", { day: "numeric", month: "long", year: "numeric" })
    : null;
  const lastBook = projects && projects[0];

  const contents = [
    ["01", "Yeni kitap", "PDF'ten Kindle'a", choose],
    ["02", "Kitaplık", projects ? `${projects.length} kitap` : "Dönüştürülen kitaplar", onOpenLibrary || toShelf],
    ["03", "Okuma Defteri", "Vurgular ve notlar, Obsidian'a", onOpenNotebook],
    ["04", "Kelime Defteri", "Kindle'da bakılan kelimeler", onOpenNotebook],
    ["05", "Kindle'ım", "Yazı tipleri ve Türkçe sözlük", onOpenNotebook],
  ];

  return (
    <div className="ed" {...dropProps}>
      <input ref={inputRef} type="file" accept="application/pdf" hidden
             onChange={(e) => e.target.files?.[0] && onFileSelected(e.target.files[0])} />

      <header className="ed__head">
        <Register corner="left" />
        <div className="ed__mark">
          <span className="ed__name">Matbaa</span>
          <Cross />
          <span className="ed__motto">PDF'ten Kindle'a</span>
        </div>
        <nav className="ed__links" aria-label="Bölümler">
          <button type="button" onClick={onOpenLibrary || toShelf}>Kitaplık</button>
          <button type="button" onClick={onOpenNotebook}>Okuma Defteri</button>
          <button type="button" className="ed__plus" onClick={choose} aria-label="Yeni PDF seç" title="Yeni PDF seç">
            <span className="ed-cross" aria-hidden="true" />
          </button>
        </nav>
        <Register corner="right" />
      </header>

      <aside className="ed__side">
        <p className="ed__side-label"><Cross /> Gezinti</p>
        <ol className="ed__contents">
          {contents.map(([n, title, sub, go], i) => (
            <li key={n}>
              <button type="button" className={`ed__entry ${i === 0 ? "is-current" : ""}`} onClick={go}>
                <span className="ed__entry-n">{n}</span>
                <span className="ed__entry-title">{title}</span>
                <span className="ed__entry-sub">{sub}</span>
              </button>
            </li>
          ))}
        </ol>
        <CounterPanel />
        {recent && (
          <div className="ed__reading">
            <p className="ed__side-label">Şu an okunan</p>
            <span className="ed__reading-rule"><Cross /></span>
            <p className="ed__reading-title">{recent.title}</p>
            <p className="ed__reading-sub">
              {recent.session.highlights} vurgu{recent.session.notes ? ` · ${recent.session.notes} not` : ""}
            </p>
            <button type="button" className="ed__link" onClick={onOpenNotebook}>Deftere dön <Icon name="next" /></button>
          </div>
        )}
        <span className="ed__side-foot"><Cross /></span>
      </aside>

      <main className="ed__main">
        <section className={`ed__lead ${dragging ? "is-dragging" : ""}`}>
          <div className="ed__call">
            {!isConverting ? (
              <>
                <h1 className="ed__title">Kitabınızı Kindle'a dizin.</h1>
                <span className="ed__rule"><Cross /></span>
                <p className="ed__lede">
                  Bir PDF bırakın; Matbaa bölümlerini, dipnotlarını ve içindekilerini kurar,
                  taranmış sayfaları okur ve Kindle'da düzgün okunan bir kitap dizer.
                </p>
                <div className="ed__actions">
                  <button type="button" className="ed-btn ed-btn--primary" onClick={choose}>
                    PDF seç <Icon name="next" />
                  </button>
                  <button type="button" className="ed-btn" onClick={onOpenNotebook}>
                    Okuma Defteri <span className="ed-cross ed-cross--btn" aria-hidden="true" />
                  </button>
                </div>
                <p className="ed__hint">ya da PDF'i bu sayfanın herhangi bir yerine bırakın · 200 MB'a kadar</p>
              </>
            ) : (
              <div className="ed__busy" aria-live="polite">
                <h1 className="ed__title">Sayfalar taranıyor…</h1>
                <span className="ed__rule"><Cross /></span>
                <div className="ed__progress"><span style={{ width: `${progress}%` }} /></div>
                <p className="ed__lede">
                  {progress < 100 ? `Yükleniyor — %${progress}` : "Sayfa küçük resimleri hazırlanıyor…"}
                </p>
              </div>
            )}
            {error && <p className="ed__error" role="alert">{error}</p>}
            {dragging && (
              <div className="ed__drop" aria-hidden="true">
                <span>PDF'i bırakın</span>
              </div>
            )}
          </div>

          <nav className="ed__rail" aria-label="Kitaplığı harfe göre süz">
            <span className="ed__rail-stop" />
            {ALPHABET.map((l) => (
              <button key={l} type="button" disabled={!letters.has(l)}
                      className={`ed__rail-letter ${letter === l ? "is-on" : ""}`}
                      onClick={() => pick(l)} aria-pressed={letter === l}>
                {l}
              </button>
            ))}
            <span className="ed__rail-stop" />
          </nav>

          <div className="ed__excerpt">
            {recent ? (
              <>
                <p className="ed__label">Son okuma{day ? ` · ${day}` : ""}</p>
                <h2 className="ed__excerpt-title">{recent.title}</h2>
                <span className="ed__rule"><Cross /></span>
                {recent.passage && (
                  <blockquote className="ed__passage">{recent.passage.quote || recent.passage.text}</blockquote>
                )}
                <button type="button" className="ed__link" onClick={onOpenNotebook}>Deftere dön <span className="ed-cross ed-cross--btn" aria-hidden="true" /></button>
                <aside className="ed__note" aria-label="Kenar notu">
                  {recent.passage?.page && <span>s. {recent.passage.page}</span>}
                  <em>{recent.session.highlights} vurgu{recent.session.notes ? `, ${recent.session.notes} not` : ""}</em>
                </aside>
              </>
            ) : lastBook ? (
              <>
                <p className="ed__label">Son düzenlenen</p>
                <h2 className="ed__excerpt-title">{lastBook.book_title}</h2>
                <span className="ed__rule"><Cross /></span>
                <p className="ed__passage-plain">{authorOf(lastBook)}</p>
                <Quoted quote={quote} />
                <button type="button" className="ed__link" onClick={() => onOpenProject(lastBook.session_id)}>Kitabı aç <span className="ed-cross ed-cross--btn" aria-hidden="true" /></button>
              </>
            ) : projects && projects.length === 0 ? (
              <>
                <p className="ed__label">İlk adımlar</p>
                <h2 className="ed__excerpt-title">Henüz kitap yok.</h2>
                <span className="ed__rule"><Cross /></span>
                <Quoted quote={quote} />
                <ol className="ed__steps">
                  <li><strong>PDF'inizi bırakın.</strong> Matbaa sayfaları tanır; emin olamadıklarını size gösterir,
                    sonra dönüştürür.</li>
                  <li><strong>Kitabı Kindle'a gönderin</strong> ya da EPUB'u indirin. Tezgâhta bölümleri ve metni
                    düzeltebilirsiniz.</li>
                  <li><strong>Okuma Defteri'ni açın.</strong> Kindle'ı bağlayın ve Obsidian kasanızı seçin; altını
                    çizdikleriniz kasanıza, kitaptaki sayfalarıyla gelir.</li>
                </ol>
              </>
            ) : null}
          </div>
        </section>

        {projects && projects.length > 0 && (
          <section className="ed__shelf" ref={shelfRef} aria-label="Kitaplığım">
            <div className="ed__shelf-head">
              <p className="ed__label">
                Kitaplığım{letter ? ` · ${letter}` : ""} · {shown.length} kitap
              </p>
              {letter && <button type="button" className="ed__link" onClick={() => setLetter(null)}>hepsi</button>}
              <span className="ed__shelf-rule" />
              {onOpenLibrary && (
                <button type="button" className="ed__link ed__link--inline" onClick={onOpenLibrary}>
                  Tümünü gör <Icon name="next" />
                </button>
              )}
              <div className="ed__arrows">
                <button type="button" onClick={() => scrollRow(-1)} aria-label="Geri"><Icon name="back" /></button>
                <button type="button" onClick={() => scrollRow(1)} aria-label="İleri"><Icon name="next" /></button>
              </div>
            </div>
            <ul className="ed__row" ref={rowRef}>
              {shown.map((p, i) => (
                <ShelfCard key={p.session_id} p={p} index={i} onOpen={onOpenProject} onRemoved={loadProjects} />
              ))}
            </ul>
          </section>
        )}
      </main>
    </div>
  );
}
