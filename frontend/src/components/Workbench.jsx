import React, { useEffect, useMemo, useRef, useState } from "react";
import { chooseCover, fetchFonts, fetchGenres, fetchThemes, readerNotesCount } from "../api";
import SendToKindleModal from "./SendToKindleModal";
import ChapterList from "./ChapterList.jsx";
import LiveEditor from "./LiveEditor.jsx";
import KindleSimulator from "./KindleSimulator.jsx";
import FindReplaceModal from "./FindReplaceModal.jsx";
import ImprintModal from "./ImprintModal.jsx";
import IndexModal from "./IndexModal.jsx";
import AskModal from "./AskModal.jsx";

export default function Workbench({ session, onSaveChapter, onSplitChapter, onExport, onMetaChange, onBulkReplace, onSessionReplace, onReorderChapters, onStartOver, saveStatus, isExporting }) {
  const [selectedId, setSelectedId] = useState(session.chapters[0]?.id ?? null);
  const [showFindReplace, setShowFindReplace] = useState(false);
  const [showKindle, setShowKindle] = useState(false);
  const [showImprint, setShowImprint] = useState(false);
  const [showIndex, setShowIndex] = useState(false);
  const [showAsk, setShowAsk] = useState(false);
  // the reader's Kindle highlights for this book, if any were imported:
  // then the book can be exported with them carried back in
  const [readerNotes, setReaderNotes] = useState(null);
  const [withNotes, setWithNotes] = useState(false);
  useEffect(() => {
    readerNotesCount(session.session_id).then(setReaderNotes).catch(() => setReaderNotes(null));
  }, [session.session_id]);
  // How the book looks: the theme is a block of the book's own stylesheet,
  // so the preview beside the editor shows it as the Kindle will.
  const [themes, setThemes] = useState([]);
  useEffect(() => {
    fetchThemes().then(setThemes).catch(() => setThemes([]));
  }, []);
  // What kind of book it is: guessed at conversion (Wikidata, else the book
  // itself), the reader's word final; it sorts the library and the counter.
  const [genres, setGenres] = useState([]);
  useEffect(() => {
    fetchGenres().then(setGenres).catch(() => setGenres([]));
  }, []);
  const genreAbout = session.genre_source === "reader" ? "senin seçimin"
    : session.genre_source === "wikidata" ? `tahmin; ${session.genre_reason || "Wikidata"}`
    : `tahmin, kitabın kendisinden${session.genre_reason ? `; ${session.genre_reason}` : ""}`;
  // A typeface embedded in an older book: shown in the preview as the Kindle
  // shows it with "Yayıncı yazı tipi" chosen; its rule goes before the
  // theme's block, as the builder puts it (app/fonts.py with_family).
  const [fonts, setFonts] = useState([]);
  useEffect(() => {
    fetchFonts().then(setFonts).catch(() => setFonts([]));
  }, []);
  const fontId = session.font || "kindle";
  const font = fonts.find((f) => f.id === fontId);
  const previewCss = useMemo(() => {
    const css = session.css || "";
    if (!font?.family_rule) return css;
    const at = css.indexOf("/* matbaa-theme:");
    if (at < 0) return [css, font.family_rule].join("\n");
    return [css.slice(0, at), font.family_rule, css.slice(at)].join("\n");
  }, [session.css, font]);

  const theme = (session.css || "").match(/\/\* matbaa-theme:([a-z]+) \*\//)?.[1] || "klasik";
  const themeAbout = themes.find((t) => t.id === theme)?.about || "";
  // The PDF's own cover or one set in type; the PDF's is kept while the
  // other is in use, so the choice can always be undone.
  const [coverBusy, setCoverBusy] = useState(false);
  const switchCover = async (kind) => {
    setCoverBusy(true);
    try {
      onSessionReplace(await chooseCover(session.session_id, kind));
    } catch {
      /* the cover stays as it was */
    } finally {
      setCoverBusy(false);
    }
  };
  // The open chapter is re-read from the session after a find-and-replace
  // rewrote it on the server; otherwise the editor kept showing the old
  // text and the next keystroke saved it back over the replacement.
  const [editorReloadKey, setEditorReloadKey] = useState(0);
  const editorRef = useRef(null);

  const openFindReplace = async () => {
    // Unsaved typing goes to the server first, so the search sees it.
    await editorRef.current?.flush();
    setShowFindReplace(true);
  };

  // A language model is shown the chapter as saved, so unsaved typing goes
  // first; its accepted corrections come back as a new session.
  const flushEditor = () => editorRef.current?.flush();
  const applyModelSession = (updated) => {
    onSessionReplace(updated);
    setEditorReloadKey((k) => k + 1);
  };

  const applyReplace = async (changed) => {
    await onBulkReplace(changed);
    setEditorReloadKey((k) => k + 1);
  };
  const selectedChapter = session.chapters.find((c) => c.id === selectedId) || null;
  const chapterNotes = useMemo(
    () => (session.chapter_warnings || []).filter((cw) => cw.chapter_id === selectedId),
    [session.chapter_warnings, selectedId]
  );

  // Most PDFs carry no title/author metadata at all, so the converter falls
  // back to visible placeholders ("Untitled Book" / "Unknown") rather than
  // silently shipping an empty string — but a placeholder that never gets
  // replaced is exactly as bad as an empty field once it's on a real Kindle
  // library shelf, and nothing else in the UI called attention to it before
  // export. Computed live from the same fields the title/author inputs
  // above are bound to, so it disappears the instant either is edited.
  const metaWarnings = useMemo(() => {
    const warnings = [];
    if (!session.book_title?.trim() || session.book_title.trim() === "Untitled Book") {
      warnings.push({ message: "Kitap başlığı ayarlanmamış — üstteki alandan girin.", severity: "warning" });
    }
    if (!session.author?.trim() || session.author.trim() === "Unknown") {
      warnings.push({ message: "Yazar adı ayarlanmamış — üstteki alandan girin.", severity: "info" });
    }
    return warnings;
  }, [session.book_title, session.author]);

  const handleSplit = async (chapterId, beforeHtml, afterHtml, newTitle) => {
    const updated = await onSplitChapter(chapterId, beforeHtml, afterHtml, newTitle);
    const idx = updated.chapters.findIndex((c) => c.id === chapterId);
    const newChapter = idx >= 0 ? updated.chapters[idx + 1] : null;
    if (newChapter) setSelectedId(newChapter.id);
  };

  return (
    <div className="workbench">
      <header className="workbench__topbar">
        <div className="workbench__meta">
          {session.cover_image_base64 && (
            <img
              className="workbench__cover-thumb"
              src={`data:image/png;base64,${session.cover_image_base64}`}
              alt="Kapak"
              title="EPUB kapağı olarak kullanılacak"
            />
          )}
          <div>
            <input
              className="workbench__title-input"
              value={session.book_title}
              onChange={(e) => onMetaChange({ book_title: e.target.value })}
              aria-label="Kitap adı"
            />
            <input
              className="workbench__author-input"
              value={session.author}
              onChange={(e) => onMetaChange({ author: e.target.value })}
              aria-label="Yazar"
            />
            {/* Readers use dc:language to pick hyphenation rules and the
                text-to-speech voice, so it has to be right and it has to be
                correctable when the guess is wrong. */}
            <select
              className="workbench__lang-select"
              value={session.language || "en"}
              onChange={(e) => onMetaChange({ language: e.target.value })}
              aria-label="Kitabın dili"
              title="Kitabın dili — tireleme ve sesli okuma bunu kullanır"
            >
              <option value="tr">Türkçe</option>
              <option value="en">English</option>
              <option value="de">Deutsch</option>
              <option value="fr">Français</option>
              <option value="es">Español</option>
              <option value="it">Italiano</option>
            </select>
            {genres.length > 0 && (
              <select
                className="workbench__lang-select"
                value={session.genre || "diger"}
                onChange={(e) => onMetaChange({ genre: e.target.value })}
                aria-label="Kitabın türü"
                title={`Tür: ${genreAbout}`}
              >
                {genres.map((g) => (
                  <option key={g.id} value={g.id}>{g.label}</option>
                ))}
              </select>
            )}
            {/* A Kindle has no Turkish hyphenation dictionary; Matbaa sets
                soft hyphens at the syllable breaks itself (app/hyphenate.py). */}
            {(session.language || "").startsWith("tr") && (
              <label className="workbench__notes-toggle"
                     title="Türkçe hece kurallarıyla görünmez tireler: iki yana yaslı satırlardaki boşluk delikleri kapanır. Satır sonuna gelen uzun kelime hecesinden bölünür.">
                <input type="checkbox" checked={!!session.hyphenate}
                       onChange={(e) => onMetaChange({ hyphenate: e.target.checked })} />
                heceleme
              </label>
            )}
            <select
              className="workbench__lang-select"
              value={session.cover_kind || "pdf"}
              onChange={(e) => switchCover(e.target.value)}
              disabled={coverBusy}
              aria-label="Kapak"
              title="Kapak — PDF'in kendi kapağı, ya da başlık ve yazardan dizilmiş bir Matbaa kapağı"
            >
              <option value="pdf">PDF kapağı</option>
              <option value="matbaa">Matbaa kapağı</option>
              {session.web_cover_base64 && <option value="web">İnternet kapağı</option>}
            </select>
            {/* Books carry no typeface: Matbaa's faces go on the Kindle itself
                (its fonts/ folder) and serve every book from the Aa menu. The
                choice is shown only for a book made when it embedded one, so
                it can be set back to the Kindle's own. */}
            {fonts.length > 0 && fontId !== "kindle" && (
              <select
                className="workbench__lang-select"
                value={fontId}
                onChange={(e) => onMetaChange({ font: e.target.value })}
                aria-label="Yazı tipi"
                title="Kitaba gömülen yazı tipi — Kindle'da Aa menüsünden “Yayıncı yazı tipi” seçilince kullanılır"
              >
                {fonts.map((f) => (
                  <option key={f.id} value={f.id}>{f.label}</option>
                ))}
              </select>
            )}
            {themes.length > 0 && (
              <select
                className="workbench__lang-select"
                value={theme}
                onChange={(e) => onMetaChange({ theme: e.target.value })}
                aria-label="Kitabın görünümü"
                title={`Görünüm — ${themeAbout}`}
              >
                {themes.map((t) => (
                  <option key={t.id} value={t.id}>{t.label}</option>
                ))}
              </select>
            )}
          </div>
        </div>
        <div className="workbench__actions">
          {onStartOver && (
            <button className="btn workbench__start-over" onClick={onStartOver} title="Yeni bir PDF ile baştan başlayın">
              ← Baştan Başla
            </button>
          )}
          <button className="btn" onClick={() => setShowImprint(true)}
                  title={session.imprint?.isbn ? `ISBN ${session.imprint.isbn}` : "Künye bulunamadı; elle girilebilir"}>
            Künye{session.imprint?.isbn ? " ✓" : ""}
          </button>
          <button className="btn" onClick={() => setShowAsk(true)}
                  title="Kitapta ara, kitaba soru sor; yanıt kitapla denetlenir">
            Kitaba sor
          </button>
          <button className="btn" onClick={() => setShowIndex(true)}
                  title="Basılı dizini olmayan kitap için adlar ve kasandaki kavramlar">
            Dizin
          </button>
          <button className="btn" onClick={openFindReplace}>
            Bul ve Değiştir
          </button>
          <button className="btn btn--send" onClick={() => setShowKindle(true)}>
            Kindle'a Gönder
          </button>
          {readerNotes?.highlights > 0 && (
            <label className="workbench__notes-toggle"
                   title="Altını çizdiğin yerler kitapta işaretli, notların ve soruların kitabın sonunda bir ek olarak">
              <input type="checkbox" checked={withNotes} onChange={(e) => setWithNotes(e.target.checked)} />
              notlarımla ({readerNotes.highlights})
            </label>
          )}
          <button className="btn btn--primary" onClick={() => onExport(withNotes)} disabled={isExporting}>
            {isExporting ? "Derleniyor…" : "EPUB'a Aktar"}
          </button>
        </div>
      </header>

      <div className="workbench__split">
        <ChapterList
          chapters={session.chapters}
          selectedId={selectedId}
          onSelect={setSelectedId}
          warnings={[...metaWarnings, ...(session.warnings || [])]}
          chapterWarnings={session.chapter_warnings}
          onReorder={onReorderChapters}
          report={session.report}
          sessionId={session.session_id}
          onBeforeModel={flushEditor}
          onModelApplied={applyModelSession}
        />

        <LiveEditor
          ref={editorRef}
          reloadKey={editorReloadKey}
          chapter={selectedChapter}
          notes={chapterNotes}
          css={session.css}
          onSave={onSaveChapter}
          onSplit={handleSplit}
          saveStatus={saveStatus}
        />

        <div className="type-ruler" aria-hidden="true">
          {Array.from({ length: 14 }).map((_, i) => (
            <span key={i} className="type-ruler__tick" style={{ height: i % 3 === 0 ? 18 : 9 }} />
          ))}
          <span className="type-ruler__word">MATBAA</span>
        </div>

        <KindleSimulator css={previewCss} fontFaces={font?.faces_css || ""} chapter={selectedChapter} />
      </div>

      {showAsk && <AskModal session={session} onClose={() => setShowAsk(false)} />}
      {showIndex && (
        <IndexModal session={session} onClose={() => setShowIndex(false)} onMetaChange={onMetaChange} />
      )}
      {showImprint && (
        <ImprintModal session={session} onClose={() => setShowImprint(false)} onMetaChange={onMetaChange}
                      onSessionReplace={onSessionReplace} />
      )}
      {showKindle && (
        <SendToKindleModal
          sessionId={session.session_id}
          onClose={() => setShowKindle(false)}
          onBeforeSend={() => editorRef.current?.flush()}
        />
      )}
      {showFindReplace && (
        <FindReplaceModal
          session={session}
          onClose={() => setShowFindReplace(false)}
          onApply={applyReplace}
        />
      )}
    </div>
  );
}
