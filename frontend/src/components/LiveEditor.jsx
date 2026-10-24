import React, { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import { inlineImagesInDom, restoreImagePaths } from "../utils/chapterImages.js";
import { openerParts } from "../utils/chapterOpener.js";
import { scopeCss } from "../utils/scopeCss.js";
import MarginNotes from "./MarginNotes.jsx";
import { useUi } from "./UiSwitch.jsx";

const SAVE_DEBOUNCE_MS = 700;
// The book stylesheet styles a whole page; here it may only style the
// editable text, and the page margins and paper come from .editor-surface.
const EDITOR_SCOPE = ".editor-surface__body";
const EDITOR_PAGE_RESET = `${EDITOR_SCOPE} { margin: 0 !important; background: transparent !important; }`;

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s || "";
  return div.innerHTML;
}

function getBlockAtCaret(container) {
  const sel = window.getSelection();
  if (!sel || !sel.rangeCount) return null;
  let node = sel.getRangeAt(0).startContainer;
  if (node.nodeType === 3) node = node.parentElement;
  while (node && node.parentElement !== container) {
    node = node.parentElement;
  }
  return node && node.parentElement === container ? node : null;
}

function replaceBlockTag(block, tag) {
  const el = document.createElement(tag);
  el.innerHTML = block.innerHTML;
  el.className = block.className;
  block.replaceWith(el);
  return el;
}

// Pulls the leading .chapter-eyebrow and H1/H2/H3 (the title) back out of
// the editable surface's children, treating everything after them as the
// chapter body — this is what lets the title be edited by clicking on it
// directly instead of in a separate input field.
// The body's blocks as saved HTML: figure sources go back to their
// "images/<id>.png" paths (see the note in extractEyebrowTitleBody).
function serializeBlocks(nodes) {
  return nodes
    .map((c) => {
      const copy = c.cloneNode(true);
      restoreImagePaths(copy);
      return copy.outerHTML;
    })
    .join("");
}

// How many leading children are the opening lines (label, title, author)
// rather than the chapter's body.
function openerLength(children, isSplitContinuation) {
  let idx = 0;
  if (children[idx] && children[idx].classList.contains("chapter-eyebrow")) idx++;
  if (!isSplitContinuation && children[idx] && /^H[1-3]$/.test(children[idx].tagName)) {
    idx++;
    if (children[idx] && children[idx].classList.contains("opener-byline")) idx++;
  }
  return idx;
}

function extractEyebrowTitleBody(container, isSplitContinuation) {
  const children = Array.from(container.children);
  let idx = 0;
  let eyebrow = "";
  let title = "";
  let byline = null;

  if (children[idx] && children[idx].classList.contains("chapter-eyebrow")) {
    eyebrow = children[idx].textContent.trim();
    idx++;
  }
  if (!isSplitContinuation && children[idx] && /^H[1-3]$/.test(children[idx].tagName)) {
    title = children[idx].textContent.trim();
    idx++;
    if (children[idx] && children[idx].classList.contains("opener-byline")) {
      byline = children[idx].textContent.trim();
      idx++;
    }
  }
  // Figures are shown from a data URI so they render at all (see
  // utils/chapterImages), but what gets SAVED has to be the original
  // "images/<id>.png" path — that is what the EPUB packager matches each
  // figure against, and it keeps the session from growing a copy of every
  // image on every keystroke. Restore on a clone so the visible editor is
  // never touched mid-edit.
  const html = serializeBlocks(children.slice(idx));
  return { eyebrow, title, byline, html };
}

