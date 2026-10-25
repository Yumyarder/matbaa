import { startEngine } from "./browser/engine.js";

const BASE = "/api";

// In the site's build the answers come from the engine in this browser
// (browser/sw.js); a request waits until the page is wired to it. On the
// desktop startEngine() is already resolved and this is plain fetch.
const fetch = (...args) => startEngine().then(() => window.fetch(...args));

async function handle(res) {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${res.status})`);
  }
  return res.json();
}

// --- Okuma Defteri: Kindle highlights into Obsidian ---------------------------
export function fetchNotebook() {
  return fetch(`${BASE}/notebook`).then(handle);
}

export function importClippings(file) {
  const form = new FormData();
  form.append("file", file);
  return fetch(`${BASE}/notebook/import`, { method: "POST", body: form }).then(handle);
}

// --- The Kindle readied: Matbaa's typefaces and its Turkish dictionary on it ---
export function kindleDevice() {
  return fetch(`${BASE}/kindle/device`).then(handle);
}

export function installKindleFonts() {
  return fetch(`${BASE}/kindle/fonts`, { method: "POST" }).then(handle);
}

export function installKindleDictionary() {
  return fetch(`${BASE}/kindle/dictionary`, { method: "POST" }).then(handle);
}

// The dictionary made again with the books added since (a background job): {state, step, message, result}
export function dictionaryRefresh() {
  return fetch(`${BASE}/kindle/dictionary/refresh`, { method: "POST" }).then(handle);
}

export function dictionaryRefreshStatus() {
  return fetch(`${BASE}/kindle/dictionary/refresh`).then(handle);
}

// --- Kelime Defteri: words looked up on the Kindle ---------------------------
export function fetchWords() {
  return fetch(`${BASE}/notebook/words`).then(handle);
}

export function wordsFromKindle() {
  return fetch(`${BASE}/notebook/words/kindle`, { method: "POST" }).then(handle);
}

export function planWords(include) {
  return postJson(`${BASE}/notebook/words/plan`, { include });
}

export function writeWords(include, token) {
  return postJson(`${BASE}/notebook/words/write`, { include, token });
}

// --- Kitapla sohbet ------------------------------------------------------------
// {question, session_id|null, model?} -> {passages, prompt, llm, answer?, check?}
export function askBook(body) {
  return postJson(`${BASE}/ask`, body);
}

// The reader's language model settings (never the key back): {provider, model, base_url, has_key, available, local}
export function fetchLlmSettings() {
  return fetch(`${BASE}/llm/settings`).then(handle);
}

export function saveLlmSettings(body) {
  return fetch(`${BASE}/llm/settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then(handle);
}

export function checkAnswer(body) {
  return postJson(`${BASE}/ask/check`, body);
}

export function planAsk(body) {
  return postJson(`${BASE}/ask/plan`, body);
}

export function writeAsk(body) {
  return postJson(`${BASE}/ask/write`, body);
}

// The index Matbaa would make for a book without one: {available, printed, on, paged, entries, removed}
export function fetchIndex(sessionId) {
  return fetch(`${BASE}/session/${sessionId}/index`).then(handle);
}

// The imprint completed online by the ISBN: {session, found, filled}
export function lookupImprint(sessionId) {
  return fetch(`${BASE}/session/${sessionId}/imprint/lookup`, { method: "POST" }).then(handle);
}

// The book's cover: "pdf" (the PDF's own), "matbaa" (set in type) or "web" (found by ISBN); returns the session
export function chooseCover(sessionId, kind) {
  return fetch(`${BASE}/session/${sessionId}/cover`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind }),
  }).then(handle);
}

// The typefaces a book can carry (backend/app/fonts.py): [{id, label, faces_css?, family_rule?}]
export function fetchFonts() {
  return fetch(`${BASE}/fonts`).then(handle);
}

// How a book can look (backend/app/builders/themes.py): [{id, label, about}]
export function fetchThemes() {
  return fetch(`${BASE}/themes`).then(handle);
}

// The genres a book can be given: [{id, label}] (app/genre.py).
export function fetchGenres() {
  return fetch(`${BASE}/genres`).then(handle);
}

// The start screen's line before any Kindle passage: {quote, book}.
export function fetchStartQuote() {
  return fetch(`${BASE}/start/quote`).then(handle);
}

// What the site's counter says: {available, total, genres, recent}.
export function fetchCounterSummary() {
  return fetch(`${BASE}/counter/summary`).then(handle);
}

// The site's counter (app/counter.py): {enabled, notice_seen, active}.
export function fetchCounter() {
  return fetch(`${BASE}/counter`).then(handle);
}

export function saveCounter(change) {
  return fetch(`${BASE}/counter`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(change),
  }).then(handle);
}

export function kindleStatus() {
  return fetch(`${BASE}/notebook/kindle/status`).then(handle);
}

export function importFromKindle() {
  return fetch(`${BASE}/notebook/kindle`, { method: "POST" }).then(handle);
}

export function fetchNotebookBook(key) {
  return fetch(`${BASE}/notebook/book/${encodeURIComponent(key)}`).then(handle);
}

function postJson(url, body) {
  return fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then(handle);
}

export function planNotebookBook(key, body) {
  return postJson(`${BASE}/notebook/book/${encodeURIComponent(key)}/plan`, body);
}

export function writeNotebookBook(key, body) {
  return postJson(`${BASE}/notebook/book/${encodeURIComponent(key)}/write`, body);
}

export function developPreview(key, id) {
  return fetch(`${BASE}/notebook/book/${encodeURIComponent(key)}/develop/${encodeURIComponent(id)}`, { method: "POST" })
    .then(handle);
}

export function developWrite(key, id, text) {
  return postJson(`${BASE}/notebook/book/${encodeURIComponent(key)}/develop/${encodeURIComponent(id)}/write`, { text });
}

export function saveNoteEdits(changes) {
  return postJson(`${BASE}/notebook/edits`, { changes });
}

export function saveAnswer(id, text, source = "chatgpt") {
  return postJson(`${BASE}/notebook/answer`, { id, text, source });
}

export function askModel(key, id) {
  return fetch(`${BASE}/notebook/book/${encodeURIComponent(key)}/ask/${encodeURIComponent(id)}`, { method: "POST" })
    .then(handle);
}

export function saveObsidianSettings(settings) {
  return postJson(`${BASE}/obsidian/settings`, settings);
}

// --- Book report ------------------------------------------------------------
// The open issues and their passages, as a file for whichever language model
// the user works with.
export function reportBundleUrl(sessionId) {
  return `${BASE}/session/${sessionId}/report/bundle`;
}

// The optional language model (backend/app/llm.py): only when the user has
// configured one, and only for the chapter they ask about.
// Send to Kindle (backend/app/kindle_send.py).
export function kindlePreview(sessionId) {
  return fetch(`${BASE}/session/${sessionId}/kindle/preview`).then(handle);
}

export function saveKindleSettings(settings) {
  return fetch(`${BASE}/kindle/settings`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  }).then(handle);
}

export function sendToKindle(sessionId) {
  return fetch(`${BASE}/session/${sessionId}/kindle/send`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirm: true }),
  }).then(handle);
}

// The EPUB as it would be exported, checked (backend/app/validate.py).
export function validateEpub(sessionId) {
  return fetch(`${BASE}/session/${sessionId}/validate`).then(handle);
}

export function fetchLlmStatus() {
  return fetch(`${BASE}/llm/status`).then(handle);
}

export function llmPropose(sessionId, chapterId) {
  return fetch(`${BASE}/session/${sessionId}/chapter/${chapterId}/llm/propose`, { method: "POST" }).then(handle);
}

export function llmApply(sessionId, chapterId, proposals) {
  return fetch(`${BASE}/session/${sessionId}/chapter/${chapterId}/llm/apply`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(proposals),
  }).then(handle);
}

// --- PDF Editor tab -------------------------------------------------------
export function fetchEditorPageInfo(uploadId, index) {
  return fetch(`${BASE}/editor/page-info/${uploadId}/${index}`).then(handle);
}

export function editorPageImageSrc(uploadId, index, dpi = 150) {
  return `${BASE}/editor/page/${uploadId}/${index}?dpi=${dpi}`;
}

export function fetchHyphenFlags(uploadId, index) {
  return fetch(`${BASE}/editor/hyphen-flags/${uploadId}/${index}`).then(handle);
}

export function fetchScanIssues(uploadId, headerRatio, footerRatio) {
  const params = new URLSearchParams();
  if (headerRatio != null) params.set("header_ratio", headerRatio);
  if (footerRatio != null) params.set("footer_ratio", footerRatio);
  const qs = params.toString() ? `?${params.toString()}` : "";
  return fetch(`${BASE}/editor/scan-issues/${uploadId}${qs}`).then(handle);
}

export function fetchPagePreviewHtml(uploadId, index, headerRatio, footerRatio) {
  const params = new URLSearchParams();
  if (headerRatio != null) params.set("header_ratio", headerRatio);
  if (footerRatio != null) params.set("footer_ratio", footerRatio);
  const qs = params.toString() ? `?${params.toString()}` : "";
  return fetch(`${BASE}/editor/page-preview-html/${uploadId}/${index}${qs}`).then(handle);
}