const LiveEditor = forwardRef(function LiveEditor({ chapter, css, onSave, onSplit, saveStatus, reloadKey = 0, notes }, ref) {
  // Haşiye hangs the chapter's warnings in the page margin (MarginNotes)
  const day = useUi() === "hasiye";
  const bodyRef = useRef(null);
  const debounceRef = useRef(null);
  // Whether the editor holds edits the server has not seen. Saving only
  // then is what keeps a chapter switch from writing back a DOM that no
  // longer describes the chapter: after a split, the old DOM still held
  // both halves, and saving it on the way out copied the second half back
  // into the first.
  const dirtyRef = useRef(false);
  const [footnotes, setFootnotes] = useState(chapter?.footnotes || []);
  const scopedCss = useMemo(() => `${scopeCss(css, EDITOR_SCOPE)}\n${EDITOR_PAGE_RESET}`, [css]);

  // Which chapter's content is CURRENTLY sitting in bodyRef's DOM, plus
  // enough info to save it correctly — kept in a ref (not React state) so
  // it's always current inside the debounce timer's closure, and so we
  // can synchronously flush it the instant the chapter prop changes,
  // before the DOM gets overwritten with the next chapter's content.
  const loadedRef = useRef(null); // { id, isSplitContinuation, footnotes }

  // Save now, if there is anything to save. Resolves once the server has
  // answered; a failed save leaves the edits marked unsaved so a retry has
  // something to send.
  const flushPending = useCallback(async () => {
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
      debounceRef.current = null;
    }
    const loaded = loadedRef.current;
    if (!loaded || !bodyRef.current || !dirtyRef.current) return;
    const { eyebrow, title, byline, html } = extractEyebrowTitleBody(bodyRef.current, loaded.isSplitContinuation);
    dirtyRef.current = false;
    const ok = await onSave(loaded.id, { html, title, eyebrow, byline, footnotes: loaded.footnotes });
    if (ok === false) dirtyRef.current = true;
  }, [onSave]);

  useImperativeHandle(ref, () => ({ flush: flushPending }), [flushPending]);

  useEffect(() => {
    // Flush whatever was pending for the PREVIOUS chapter — using the
    // still-correct bodyRef content and loadedRef info from before this
    // effect touches anything — then load the new one in. A reload of the
    // same chapter (after a find-and-replace changed it on the server) has
    // nothing pending: the caller flushed before changing it.
    flushPending();
    dirtyRef.current = false;

    const nextFootnotes = chapter?.footnotes || [];
    setFootnotes(nextFootnotes);

    if (bodyRef.current && chapter && chapter.kind !== "image") {
      // Same opening lines the EPUB prints, flat so they can be read back.
      const parts = openerParts(chapter);
      bodyRef.current.innerHTML = parts.eyebrow + parts.title + parts.byline + (chapter.html || "");
      inlineImagesInDom(bodyRef.current, chapter.images);
      loadedRef.current = { id: chapter.id, isSplitContinuation: chapter.is_split_continuation, footnotes: nextFootnotes };
    } else {
      loadedRef.current = null;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chapter?.id, reloadKey]);

  const scheduleSave = useCallback(
    (footnoteOverride) => {
      if (!loadedRef.current) return;
      if (footnoteOverride) loadedRef.current = { ...loadedRef.current, footnotes: footnoteOverride };
      dirtyRef.current = true;
      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => {
        debounceRef.current = null;
        flushPending();
      }, SAVE_DEBOUNCE_MS);
    },
    [flushPending]
  );

  const handleFootnoteChange = (id, text) => {
    const next = footnotes.map((f) => (f.id === id ? { ...f, text } : f));
    setFootnotes(next);
    scheduleSave(next);
  };

  const applyToBlock = (mutator) => {
    if (!bodyRef.current) return;
    const block = getBlockAtCaret(bodyRef.current);
    if (!block) return;
    mutator(block);
    scheduleSave();
  };

  // Inserts HTML at the current caret position. Crucially, this only
  // steals focus if the editor didn't already have it — refocusing
  // unconditionally was what made "İnce Çizgi Ekle" jump to the wrong
  // spot, since re-focusing a contentEditable with no live selection
  // resets the cursor to the start of the element.
  const insertAtCaret = (htmlSnippet) => {
    if (!bodyRef.current) return;
    if (document.activeElement !== bodyRef.current) {
      bodyRef.current.focus();
    }
    document.execCommand("insertHTML", false, htmlSnippet);
    scheduleSave();
  };

  const toolbar = [
    { label: "Başlık", action: () => applyToBlock((b) => replaceBlockTag(b, "h2")) },
    { label: "Alt Başlık", action: () => applyToBlock((b) => replaceBlockTag(b, "h3")) },
    { label: "Gövde", action: () => applyToBlock((b) => { const p = replaceBlockTag(b, "p"); p.className = ""; }) },
    { label: "Kalın", action: () => applyToBlock((b) => b.classList.toggle("text-bold")) },
    { label: "Soluk", action: () => applyToBlock((b) => b.classList.toggle("text-muted")) },
    { label: "İtalik", action: () => applyToBlock((b) => b.classList.toggle("text-italic")) },
    { label: "Ortala", action: () => applyToBlock((b) => b.classList.toggle("text-center")) },
    { label: "Blok Alıntı", action: () => applyToBlock((b) => b.classList.toggle("academic-blockquote")) },
    { label: "Şiir / Mektup", action: () => applyToBlock((b) => b.classList.toggle("verse-block")) },
    { label: "Büyük Harf Başlangıcı", action: () => applyToBlock((b) => b.classList.toggle("drop-cap")) },
    { label: "❖ Süsleme Ekle", action: () => insertAtCaret('<p class="symbol-line ornamental-divider">●</p>') },
    { label: "— İnce Çizgi Ekle", action: () => insertAtCaret('<hr class="thin-rule"/>') },
  ];

  const handleSplitClick = async () => {
    if (!bodyRef.current || !chapter) return;
    const block = getBlockAtCaret(bodyRef.current);
    const children = Array.from(bodyRef.current.children);
    // Only the body is split. The opening lines stay with the first half —
    // sending them along put the chapter's title into its own text.
    const body = children.slice(openerLength(children, chapter.is_split_continuation));
    const idx = block ? body.indexOf(block) : -1;
    if (idx <= 0) {
      window.alert("Yeni bölümü başlatmak için, bölmek istediğiniz paragrafın içine tıklayın (başlık/ilk paragraf hariç).");
      return;
    }
    const newTitle = window.prompt("Yeni bölümün başlığı:", `${chapter.title} (devamı)`);
    if (newTitle === null) return;
    // Title edits made just before splitting are saved first, so the split
    // and the save cannot land in the wrong order.
    await flushPending();
    onSplit(chapter.id, serializeBlocks(body.slice(0, idx)), serializeBlocks(body.slice(idx)), newTitle);
  };

  if (!chapter) {
    return (
      <div className="editor-pane editor-pane--empty">
        <p>Düzenlemeye başlamak için bir bölüm seçin.</p>
      </div>
    );
  }

  if (chapter.kind === "image") {
    return (
      <div className="editor-pane">
        <div className="editor-pane__label">
          <span className="ruler-mark">03</span>
          Düzenleyici
        </div>
        <div className="editor-image-page">
          <p className="editor-image-page__hint">
            Bu sayfa "Görsel" olarak işaretlendi — olduğu gibi bir resim olarak EPUB'a
            eklenecek, metin olarak düzenlenemez. Sayfa İnceleme ekranına dönüp modunu
            değiştirebilirsiniz.
          </p>
          {chapter.image_base64 && (
            <img
              className="editor-image-page__preview"
              src={`data:image/png;base64,${chapter.image_base64}`}
              alt={chapter.title}
            />
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="editor-pane">
      <div className="editor-pane__label">
        <span className="ruler-mark">03</span>
        Düzenleyici
        {saveStatus === "error" ? (
          <button
            type="button"
            className="save-indicator save-indicator--error"
            onClick={() => {
              dirtyRef.current = true;
              flushPending();
            }}
            title="Son değişiklikler sunucuya ulaşmadı"
          >
            Kaydedilemedi · Tekrar dene
          </button>
        ) : (
          <span className={`save-indicator save-indicator--${saveStatus}`} aria-live="polite">
            {saveStatus === "saving" ? "Kaydediliyor…" : saveStatus === "saved" ? "Kaydedildi" : "Düzenleniyor"}
          </span>
        )}
      </div>

      <div className="editor-toolbar">
        {toolbar.map((t) => (
          <button key={t.label} onMouseDown={(e) => e.preventDefault()} onClick={t.action}>
            {t.label}
          </button>
        ))}
        <button className="editor-toolbar__split" onMouseDown={(e) => e.preventDefault()} onClick={handleSplitClick}>
          ✂ Yeni Bölüm Başlat
        </button>
      </div>

      <p className="editor-hint">
        Başlığa, üst başlığa ve metnin her yerine doğrudan tıklayıp düzenleyebilirsiniz.
      </p>

      <div className="editor-surface">
        <style>{scopedCss}</style>
        <div
          ref={bodyRef}
          className="editor-surface__body"
          contentEditable
          suppressContentEditableWarning
          spellCheck={false}
          onInput={() => scheduleSave()}
          onBlur={() => flushPending()}
        />
        {day && <MarginNotes bodyRef={bodyRef} notes={notes} version={`${chapter?.id}:${reloadKey}`} />}
      </div>

      {footnotes.length > 0 && (
        <div className="editor-footnotes">
          <p className="editor-footnotes__title">Notlar — bölüm sonuna ayrı ekleniyor</p>
          {footnotes.map((fn) => (
            <div key={fn.id} className="editor-footnotes__row">
              <span className="editor-footnotes__marker">{fn.marker}</span>
              <textarea
                defaultValue={fn.text}
                onChange={(e) => handleFootnoteChange(fn.id, e.target.value)}
                rows={2}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
});

export default LiveEditor;