export function runRegionOcr(uploadId, pageIndex, bbox) {
  return fetch(`${BASE}/editor/ocr`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ upload_id: uploadId, page_index: pageIndex, bbox }),
  }).then(handle);
}

// Step 1: upload the PDF and get back page thumbnails so junk/ad pages
// (like a download site's advertisement page) can be reviewed and excluded first.
export async function uploadPdf(file, onProgress) {
  const form = new FormData();
  form.append("file", file);
  await startEngine();
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${BASE}/upload`);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) {
        onProgress(Math.round((e.loaded / e.total) * 100));
      }
    };
    xhr.onload = () => {
      try {
        const data = JSON.parse(xhr.responseText);
        if (xhr.status >= 200 && xhr.status < 300) resolve(data);
        else reject(new Error(data.detail || "Upload failed"));
      } catch (err) {
        reject(err);
      }
    };
    xhr.onerror = () => reject(new Error("Network error during upload"));
    xhr.send(form);
  });
}

// Step 1b: a scanned upload has no text to read until OCR has written one.
// The pass runs on the server and is polled, because it takes seconds per
// page — see main.start_ocr.
export function startOcr(uploadId) {
  return fetch(`${BASE}/upload/${uploadId}/ocr`, { method: "POST" }).then(handle);
}

export function cancelOcr(uploadId) {
  return fetch(`${BASE}/upload/${uploadId}/ocr/cancel`, { method: "POST" }).then(handle);
}

export function fetchOcrStatus(uploadId) {
  return fetch(`${BASE}/upload/${uploadId}/ocr-status`).then(handle);
}

// Step 2: run the actual conversion, excluding whichever pages were
// unchecked in the page-review screen.
// Where a running conversion is: {stage, done, total} (stage in the reader's words)
export function convertProgress(uploadId) {
  return fetch(`${BASE}/convert/${uploadId}/progress`).then(handle);
}

export function convertPdf(uploadId, excludedPages, coverPageIndex, imagePages = [], tocPages = [], options = {}) {
  const { headerMarginRatio, footerMarginRatio, excludedTextRegions, imageRegions, ocrRegions, autoFigures } = options;
  return fetch(`${BASE}/convert/${uploadId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      excluded_pages: excludedPages,
      cover_page_index: coverPageIndex,
      image_pages: imagePages,
      toc_pages: tocPages,
      header_margin_ratio: headerMarginRatio ?? null,
      footer_margin_ratio: footerMarginRatio ?? null,
      excluded_text_regions: excludedTextRegions || {},
      image_regions: imageRegions || [],
      ocr_regions: ocrRegions || [],
      auto_figures: autoFigures !== false,
    }),
  }).then(handle);
}

// Books kept on disk (backend/app/session_store.py).
export function fetchProjects() {
  return fetch(`${BASE}/projects`).then(handle);
}

// The book's cover, small, for the shelf ("v" changes with the book, so a new cover shows)
export function projectCoverUrl(sessionId, v) {
  return `${BASE}/projects/${sessionId}/cover.jpg?v=${encodeURIComponent(v || "")}`;
}

export function deleteProject(sessionId) {
  return fetch(`${BASE}/session/${sessionId}`, { method: "DELETE" }).then(handle);
}

export function getSession(sessionId) {
  return fetch(`${BASE}/session/${sessionId}`).then(handle);
}

export function updateChapter(sessionId, chapterId, patch) {
  return fetch(`${BASE}/session/${sessionId}/chapter/${chapterId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  }).then(handle);
}

export function splitChapter(sessionId, chapterId, beforeHtml, afterHtml, newTitle) {
  return fetch(`${BASE}/session/${sessionId}/chapter/${chapterId}/split`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ before_html: beforeHtml, after_html: afterHtml, new_title: newTitle }),
  }).then(handle);
}

export function reorderChapters(sessionId, chapterIds) {
  return fetch(`${BASE}/session/${sessionId}/reorder`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chapter_ids: chapterIds }),
  }).then(handle);
}

export function updateMeta(sessionId, meta) {
  return fetch(`${BASE}/session/${sessionId}/meta`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(meta),
  }).then(handle);
}

export function readerNotesCount(sessionId) {
  return fetch(`${BASE}/session/${sessionId}/reader-notes`).then(handle);
}

export async function exportEpub(sessionId, filename = "book.epub", withNotes = false) {
  const res = await fetch(`${BASE}/session/${sessionId}/export${withNotes ? "?notes=true" : ""}`, { method: "POST" });
  if (!res.ok) throw new Error("Export failed");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
