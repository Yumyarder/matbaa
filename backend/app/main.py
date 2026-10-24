from __future__ import annotations

import base64
import os
import re
import sys
import tempfile
import threading
import uuid
from typing import Optional

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

from app.builders.css_template import MATBAA_CSS, book_css
from app.builders.epub_builder import build_epub
from app.builders.themes import THEMES, apply_theme, theme_list
from app import book_lookup, book_names, cover as book_cover, fonts as book_fonts, imprint as book_imprint
from app import genre as book_genre, genre_lookup
from app import counter, quote_lookup
from app.models import (
    LlmProposals,
    ChapterImage,
    ChapterOut,
    ChapterSplitRequest,
    ChapterUpdate,
    ChapterWarning,
    ConversionSession,
    ConvertRequest,
    CoverChoice,
    Footnote,
    MetaUpdate,
    OcrRequest,
    PagePreviewOut,
    ReorderRequest,
    UploadPreview,
)
from app.diagnosis import build_report, llm_bundle
from app.validate import check_epub, summary as validation_summary
from app import kindle_send
from app import kindle_prep, kindle_usb, obsidian
from app import notebook as nb
from app.clippings import parse_any
from app import deasciify
from app import reader_notes
from app import llm
from app.ocr import ocr_region, OcrUnavailable
from app import ocr_layer
from app.parsers.pdf_parser import (
    convert_pdf_to_chapters,
    get_pdf_page_previews,
    get_page_dimensions,
    render_page_png,
    get_hyphen_flags,
    scan_pages_for_issues,
    get_page_preview_html,
    _page_text_is_ocr,
)
from app.session_store import delete_session, get_session, list_projects, save_session


def resource_path(relative_path: str) -> str:
    """Resolve a path that works both when running normally (`uvicorn
    app.main:app`) and when frozen into a PyInstaller onefile .exe, where
    bundled data files are unpacked to a temp dir at sys._MEIPASS."""
    base_path = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


app = FastAPI(title="Matbaa — Academic PDF -> Kindle EPUB Converter")

_DEV_ORIGINS = {"http://localhost:5173", "http://127.0.0.1:5173"}

app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(_DEV_ORIGINS),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# The API listens only on this computer, but any web page the reader opens
# can still send requests to 127.0.0.1 from their browser: a form post or a
# file upload needs no permission (CORS only stops the page reading the
# answer), and a domain made to resolve to 127.0.0.1 (DNS rebinding) can read
# answers too. So the Host must name this computer, and anything that
# changes something must come from Matbaa's own page (or the dev server).
# "testserver" is the Host Starlette's TestClient sends in the tests.
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "testserver"}
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _refuse(message: str) -> JSONResponse:
    return JSONResponse({"detail": message}, status_code=403)


@app.middleware("http")
async def only_from_this_computer(request: Request, call_next):
    host_header = request.headers.get("host") or ""
    host = host_header.rsplit(":", 1)[0].lower() if not host_header.endswith("]") else host_header.lower()
    if host not in _LOCAL_HOSTS:
        return _refuse("Matbaa yalnız bu bilgisayardan kullanılabilir.")
    if request.method not in _SAFE_METHODS:
        origin = request.headers.get("origin")
        own = f"{request.url.scheme}://{host_header}"
        if origin is not None and origin != own and origin not in _DEV_ORIGINS:
            return _refuse("Bu istek Matbaa'nın kendi sayfasından gelmedi.")
        if request.headers.get("sec-fetch-site") == "cross-site":
            return _refuse("Bu istek Matbaa'nın kendi sayfasından gelmedi.")
    return await call_next(request)

TEMP_DIR = tempfile.gettempdir()


def _uploaded_file_path(upload_id: str) -> str:
    return os.path.join(TEMP_DIR, f"upload_{upload_id}.pdf")


def _ocr_copy_path(upload_id: str) -> str:
    return os.path.join(TEMP_DIR, f"upload_{upload_id}_ocr.pdf")


def _upload_name_path(upload_id: str) -> str:
    """The name of the file the reader chose: the last place a book's title
    and author are looked for (app/book_names.py)."""
    return os.path.join(TEMP_DIR, f"upload_{upload_id}.name")


def _upload_name(upload_id: str) -> Optional[str]:
    try:
        with open(_upload_name_path(upload_id), encoding="utf-8") as fh:
            return fh.read().strip() or None
    except OSError:
        return None


def _upload_pdf_path(upload_id: str) -> str:
    """The file every other endpoint should read.

    Once a scanned upload has been given a text layer (see ocr_layer), the
    searchable copy IS the upload: same pages, same page sizes, same
    coordinates for masks and regions — only now with words on it. Routing
    every reader through here is what keeps OCR out of the rest of the app.
    """
    ocr_copy = _ocr_copy_path(upload_id)
    return ocr_copy if os.path.exists(ocr_copy) else _uploaded_file_path(upload_id)


# upload_id -> {"state", "done", "total", "message"} for a running OCR pass.
_ocr_jobs: dict = {}
_ocr_jobs_lock = threading.Lock()


def _ocr_job_state(upload_id: str) -> dict:
    with _ocr_jobs_lock:
        return dict(_ocr_jobs.get(upload_id, {"state": "idle", "done": 0, "total": 0, "message": None}))


def _set_ocr_job(upload_id: str, **fields) -> None:
    with _ocr_jobs_lock:
        job = _ocr_jobs.setdefault(upload_id, {"state": "idle", "done": 0, "total": 0, "message": None})
        job.update(fields)


@app.get("/api/health")
def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Step 1: upload -> page thumbnails, so junk/ad pages can be excluded first
# ---------------------------------------------------------------------------
@app.post("/api/upload", response_model=UploadPreview)
async def upload_pdf(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Please upload a .pdf file")

    upload_id = str(uuid.uuid4())
    pdf_path = _uploaded_file_path(upload_id)
    with open(pdf_path, "wb") as f:
        f.write(await file.read())
    with open(_upload_name_path(upload_id), "w", encoding="utf-8") as f:
        f.write(os.path.basename(file.filename))

    try:
        needs = ocr_layer.pages_needing_ocr(pdf_path)
        previews = get_pdf_page_previews(pdf_path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Could not read PDF: {exc}") from exc

    return UploadPreview(
        upload_id=upload_id,
        page_count=len(previews),
        pages=_previews_out(previews),
        scanned_pages=needs.pages,
        ocr_reason=needs.reason or ("scan" if needs.pages else None),
        ocr_available=ocr_layer.ocr_available(),
        ocr_message=None if ocr_layer.ocr_available() else ocr_layer.unavailable_message(),
    )


def _previews_out(previews) -> list:
    return [
        PagePreviewOut(
            index=p.index,
            text_snippet=p.text_snippet,
            thumbnail_base64=p.thumbnail_base64,
            likely_junk=p.likely_junk,
            suggested_mode=p.suggested_mode,
        )
        for p in previews
    ]


# ---------------------------------------------------------------------------
# Step 1b: a scanned upload is read by OCR before it is reviewed
# ---------------------------------------------------------------------------
# This runs in its own thread and is polled, rather than being done inside
# the upload request, because it takes a couple of seconds per page: a
# 300-page scan would hold a request open for a quarter of an hour and time
# out in the browser long before it finished. The person watches it count
# the pages, and can skip it.
class _OcrCancelled(Exception):
    pass


def _run_ocr_job(upload_id: str, pages: list) -> None:
    def progress(done: int, total: int) -> None:
        # Checked between pages: a skipped pass stops, rather than finishing
        # in the background and swapping the file under a later conversion.
        if _ocr_job_state(upload_id)["state"] == "cancelling":
            raise _OcrCancelled()
        _set_ocr_job(upload_id, done=done, total=total)

    try:
        ocr_layer.build_searchable_copy(
            _uploaded_file_path(upload_id),
            _ocr_copy_path(upload_id),
            pages=pages,
            progress=progress,
        )
        _set_ocr_job(upload_id, state="done")
    except _OcrCancelled:
        _set_ocr_job(upload_id, state="cancelled")
    except ocr_layer.OcrUnavailable as exc:
        _set_ocr_job(upload_id, state="error", message=str(exc))
    except Exception as exc:  # noqa: BLE001 — reported, never swallowed
        _set_ocr_job(upload_id, state="error", message=f"OCR sırasında hata: {exc}")


@app.post("/api/upload/{upload_id}/ocr")
def start_ocr(upload_id: str):
    if not os.path.exists(_uploaded_file_path(upload_id)):
        raise HTTPException(404, "Upload not found or already expired — please re-upload")
    if not ocr_layer.ocr_available():
        _set_ocr_job(upload_id, state="unavailable", message=ocr_layer.unavailable_message())
        return _ocr_job_state(upload_id)
    if _ocr_job_state(upload_id)["state"] == "running":
        return _ocr_job_state(upload_id)
    if os.path.exists(_ocr_copy_path(upload_id)):
        _set_ocr_job(upload_id, state="done")
        return _ocr_job_state(upload_id)

    pages = ocr_layer.pages_needing_ocr(_uploaded_file_path(upload_id)).pages
    _set_ocr_job(upload_id, state="running", done=0, total=len(pages), message=None)
    threading.Thread(target=_run_ocr_job, args=(upload_id, pages), daemon=True).start()
    return _ocr_job_state(upload_id)


@app.post("/api/upload/{upload_id}/ocr/cancel")
def cancel_ocr(upload_id: str):
    if _ocr_job_state(upload_id)["state"] == "running":
        _set_ocr_job(upload_id, state="cancelling")
    return _ocr_job_state(upload_id)


@app.get("/api/upload/{upload_id}/ocr-status")
def ocr_status(upload_id: str):
    state = _ocr_job_state(upload_id)
    # Fresh page suggestions, now that the pages have words on them: a
    # scanned page the review screen could only call a picture is a text
    # page once it can be read.
    if state["state"] == "done":
        previews = get_pdf_page_previews(_upload_pdf_path(upload_id))
        state["pages"] = _previews_out(previews)
    return state


# ---------------------------------------------------------------------------
# PDF Editor tab (Step 1: page render + dimensions for the mask-lines tool)
# ---------------------------------------------------------------------------
# These read the SAME uploaded file the Page Review flow uses (kept alive
# until /api/convert/{upload_id} runs and deletes it) — the editor operates
# on the raw upload, before conversion, so it never touches a conversion
# session at all.
@app.get("/api/editor/page-info/{upload_id}/{index}")
def editor_page_info(upload_id: str, index: int):
    pdf_path = _upload_pdf_path(upload_id)
    if not os.path.exists(pdf_path):
        raise HTTPException(404, "Upload not found or already expired — please re-upload")
    info = get_page_dimensions(pdf_path, index)
    if info is None:
        raise HTTPException(404, "Page not found")
    return info


@app.get("/api/editor/page/{upload_id}/{index}")
def editor_page_image(upload_id: str, index: int, dpi: int = 150):
    pdf_path = _upload_pdf_path(upload_id)
    if not os.path.exists(pdf_path):
        raise HTTPException(404, "Upload not found or already expired — please re-upload")
    # Clamp to sane bounds — this is a user-facing zoom control, not
    # something that should be able to request an arbitrarily huge render.
    dpi = max(72, min(dpi, 400))
    png_bytes = render_page_png(pdf_path, index, dpi)
    if png_bytes is None:
        raise HTTPException(404, "Page not found")
    return Response(content=png_bytes, media_type="image/png")


@app.get("/api/editor/hyphen-flags/{upload_id}/{index}")
def editor_hyphen_flags(upload_id: str, index: int):
    pdf_path = _upload_pdf_path(upload_id)
    if not os.path.exists(pdf_path):
        raise HTTPException(404, "Upload not found or already expired — please re-upload")
    flags = get_hyphen_flags(pdf_path, index)
    if flags is None:
        raise HTTPException(404, "Page not found")
    return {"flags": flags}


@app.get("/api/editor/scan-issues/{upload_id}")
def editor_scan_issues(upload_id: str, header_ratio: Optional[float] = None, footer_ratio: Optional[float] = None):
    pdf_path = _upload_pdf_path(upload_id)
    if not os.path.exists(pdf_path):
        raise HTTPException(404, "Upload not found or already expired — please re-upload")
    issues = scan_pages_for_issues(pdf_path, header_ratio, footer_ratio)
    return {"issues": issues}


@app.get("/api/editor/page-preview-html/{upload_id}/{index}")
def editor_page_preview_html(
    upload_id: str, index: int, header_ratio: Optional[float] = None, footer_ratio: Optional[float] = None
):
    pdf_path = _upload_pdf_path(upload_id)
    if not os.path.exists(pdf_path):
        raise HTTPException(404, "Upload not found or already expired — please re-upload")
    preview_html = get_page_preview_html(pdf_path, index, header_ratio, footer_ratio)
    if preview_html is None:
        raise HTTPException(404, "Page not found")
    return {"html": preview_html, "css": MATBAA_CSS}


@app.post("/api/editor/ocr")
def editor_ocr(body: OcrRequest):
    pdf_path = _upload_pdf_path(body.upload_id)
    if not os.path.exists(pdf_path):
        raise HTTPException(404, "Upload not found or already expired — please re-upload")
    try:
        result = ocr_region(pdf_path, body.page_index, body.bbox, body.lang)
    except OcrUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"OCR failed: {exc}") from exc
    return result


# ---------------------------------------------------------------------------
# Step 2: convert, excluding whichever pages the person unchecked
# ---------------------------------------------------------------------------
_convert_progress: dict = {}
_convert_progress_lock = threading.Lock()


def _tell_progress(upload_id: str, stage: Optional[str], done: int = 0, total: int = 0) -> None:
    with _convert_progress_lock:
        if stage is None:
            _convert_progress.pop(upload_id, None)
        else:
            _convert_progress[upload_id] = {"stage": stage, "done": done, "total": total}


@app.get("/api/convert/{upload_id}/progress")
def convert_progress(upload_id: str):
    """Where a running conversion is: {stage, done, total}; stage is None
    when nothing is running for this upload."""
    with _convert_progress_lock:
        return dict(_convert_progress.get(upload_id, {"stage": None, "done": 0, "total": 0}))


@app.post("/api/convert/{upload_id}", response_model=ConversionSession)
def convert_pdf(upload_id: str, body: ConvertRequest):
    pdf_path = _upload_pdf_path(upload_id)
    if not os.path.exists(pdf_path):
        raise HTTPException(404, "Upload not found or already expired — please re-upload")
    try:
        return _convert(upload_id, pdf_path, body)
    finally:
        _tell_progress(upload_id, None)


def _convert(upload_id: str, pdf_path: str, body: ConvertRequest):
    _tell_progress(upload_id, "Başlıyor")
    try:
        result = convert_pdf_to_chapters(
            pdf_path,
            excluded_pages=set(body.excluded_pages),
            cover_page_index=body.cover_page_index,
            image_pages=set(body.image_pages),
            toc_pages=set(body.toc_pages),
            header_ratio=body.header_margin_ratio,
            footer_ratio=body.footer_margin_ratio,
            excluded_text_regions=body.excluded_text_regions or None,
            image_regions=[r.model_dump() for r in body.image_regions] or None,
            ocr_regions=[r.model_dump() for r in body.ocr_regions] or None,
            auto_figures=body.auto_figures,
            progress=lambda stage, done, total: _tell_progress(upload_id, stage, done, total),
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Conversion failed: {exc}") from exc
    _tell_progress(upload_id, "Künye, rapor ve kitap kaydı")

    session_id = str(uuid.uuid4())
    chapters_out = [
        ChapterOut(
            id=ch.id,
            index=ch.index,
            title=ch.title,
            kind=ch.kind,
            eyebrow=ch.eyebrow,
            html="".join(ch.paragraphs),
            footnotes=[Footnote(id=fn.id, marker=fn.marker, text=fn.text) for fn in ch.footnotes],
            is_split_continuation=ch.is_split_continuation,
            image_base64=ch.image_base64,
            images=[ChapterImage(**img) for img in ch.images],
            byline=ch.byline,
            toc_path=list(ch.toc_path),
            opener=ch.opener,
        )
        for ch in result.chapters
    ]

    # what the PDF could not tell, the name of the file the reader chose may
    book_title, author = book_names.fill(result.detected_title, result.detected_author,
                                         _upload_name(upload_id), result.detected_language)
    session = ConversionSession(
        session_id=session_id,
        book_title=book_title,
        author=author,
        language=result.detected_language,
        chapters=chapters_out,
        css=book_css(result.paragraph_style),
        warnings=result.warnings,
        chapter_warnings=[ChapterWarning(**cw) for cw in result.chapter_warnings],
        cover_image_base64=book_cover.clean_base64(result.cover_image_base64),
        report=_book_report(result, pdf_path, upload_id),
        imprint=_book_imprint(pdf_path),
    )
    _tell_progress(upload_id, "Kitabın türü")
    _guess_genre(session, pdf_path)
    save_session(session)

    for path in (pdf_path, _uploaded_file_path(upload_id), _ocr_copy_path(upload_id), _upload_name_path(upload_id)):
        try:
            os.remove(path)
        except OSError:
            pass
    with _ocr_jobs_lock:
        _ocr_jobs.pop(upload_id, None)

    return session


def _book_imprint(pdf_path: str) -> Optional[dict]:
    """The book's imprint from its own pages; a failure here must never cost
    the conversion."""
    try:
        found = book_imprint.read_pdf(pdf_path)
        return None if found.empty() else found.to_dict()
    except Exception:  # noqa: BLE001
        return None


def _guess_genre(session: ConversionSession, pdf_path: str) -> None:
    """The book's genre: Wikidata's word when Matbaa runs as the reader's
    app (MATBAA_ONLINE), else the book's own reading; a failure here must
    never cost the conversion."""
    try:
        front = book_genre.front_pages_text(pdf_path) if pdf_path else ""
        local = book_genre.guess_session(session, front)
        online = genre_lookup.look_up(session.book_title, session.author) if os.environ.get("MATBAA_ONLINE") else None
        found = book_genre.decide(local, online)
        session.genre, session.genre_reason = found.key, found.reason
        session.genre_source = "wikidata" if online is not None and found.reason == online.reason else "auto"
    except Exception:  # noqa: BLE001
        session.genre, session.genre_source, session.genre_reason = "diger", "auto", None


def _fill_genres() -> None:
    """Books converted before Matbaa guessed genres get one, once, in the
    background: from their text (the PDF is gone), and from Wikidata in the
    reader's app, a request a second as Wikidata asks."""
    import time

    for p in list_projects():
        if p.get("genre"):
            continue
        session = get_session(p["session_id"])
        if not session or session.genre:
            continue
        _guess_genre(session, "")
        save_session(session)
        if os.environ.get("MATBAA_ONLINE"):
            time.sleep(1)


@app.on_event("startup")
def _background_fills() -> None:
    threading.Thread(target=_fill_genres, daemon=True).start()


def _book_report(result, pdf_path: str, upload_id: str) -> Optional[dict]:
    """The book's report; a failure here must never cost the conversion."""
    try:
        import fitz
        with fitz.open(pdf_path) as doc:
            producer = (doc.metadata or {}).get("producer") or ""
            ocr_pages = sum(1 for page in doc if _page_text_is_ocr(page))
        context = {"producer": producer, "ocr_pages": ocr_pages}
        return build_report(result, context).to_dict()
    except Exception:  # noqa: BLE001
        return None


# --- Okuma Defteri: Kindle highlights into Obsidian (docs/MATBAA3.md, phase A) ---------

def _nb_book(key: str):
    book = next((b for b in nb.current_books() if b.key == key), None)
    if book is None:
        raise HTTPException(404, "Bu kitabın vurguları bulunamadı.")
    return nb.with_edits(book)


def _nb_project(book):
    """The saved Matbaa book a Kindle book is, and its highlights placed in it."""
    project = nb.best_project(book, list_projects())
    placements = {}
    if project:
        session = get_session(project["session_id"])
        if session:
            placements = nb.place_book(book, session)
    return project, placements


def _nb_vault() -> tuple:
    settings = obsidian.load_settings()
    vault = settings.get("vault")
    if not vault or not os.path.isdir(vault):
        raise HTTPException(409, obsidian.vault_problem(vault))
    return vault, settings


def _nb_for_note(book, project, vault, settings):
    """The book as its note is named: a Matbaa book's clean title, unless
    the vault already has a note under the Kindle's title."""
    from dataclasses import replace
    folder = obsidian.book_folder(vault, settings)
    if project and not obsidian.find_book_note(folder, book.title):
        return replace(book, title=project["book_title"], author=book.author or project.get("author") or "")
    return book


def _nb_list():
    settings = obsidian.load_settings()
    vault = settings.get("vault")
    folder = obsidian.book_folder(vault, settings) if vault and os.path.isdir(vault) else None
    projects = list_projects()
    books = []
    for b in nb.current_books():
        hs = [h for h in b.highlights if h.text]
        project = nb.best_project(b, projects)
        note = obsidian.find_book_note(folder, b.title) if folder else None
        if not note and folder and project:
            note = obsidian.find_book_note(folder, project["book_title"])
        books.append({
            "key": b.key, "kindle_title": b.title,
            "title": os.path.basename(note)[:-3] if note else project["book_title"] if project else b.title,
            "author": b.author, "highlights": len(hs), "notes": sum(1 for h in b.highlights if h.note),
            "limited": b.limited,
            "questions": sum(1 for h in b.highlights if obsidian.is_question(h.note)),
            "ideas": sum(1 for h in b.highlights if obsidian.is_idea(h.note)),
            "project": {"session_id": project["session_id"], "title": project["book_title"]} if project else None,
            "note": os.path.basename(note)[:-3] if note else None,
            "last": max((h.added for h in b.highlights if h.added), default=""),
            "session": nb.last_session(b),
        })
    return {"books": books, "settings": {**settings, "vault_ok": bool(vault and os.path.isdir(vault)),
                                          "llm": llm.status().get("available", False),
                                          "vault_problem": None if (vault and os.path.isdir(vault))
                                          else obsidian.vault_problem(vault)}}


@app.get("/api/notebook")
def notebook_books():
    return _nb_list()


@app.post("/api/notebook/import")
async def notebook_import(file: UploadFile = File(...)):
    data = await file.read()
    clips = parse_any(data)
    if not clips:
        raise HTTPException(400, "Dosyada Kindle vurgusu bulunamadı. My Clippings.txt ya da Kindle not dışa aktarımı (HTML) olmalı.")
    added = nb.import_clips(clips)
    return {**_nb_list(), "imported": added}


@app.get("/api/notebook/kindle/status")
def notebook_kindle_status():
    st = kindle_usb.state()
    return {"connected": st != "NO_KINDLE", "ready": st == "READY", "state": st,
            "message": kindle_usb.MESSAGES.get(st) if st not in ("READY", "NO_KINDLE") else None}


@app.get("/api/kindle/device")
def kindle_device():
    """What the plugged-in Kindle has of Matbaa's typefaces and dictionary."""
    return kindle_prep.report()


@app.post("/api/kindle/fonts")
def kindle_fonts():
    """Matbaa's typefaces put on the Kindle (its fonts/ folder), for every
    book's Aa menu; nothing already there is touched."""
    try:
        done = kindle_prep.install_fonts()
    except kindle_usb.KindleNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    if any(v == "TIMEOUT" for v in done.values()):
        raise HTTPException(504, "Yazı tiplerinin bir kısmı Kindle'a kopyalanamadı (zaman aşımı); kabloyu "
                                 "çıkarıp yeniden takıp deneyin.")
    return {"files": done, **kindle_prep.report()}


@app.post("/api/kindle/dictionary")
def kindle_dictionary():
    """Matbaa's Turkish dictionary put on the Kindle (documents/dictionaries)."""
    try:
        done = kindle_prep.install_dictionary(replace=True)    # an older make of it gives way
    except FileNotFoundError as exc:
        raise HTTPException(409, "Türkçe sözlük henüz yapılmadı (tools/make_dictionary.py).") from exc
    except kindle_usb.KindleNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    if any(v == "TIMEOUT" for v in done.values()):
        raise HTTPException(504, "Sözlük Kindle'a kopyalanamadı (zaman aşımı); kabloyu çıkarıp yeniden takıp deneyin.")
    return {"files": done, **kindle_prep.report()}


# --- Kitapla sohbet: search a book, ask it, check the answer --------------------------

_INDEXES: dict = {}


def _search_indexes(session_id: Optional[str] = None):
    """The search index of one saved book, or of every one; rebuilt when a
    book's text changed since."""
    from app import search
    ids = [session_id] if session_id else [p["session_id"] for p in list_projects()]
    dictionary = _word_dictionary()
    lemma = dictionary.lemmatizer().lemma if dictionary is not None else None
    out = []
    for sid in ids:
        session = get_session(sid)
        if session is None:
            continue
        stamp = (len(session.chapters), sum(len(c.html or "") for c in session.chapters), lemma is not None)
        cached = _INDEXES.get(sid)
        if not cached or cached[0] != stamp:
            cached = (stamp, search.BookIndex(session, lemma))
            _INDEXES[sid] = cached
        out.append(cached[1])
    return out


@app.get("/api/search")
def search_books(q: str, session_id: Optional[str] = None, limit: int = 12):
    """Passages of one book (or of every saved book) that a question or a
    few words are about, with their pages."""
    from app import search
    if not q.strip():
        return {"hits": []}
    indexes = _search_indexes(session_id)
    if session_id and not indexes:
        raise HTTPException(404, "Session not found")
    return {"hits": [h.to_dict() for h in search.search(indexes, q, min(max(limit, 1), 30))]}


def _ask_passages(body: dict):
    from app import search
    question = (body or {}).get("question", "").strip()
    if not question:
        raise HTTPException(400, "Bir soru yazın.")
    session_id = (body or {}).get("session_id")
    indexes = _search_indexes(session_id)
    if session_id and not indexes:
        raise HTTPException(404, "Session not found")
    return question, session_id, search.passages(indexes, question, 8)


@app.post("/api/ask")
def ask_book(body: dict):
    """The question's passages and the request made of them — to copy to
    ChatGPT, or answered here when a model is configured and asked for."""
    from app import ask
    question, session_id, hits = _ask_passages(body)
    out = {"question": question, "passages": [h.to_dict() for h in hits],
           "prompt": ask.prompt(question, hits), "llm": llm.status().get("available", False)}
    if (body or {}).get("model") and hits:
        if not out["llm"]:
            raise HTTPException(409, "Dil modeli ayarlı değil; isteği kopyalayıp ChatGPT'ye götürebilirsin.")
        try:
            answer = llm.complete(ask.SYSTEM, ask.prompt(question, hits, with_instructions=False),
                                  max_tokens=1500).strip()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"Model yanıt veremedi: {exc}") from exc
        out["answer"] = answer
        out["check"] = ask.check(answer, hits, get_session(session_id) if session_id else None)
    return out


@app.post("/api/ask/check")
def ask_check(body: dict):
    """An answer (pasted from ChatGPT) checked against the book: its
    quotations, and the pages they are cited on."""
    from app import ask
    question, session_id, hits = _ask_passages(body)
    return ask.check((body or {}).get("answer", ""), hits, get_session(session_id) if session_id else None)


def _ask_plan(body: dict):
    from app import ask
    question, session_id, hits = _ask_passages(body)
    answer = (body or {}).get("answer", "").strip()
    if not answer:
        raise HTTPException(400, "Kaydedilecek bir yanıt yok.")
    session = get_session(session_id) if session_id else None
    if session is None:
        raise HTTPException(400, "Soru bir kitaba sorulmalı.")
    vault, settings = _nb_vault()
    folder = obsidian.book_folder(vault, settings)
    note = obsidian.find_book_note(folder, session.book_title)
    path = note or os.path.join(folder, obsidian._safe_name(session.book_title) + ".md")
    return ask.plan_note(path, note is not None, question, answer, hits, session.book_title, session.author)


@app.post("/api/ask/plan")
def ask_plan(body: dict):
    """The book's note as it would be with the question and its answer."""
    fp = _ask_plan(body)
    import hashlib
    return {"file": {"path": fp.path, "name": os.path.basename(fp.path), "exists": fp.exists, "diff": fp.diff,
                     "text": fp.text}, "token": hashlib.sha1(fp.text.encode("utf-8")).hexdigest()[:16]}


@app.post("/api/ask/write")
def ask_write(body: dict):
    """Write the plan the reader saw — refused if anything changed since."""
    import hashlib
    from app import wordbook
    fp = _ask_plan(body)
    if not body or body.get("token") != hashlib.sha1(fp.text.encode("utf-8")).hexdigest()[:16]:
        raise HTTPException(409, "Not, önizlemeden sonra değişti; önizlemeyi yenileyip tekrar deneyin.")
    return wordbook.write(fp)


# --- Kelime Defteri: words looked up on the Kindle -----------------------------------

_DICTIONARY: dict = {}


def _word_dictionary():
    """The Turkish dictionary Matbaa reads itself (tr.db), or None until it
    is made (tools/make_dictionary.py)."""
    from app import dictionary
    if "d" not in _DICTIONARY and dictionary.Dictionary.available():
        _DICTIONARY["d"] = dictionary.Dictionary()
    return _DICTIONARY.get("d")


def _words(vault=None, settings=None):
    from app import vocab, wordbook
    index = obsidian.vault_index(vault) if vault and os.path.isdir(vault) else {}
    return wordbook.entries(vocab.load(), list_projects(), get_session, _word_dictionary(), vault, settings, index)


def _words_view(words, vault, settings):
    from app import wordbook
    there = set()
    if vault and os.path.isdir(vault):
        path = wordbook.note_path(vault, settings)
        if os.path.isfile(path):
            there = wordbook.ids_in(open(path, encoding="utf-8").read())
    return {"words": [{**w.to_dict(), "in_note": w.id in there} for w in reversed(words)],
            "dictionary": _word_dictionary() is not None}


@app.get("/api/notebook/words")
def notebook_words():
    settings = obsidian.load_settings()
    vault = settings.get("vault")
    return _words_view(_words(vault, settings), vault, settings)


@app.post("/api/notebook/words/kindle")
def notebook_words_from_kindle():
    """The plugged-in Kindle's looked-up words, kept in the notebook."""
    from app import vocab
    try:
        found = vocab.from_kindle()
    except kindle_usb.KindleNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except FileNotFoundError:
        found = []
    added = vocab.import_lookups(found)
    settings = obsidian.load_settings()
    vault = settings.get("vault")
    return {**_words_view(_words(vault, settings), vault, settings), "imported": added}


def _words_plan(body: dict):
    from app import wordbook
    vault, settings = _nb_vault()
    include = (body or {}).get("include")
    return wordbook.plan(_words(vault, settings), vault, settings, set(include) if include is not None else None)


@app.post("/api/notebook/words/plan")
def notebook_words_plan(body: dict):
    plan = _words_plan(body)
    fp = plan["file"]
    return {"file": {"path": fp.path, "name": os.path.basename(fp.path), "exists": fp.exists, "diff": fp.diff,
                     "text": fp.text}, "added": plan["added"], "already": plan["already"], "token": plan["token"]}


@app.post("/api/notebook/words/write")
def notebook_words_write(body: dict):
    """Write the plan the reader saw — refused if anything changed since."""
    from app import wordbook
    plan = _words_plan(body)
    if not body or body.get("token") != plan["token"]:
        raise HTTPException(409, "Not, önizlemeden sonra değişti; önizlemeyi yenileyip tekrar deneyin.")
    return wordbook.write(plan["file"])


_DICT_JOB: dict = {"state": "idle", "step": None, "message": None, "result": None}
_DICT_JOB_LOCK = threading.Lock()


def _dictionary_job() -> None:
    from app import dictionary_build

    def step(text: str) -> None:
        with _DICT_JOB_LOCK:
            _DICT_JOB["step"] = text

    try:
        with _DICT_JOB_LOCK:
            old = _DICTIONARY.pop("d", None)
        if old is not None:
            old.close()
        result = dictionary_build.rebuild(step)
        copied = None
        if kindle_usb.state() == "READY" and kindle_prep.report()["matbaa_dictionary"]["on_kindle"]:
            step("Kindle'daki sözlüğün yerine konuyor")
            copied = kindle_prep.install_dictionary(replace=True)
        with _DICT_JOB_LOCK:
            _DICT_JOB.update(state="done", step=None, result={**result, "kindle": copied},
                             message=None)
    except Exception as exc:  # noqa: BLE001 - reported to the page
        with _DICT_JOB_LOCK:
            _DICT_JOB.update(state="error", step=None, message=str(exc))


@app.post("/api/kindle/dictionary/refresh")
def kindle_dictionary_refresh():
    """The Turkish dictionary made again with the books added since, and put
    in place of the one on the Kindle if it is plugged in: a few minutes,
    in the background."""
    with _DICT_JOB_LOCK:
        if _DICT_JOB["state"] == "running":
            return dict(_DICT_JOB)
        _DICT_JOB.update(state="running", step="Başlıyor", message=None, result=None)
    threading.Thread(target=_dictionary_job, daemon=True).start()
    with _DICT_JOB_LOCK:
        return dict(_DICT_JOB)


@app.get("/api/kindle/dictionary/refresh")
def kindle_dictionary_refresh_status():
    with _DICT_JOB_LOCK:
        return dict(_DICT_JOB)


@app.post("/api/notebook/kindle")
def notebook_from_kindle():
    try:
        data = kindle_usb.fetch_clippings()
    except kindle_usb.KindleNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    added = nb.import_clips(parse_any(data))
    return {**_nb_list(), "imported": added}


@app.get("/api/notebook/book/{key}")
def notebook_book(key: str):
    book = _nb_book(key)
    project, placements = _nb_project(book)
    settings = obsidian.load_settings()
    vault = settings.get("vault")
    index = obsidian.vault_index(vault) if vault and os.path.isdir(vault) else {}
    met = obsidian.encounters(vault, settings) if vault and os.path.isdir(vault) else {}
    items = []
    answers = nb.load_answers()
    for h in book.highlights:
        view = nb.highlight_view(h, placements.get(h.id))
        view["answer"] = (answers.get(h.id) or {}).get("text")
        restored, changes = deasciify.restore(h.note) if h.note else ("", [])
        view["note_suggestion"] = restored if changes else None
        link, exists = obsidian.link_for(h.text, index) if h.text else (None, False)
        kind = obsidian.classify_note(h.note)
        note_links = [obsidian.resolve_name(x, index) for x in kind.names]
        view.update({"link": link, "link_exists": exists, "question": kind.kind == "question",
                     "note_kind": kind.kind, "note_text": kind.text,
                     "note_links": [{"name": n, "exists": e} for n, e in note_links]})
        names = ([link] if link else []) + [n for n, _ in note_links]
        view["seen_in"] = sorted({other for n in names for other in met.get(nb.fold_ascii(n), [])})
        items.append(view)
    note = None
    if vault and os.path.isdir(vault):
        folder = obsidian.book_folder(vault, settings)
        note = obsidian.find_book_note(folder, book.title) or (
            obsidian.find_book_note(folder, project["book_title"]) if project else None)
    title = os.path.basename(note)[:-3] if note else project["book_title"] if project else book.title
    for item in items:
        item["seen_in"] = [x for x in item.get("seen_in", []) if x != title]
    return {"key": book.key, "title": title, "author": book.author, "project": project, "limited": book.limited,
            "note": os.path.basename(note)[:-3] if note else None, "highlights": items}


def _nb_plan(key: str, body: dict):
    book = _nb_book(key)
    project, placements = _nb_project(book)
    vault, settings = _nb_vault()
    body = body or {}
    links = {k: (v or None) for k, v in (body.get("links") or {}).items()}
    answers = {k: v["text"] for k, v in nb.load_answers().items() if v.get("text")}
    return obsidian.plan_book(_nb_for_note(book, project, vault, settings), placements, vault, settings,
                              dropped=set(body.get("dropped") or []), link_choice=links,
                              include=set(body.get("include") or []), answers=answers)


@app.post("/api/notebook/book/{key}/plan")
def notebook_plan(key: str, body: dict):
    plan = _nb_plan(key, body)
    out = plan.to_dict()
    out["note"]["name"] = os.path.basename(plan.note.path)
    return out


@app.post("/api/notebook/book/{key}/write")
def notebook_write(key: str, body: dict):
    """Write the plan the reader saw — refused if anything changed since."""
    plan = _nb_plan(key, body)
    if not body or body.get("token") != plan.token:
        raise HTTPException(409, "Not, önizlemeden sonra değişti; önizlemeyi yenileyip tekrar deneyin.")
    return obsidian.apply_plan(plan)


@app.post("/api/notebook/edits")
def notebook_edits(body: dict):
    """The reader's corrections to their own notes: {"changes": {id: note
    or null to undo}}. Applied on their click only — Turkish letters
    restored from the suggestion, or the note retyped."""
    changes = (body or {}).get("changes") or {}
    if not isinstance(changes, dict):
        raise HTTPException(400, "Düzeltmeler okunamadı.")
    edits = nb.save_edits(changes)
    return {"saved": len(changes), "edits": len(edits)}


@app.post("/api/notebook/answer")
def notebook_answer(body: dict):
    """The answer the reader brought back for a question (pasted from
    ChatGPT); written into the note on the next "Obsidian'a yaz"."""
    hid = (body or {}).get("id")
    if not hid:
        raise HTTPException(400, "Hangi vurgunun yanıtı olduğu belirtilmedi.")
    nb.save_answer(hid, (body or {}).get("text", ""), (body or {}).get("source", "chatgpt"))
    return {"id": hid, "answer": (nb.load_answers().get(hid) or {}).get("text")}


_QUOTED = re.compile(r"[“\"«]([^”\"»]{25,})[”\"»]")


@app.post("/api/notebook/book/{key}/ask/{hid}")
def notebook_ask_model(key: str, hid: str):
    """A configured language model answers the question on one passage.
    Like every model step here it only proposes: an answer that "quotes"
    words the book does not have is refused, and the reader sees the answer
    before it goes anywhere."""
    if not llm.status().get("available"):
        raise HTTPException(409, "Dil modeli ayarlı değil; yanıtı ChatGPT'den yapıştırabilirsin.")
    book = _nb_book(key)
    h = next((x for x in book.highlights if x.id == hid), None)
    if h is None:
        raise HTTPException(404, "Vurgu bulunamadı.")
    project, placements = _nb_project(book)
    p = placements.get(hid)
    passage = (p.paragraph if p else "") or h.text
    system = ("Bir okurun kitap okurken takıldığı yeri açıklıyorsun. Türkçe, kısa ve açık yaz. Yazarın ne "
              "demek istediğini ve geçen kavramları anlat; emin olmadığın yerde bunu söyle. Kitaptan alıntı "
              "yapacaksan yalnız verilen pasajdan, kelimesi kelimesine yap.")
    prompt = (f"Kitap: {project['book_title'] if project else book.title}"
              f"{' — ' + book.author if book.author else ''}\n"
              f"Pasaj:\n{passage}\n\nAltını çizdiğim kısım: {h.text}\nNotum: {h.note or ''}\n")
    try:
        answer = llm.complete(system, prompt, max_tokens=1200).strip()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Model yanıt veremedi: {exc}") from exc
    from app.notebook import fold_ascii
    book_text = fold_ascii(passage)
    for quoted in _QUOTED.findall(answer):
        if fold_ascii(quoted) not in book_text:
            raise HTTPException(422, "Modelin yanıtı pasajda olmayan bir alıntı içeriyor; kabul edilmedi.")
    return {"id": hid, "answer": answer}


def _nb_develop(key: str, hid: str):
    book = _nb_book(key)
    h = next((x for x in book.highlights if x.id == hid), None)
    if h is None or not obsidian.is_idea(h.note):
        raise HTTPException(404, "Bu vurgunun altında bir fikir (\"!\" ile başlayan not) yok.")
    project, _ = _nb_project(book)
    vault, settings = _nb_vault()
    folder = obsidian.book_folder(vault, settings)
    note = obsidian.find_book_note(folder, book.title) or (
        obsidian.find_book_note(folder, project["book_title"]) if project else None)
    book_note = os.path.basename(note)[:-3] if note else (project["book_title"] if project else book.title)
    has_block = bool(note) and f"^{hid}" in open(note, encoding="utf-8").read()
    return obsidian.develop_plan(book, h, book_note, vault, settings, note_has_block=has_block)


@app.post("/api/notebook/book/{key}/develop/{hid}")
def notebook_develop_preview(key: str, hid: str):
    """The note an idea would become in "3 - Gelişen Notlar", to see and edit first."""
    plan = _nb_develop(key, hid)
    return {"path": plan.path, "name": os.path.basename(plan.path)[:-3], "text": plan.text}


@app.post("/api/notebook/book/{key}/develop/{hid}/write")
def notebook_develop_write(key: str, hid: str, body: dict):
    """Write the idea's note as the reader left it in the preview; never over an existing file."""
    text = ((body or {}).get("text") or "").strip()
    if not text:
        raise HTTPException(400, "Not boş.")
    plan = _nb_develop(key, hid)
    if os.path.exists(plan.path):
        raise HTTPException(409, "Bu adla bir not zaten var; önizlemeyi yenileyin.")
    os.makedirs(os.path.dirname(plan.path), exist_ok=True)
    tmp = plan.path + ".matbaa-part"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text + "\n")
    os.replace(tmp, plan.path)
    return {"written": plan.path, "name": os.path.basename(plan.path)[:-3]}


@app.get("/api/obsidian/settings")
def obsidian_settings():
    s = obsidian.load_settings()
    return {**s, "vault_ok": bool(s.get("vault") and os.path.isdir(s["vault"]))}


@app.post("/api/obsidian/settings")
def obsidian_settings_save(body: dict):
    vault = (body or {}).get("vault")
    if vault and not os.path.isdir(vault):
        raise HTTPException(400, "Bu klasör bulunamadı.")
    s = obsidian.save_settings({**obsidian.load_settings(), **(body or {})})
    return {**s, "vault_ok": bool(s.get("vault") and os.path.isdir(s["vault"]))}


@app.get("/api/projects")
def projects():
    """Books converted before, kept on disk, most recent first; each with
    what the reader marked in it on the Kindle (highlights, words looked up)."""
    from app import vocab
    out = list_projects()
    marked: dict = {}
    for book in nb.current_books():
        project = nb.best_project(book, out)
        if project:
            marked.setdefault(project["session_id"], {"highlights": 0, "words": 0})["highlights"] += sum(
                1 for h in book.highlights if h.text)
    for lookups in vocab.by_book(vocab.load()).values():
        scored = sorted(((nb.same_book(lookups[0].book, p.get("book_title") or ""), p) for p in out),
                        key=lambda t: -t[0])
        if scored and scored[0][0] >= 0.8:
            marked.setdefault(scored[0][1]["session_id"], {"highlights": 0, "words": 0})["words"] += len(lookups)
    for p in out:
        p.update(marked.get(p["session_id"], {"highlights": 0, "words": 0}))
    return out


_THUMBS: dict = {}


@app.get("/api/projects/{session_id}/cover.jpg")
def project_cover(session_id: str):
    """The book's cover, small, for the shelf on the start screen."""
    from io import BytesIO

    from fastapi.responses import Response
    from PIL import Image
    session = get_session(session_id)
    if not session or not session.cover_image_base64:
        raise HTTPException(404, "Kapak yok")
    key = (session_id, len(session.cover_image_base64), session.cover_image_base64[-64:])
    data = _THUMBS.get(key)
    if data is None:
        try:
            with Image.open(BytesIO(base64.b64decode(session.cover_image_base64))) as img:
                img = img.convert("RGB")
                img.thumbnail((240, 360))
                buf = BytesIO()
                img.save(buf, "JPEG", quality=82)
                data = buf.getvalue()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(404, "Kapak okunamadı") from exc
        _THUMBS[key] = data
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-cache"})


@app.get("/api/llm/status")
def llm_status():
    """Whether the user has configured a language model, and which."""
    return llm.status()


@app.get("/api/llm/settings")
def llm_settings():
    """The model settings as the page may show them (never the key), and
    the models of a local server if one is running."""
    return {**llm.settings_view(), "local": llm.local_models()}


@app.put("/api/llm/settings")
def llm_settings_save(body: dict):
    """The reader's own model settings (the key typed by the reader), or
    {"clear": true} to forget them."""
    body = body or {}
    if body.get("clear"):
        return llm.clear_settings()
    provider = (body.get("provider") or "").strip().lower()
    if provider not in ("openai", "anthropic"):
        raise HTTPException(400, "Sağlayıcı openai (ya da OpenAI uyumlu/yerel) veya anthropic olmalı.")
    if not (body.get("model") or "").strip():
        raise HTTPException(400, "Model adı gerekli.")
    return llm.save_settings(provider, body.get("model", ""), body.get("api_key"), body.get("base_url", ""))


def _session_chapter(session_id: str, chapter_id: str):
    session = get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    chapter = next((c for c in session.chapters if c.id == chapter_id), None)
    if chapter is None:
        raise HTTPException(404, "Chapter not found")
    return session, chapter


@app.post("/api/session/{session_id}/chapter/{chapter_id}/llm/propose")
def llm_propose(session_id: str, chapter_id: str):
    """Ask the configured model what in this chapter is a misreading or a
    paragraph cut at a page. Sends this one chapter's text, on the user's
    request; returns proposals only, checked, and changes nothing."""
    session, chapter = _session_chapter(session_id, chapter_id)
    pieces = llm.split_html(chapter.html)
    try:
        proposals = llm.propose(pieces, session.language or "tr")
    except llm.LLMUnavailable as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Dil modeline ulaşılamadı: {exc}") from exc
    texts = llm.plain_paragraphs(pieces)
    return {
        "proposals": proposals,
        "merges": [{"index": i, "before": texts[i - 1][-80:], "after": texts[i][:80]} for i in proposals["merge"]],
    }


@app.post("/api/session/{session_id}/chapter/{chapter_id}/llm/apply", response_model=ConversionSession)
def llm_apply(session_id: str, chapter_id: str, body: LlmProposals):
    """Apply proposals the user accepted, checked again against the text."""
    session, chapter = _session_chapter(session_id, chapter_id)
    pieces = llm.split_html(chapter.html)
    checked = llm.validate(body.model_dump(), pieces)
    chapter.html = "".join(llm.apply(pieces, checked))
    save_session(session)
    return session


@app.get("/api/session/{session_id}/report")
def get_report(session_id: str):
    session = get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return session.report or {}


@app.get("/api/session/{session_id}/report/bundle")
def get_report_bundle(session_id: str):
    """The open issues and the passages concerned, as a JSON file the user
    can hand to whichever language model they use."""
    session = get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    bundle = llm_bundle(session.report or {}, session.chapters, session.book_title)
    import json
    return Response(
        content=json.dumps(bundle, ensure_ascii=False, indent=1),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="matbaa-sorunlar.json"'},
    )


@app.get("/api/session/{session_id}", response_model=ConversionSession)
def get_session_endpoint(session_id: str):
    session = get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return session


@app.put("/api/session/{session_id}/meta", response_model=ConversionSession)
def update_meta(session_id: str, update: MetaUpdate):
    session = get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if update.book_title is not None:
        session.book_title = update.book_title
    if update.author is not None:
        session.author = update.author
    if session.cover_kind == "matbaa" and (update.book_title is not None or update.author is not None):
        # a cover set in type follows the title and author it was set from
        session.cover_image_base64 = book_cover.typographic_base64(session.book_title, session.author)
    if update.language is not None:
        session.language = update.language.strip() or session.language
    if update.css is not None:
        session.css = update.css
    if update.hyphenate is not None:
        session.hyphenate = update.hyphenate
    if update.theme is not None:
        if update.theme not in THEMES:
            raise HTTPException(400, f"Bilinmeyen görünüm: {update.theme}")
        session.css = apply_theme(session.css, update.theme)
    if update.font is not None:
        if update.font not in book_fonts.FAMILIES and update.font != book_fonts.NO_FONT:
            raise HTTPException(400, f"Bilinmeyen yazı tipi: {update.font}")
        session.font = update.font
    if update.imprint is not None:
        imprint = dict(session.imprint or {})
        for key, value in update.imprint.items():
            if key not in book_imprint.Imprint.__dataclass_fields__ or key == "pages":
                continue
            if key == "isbn" and value:
                value = book_imprint.to_isbn13(str(value))
                if not value:
                    raise HTTPException(400, "Bu ISBN geçerli değil (son hane tutmuyor).")
            if key == "edition" and value not in (None, ""):
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    raise HTTPException(400, "Baskı bir sayı olmalı.") from None
            imprint[key] = value if value not in ("", None) else None
        session.imprint = imprint
    if update.imprint_page is not None:
        session.imprint_page = update.imprint_page
    if update.auto_index is not None:
        session.auto_index = update.auto_index
    if update.genre is not None:
        if update.genre not in book_genre.LABELS:
            raise HTTPException(400, f"Bilinmeyen tür: {update.genre}")
        session.genre, session.genre_source, session.genre_reason = update.genre, "reader", None
    if update.index_removed is not None:
        session.index_removed = [t for t in update.index_removed if t and t.strip()]
    save_session(session)
    return session


INDEX_MIN_ENTRIES = 15      # fewer, and an index made for the book is not worth its pages by default


def _book_index(session):
    """(entries, paged, on) of the index made for a book without a printed
    one; ([], False, False) for a book that has its own."""
    from app import auto_index
    # its rules are Turkish spelling's (the apostrophe before a name's suffix)
    if auto_index.has_printed_index(session.chapters) or not (session.language or "").lower().startswith("tr"):
        return [], False, False
    settings = obsidian.load_settings()
    vault = settings.get("vault")
    concepts = auto_index.concept_index(vault, settings) if vault and os.path.isdir(vault) else None
    dictionary = _word_dictionary()
    lemma = dictionary.lemmatizer().lemma if dictionary is not None else None
    entries = auto_index.build(session, concepts, lemma, session.index_removed)
    paged = any(e.pages() for e in entries)
    on = session.auto_index if session.auto_index is not None else len(entries) >= INDEX_MIN_ENTRIES
    return entries, paged, on


@app.get("/api/session/{session_id}/index")
def book_index(session_id: str):
    """The index Matbaa would make for this book: its entries, whether it is
    on, and the terms the reader took out."""
    from app import auto_index
    session = get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if auto_index.has_printed_index(session.chapters):
        return {"available": False, "printed": True, "on": False, "paged": False, "entries": [],
                "removed": session.index_removed}
    if not (session.language or "").lower().startswith("tr"):
        return {"available": False, "printed": False, "turkish_only": True, "on": False, "paged": False,
                "entries": [], "removed": session.index_removed}
    entries, paged, on = _book_index(session)
    return {"available": True, "printed": False, "on": on, "paged": paged, "removed": session.index_removed,
            "entries": [{"term": e.term, "kind": e.kind, "count": e.count, "pages": e.pages(),
                         "places": len({(p.chapter_id, p.block) for p in e.places})} for e in entries]}


@app.post("/api/session/{session_id}/imprint/lookup")
def imprint_lookup(session_id: str):
    """The imprint completed online by the book's ISBN, on the reader's
    request: only the ISBN is sent, only empty fields are filled, and a
    cover found is offered beside the PDF's ("web"), not put in its place."""
    session = get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    isbn = (session.imprint or {}).get("isbn")
    if not isbn:
        raise HTTPException(409, "Kitapta ISBN bulunamadı; önce künyeye ISBN'i yazın.")
    try:
        found = book_lookup.look_up(isbn)
    except book_lookup.LookupFailed as exc:
        raise HTTPException(502, f"İnternetten bakılamadı: {exc}") from exc
    if not found:
        return {"session": session, "found": None, "filled": []}
    session.imprint, filled = book_lookup.merge(session.imprint, found, session.language)
    if found.get("cover"):
        session.web_cover_base64 = found["cover"]
    save_session(session)
    return {"session": session, "filled": filled,
            "found": {k: found.get(k) for k in ("source", "title", "subtitle", "authors", "publisher", "year", "pages")}
            | {"cover": bool(found.get("cover"))}}


@app.post("/api/session/{session_id}/cover", response_model=ConversionSession)
def choose_cover(session_id: str, body: CoverChoice):
    """The PDF's own cover, or one set in type from the title and author
    (app/cover.py). The PDF's is kept while the other is in use."""
    session = get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if body.kind not in ("pdf", "matbaa", "web"):
        raise HTTPException(400, f"Bilinmeyen kapak: {body.kind}")
    if body.kind == "web" and not session.web_cover_base64:
        raise HTTPException(409, "İnternetten bir kapak bulunmadı; önce künyeyi internetten tamamlayın.")
    if session.cover_kind == "pdf" and body.kind != "pdf":
        session.pdf_cover_base64 = session.cover_image_base64
    if body.kind == "matbaa":
        session.cover_image_base64 = book_cover.typographic_base64(session.book_title, session.author)
    elif body.kind == "web":
        session.cover_image_base64 = session.web_cover_base64
    elif session.cover_kind != "pdf":
        session.cover_image_base64 = session.pdf_cover_base64
        session.pdf_cover_base64 = None
    session.cover_kind = body.kind
    save_session(session)
    return session


@app.get("/api/start/quote")
def start_quote():
    """The start screen's line for a reader with no Kindle passage yet: a
    well-known line from their latest book (or its author) on Vikisöz, looked
    up once per book and only in the reader's app; Trotsky's otherwise."""
    projects = list_projects()
    if not projects:
        return {"quote": quote_lookup.FALLBACK, "book": None}
    latest = projects[0]
    book = {"session_id": latest["session_id"], "title": latest["book_title"], "author": latest["author"]}
    session = get_session(latest["session_id"])
    if session is None:
        return {"quote": quote_lookup.FALLBACK, "book": book}
    if session.web_quote is None and os.environ.get("MATBAA_ONLINE"):
        found = quote_lookup.look_up(session.book_title, session.author)
        session.web_quote = found or {"none": True}
        save_session(session)
    quote = session.web_quote if session.web_quote and not session.web_quote.get("none") else quote_lookup.FALLBACK
    return {"quote": quote, "book": book}


@app.get("/api/counter")
def counter_state():
    """Whether this app adds its books to the site's counter (app/counter.py),
    and whether the reader has been told."""
    return counter.state()


@app.get("/api/counter/summary")
def counter_summary():
    """How many books the site's counter has, by genre (app/counter.py)."""
    return counter.summary()


@app.post("/api/counter")
def counter_settings(body: dict):
    body = body or {}
    return counter.settings(enabled=body.get("enabled"), notice_seen=body.get("notice_seen"))


@app.get("/api/genres")
def list_genres():
    """The genres a book can be given: [{id, label}] (app/genre.py)."""
    return [{"id": key, "label": label} for key, label in book_genre.GENRES]


@app.get("/api/themes")
def list_themes():
    """How a book can look: [{id, label, about}] (app/builders/themes.py)."""
    return theme_list()


@app.get("/api/fonts")
def list_fonts():
    """The typefaces a book can carry, each with the CSS the preview needs
    to show it (its faces served from /api/fonts/{family}/{file})."""
    out = []
    for item in book_fonts.font_list():
        if item["id"] in book_fonts.FAMILIES:
            item = {**item, "faces_css": book_fonts.font_css(item["id"], folder=f"/api/fonts/{item['id']}"),
                    "family_rule": book_fonts.with_family("", item["id"]).strip()}
        out.append(item)
    return out


@app.get("/api/fonts/{family}/{name}")
def font_file(family: str, name: str):
    """A face as the preview shows it. The preview is a sandboxed frame, so
    the face is served to any origin."""
    files = {f for f, _, _ in book_fonts.FAMILIES.get(family, ("", "", []))[2]}
    if name not in files:
        raise HTTPException(404, "Font not found")
    path = os.path.join(book_fonts.FONT_DIR, book_fonts.FAMILIES[family][1], name)
    return FileResponse(path, media_type="font/ttf", headers={"Access-Control-Allow-Origin": "*",
                                                             "Cache-Control": "max-age=86400"})


@app.put("/api/session/{session_id}/chapter/{chapter_id}", response_model=ConversionSession)
def update_chapter(session_id: str, chapter_id: str, update: ChapterUpdate):
    session = get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    for ch in session.chapters:
        if ch.id == chapter_id:
            ch.html = update.html
            if update.footnotes is not None:
                ch.footnotes = update.footnotes
            if update.title is not None:
                ch.title = update.title
            if update.eyebrow is not None:
                ch.eyebrow = update.eyebrow
            if update.byline is not None:
                ch.byline = update.byline or None
            save_session(session)
            return session
    raise HTTPException(404, "Chapter not found")


@app.post("/api/session/{session_id}/chapter/{chapter_id}/split", response_model=ConversionSession)
def split_chapter(session_id: str, chapter_id: str, body: ChapterSplitRequest):
    """Manual override: split one chapter into two at an editor-chosen point."""
    session = get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    idx = next((i for i, c in enumerate(session.chapters) if c.id == chapter_id), None)
    if idx is None:
        raise HTTPException(404, "Chapter not found")

    original = session.chapters[idx]
    original.html = body.before_html

    # The figures and notes go with the half that refers to them. The second
    # half used to start with none at all, so its pictures pointed at files
    # the EPUB no longer packed and its note references at notes that were
    # left behind in the first half.
    def _referenced(html: str, needle: str) -> bool:
        return needle in (html or "")

    after_images = [img for img in original.images if _referenced(body.after_html, f"images/{img.id}.png")]
    before_images = [
        img for img in original.images
        if _referenced(body.before_html, f"images/{img.id}.png") or img not in after_images
    ]
    after_notes = [fn for fn in original.footnotes if _referenced(body.after_html, f'href="#{fn.id}"')]
    before_notes = [fn for fn in original.footnotes if fn not in after_notes]
    original.images = before_images
    original.footnotes = before_notes

    new_id = f"{original.id}_split_{uuid.uuid4().hex[:6]}"
    new_chapter = ChapterOut(
        id=new_id,
        index=original.index,
        title=body.new_title or f"{original.title} (devamı)",
        kind=original.kind,
        html=body.after_html,
        footnotes=after_notes,
        images=after_images,
        is_split_continuation=False,
        # a section split off by hand stays under the same printed heading
        toc_path=list(original.toc_path),
    )
    session.chapters.insert(idx + 1, new_chapter)
    for i, c in enumerate(session.chapters):
        c.index = i

    save_session(session)
    return session


@app.put("/api/session/{session_id}/reorder", response_model=ConversionSession)
def reorder_chapters(session_id: str, body: ReorderRequest):
    """Persist a manual drag-and-drop reordering of the chapter list. The
    exported EPUB's spine/nav are built by walking session.chapters in
    order, so reordering here is all that's needed for the export to
    reflect the new order too — no separate epub_builder change required."""
    session = get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    by_id = {c.id: c for c in session.chapters}
    if set(body.chapter_ids) != set(by_id.keys()):
        raise HTTPException(400, "chapter_ids must be a reordering of exactly the session's current chapters")

    reordered = [by_id[cid] for cid in body.chapter_ids]
    for i, c in enumerate(reordered):
        c.index = i
    session.chapters = reordered

    save_session(session)
    return session


def _build_session_epub(session, with_notes: bool = False) -> str:
    """The book as it would be exported; "with_notes" carries the reader's
    Kindle highlights and notes back into it (backend/app/reader_notes.py)."""
    chapters, css = session.chapters, session.css
    out_path = os.path.join(TEMP_DIR, f"{session.session_id}.epub")
    if with_notes:
        book = reader_notes.book_for_session(session)
        if book is not None:
            chapters, _ = reader_notes.annotate(session, book)
            css = (css or "") + reader_notes.CSS
            out_path = os.path.join(TEMP_DIR, f"{session.session_id}-notlarimla.epub")
    # an index for a book without one, at its end; the session's text stays as it is
    entries, paged, on = _book_index(session)
    if on and entries:
        from app import auto_index
        anchored = {} if paged else auto_index.anchor_ids(session, entries)
        chapters = [ch.model_copy(update={"html": anchored[ch.id]}) if ch.id in anchored else ch for ch in chapters]
        chapters = chapters + [ChapterOut(id="dizin", index=len(chapters), title="Dizin",
                                          html=auto_index.chapter_html(entries, paged))]
    build_epub(
        book_title=session.book_title,
        author=session.author,
        chapters=chapters,
        css=css,
        output_path=out_path,
        cover_image_base64=session.cover_image_base64,
        language=session.language,
        hyphenate=session.hyphenate,
        font=session.font if session.font in book_fonts.FAMILIES else None,
        imprint=session.imprint,
        imprint_page=session.imprint_page,
        subject=book_genre.label(session.genre) if session.genre and session.genre != "diger" else None,
    )
    return out_path


@app.get("/api/session/{session_id}/validate")
def validate_session_epub(session_id: str):
    """Build the EPUB as it would be exported and check it: EPUB 3 validity
    (and EPUBCheck itself where Java is installed) and Kindle's own limits."""
    session = get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    findings = check_epub(_build_session_epub(session))
    return {**validation_summary(findings), "findings": [f.to_dict() for f in findings]}


def _epub_filename(session) -> str:
    return ("".join(c for c in session.book_title if c.isalnum() or c in " -_").strip() or "book") + ".epub"


@app.get("/api/kindle/status")
def kindle_status():
    return kindle_send.status()


@app.post("/api/kindle/settings")
def kindle_settings(body: dict):
    allowed = {"kindle_email", "from_email", "smtp_host", "smtp_port", "smtp_user", "smtp_password"}
    return kindle_send.save({k: v for k, v in (body or {}).items() if k in allowed})


@app.get("/api/session/{session_id}/kindle/preview")
def kindle_preview(session_id: str):
    """What a send would do, for the confirmation screen: to whom, which
    file, how large, and whether the EPUB passes its check."""
    session = get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    path = _build_session_epub(session)
    findings = check_epub(path)
    st = kindle_send.status()
    return {
        **st,
        "filename": _epub_filename(session),
        "title": session.book_title,
        "size_mb": round(os.path.getsize(path) / 1e6, 1),
        "valid": not any(f.severity == "error" for f in findings),
        "errors": [f.message for f in findings if f.severity == "error"][:5],
    }


@app.post("/api/session/{session_id}/kindle/send")
def kindle_send_book(session_id: str, body: dict):
    """Send the book to the configured Kindle address — only with an
    explicit confirmation, and only an EPUB that passes its check."""
    if not (body or {}).get("confirm"):
        raise HTTPException(400, "Gönderim onaylanmadı.")
    session = get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    path = _build_session_epub(session)
    errors = [f.message for f in check_epub(path) if f.severity == "error"]
    if errors:
        raise HTTPException(409, "EPUB doğrulamadan geçmedi: " + "; ".join(errors[:3]))
    try:
        sent = kindle_send.send(path, session.book_title, _epub_filename(session))
        if counter.count(session):
            save_session(session)
        return sent
    except kindle_send.KindleNotConfigured as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(413, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"E-posta gönderilemedi: {exc}") from exc


@app.get("/api/session/{session_id}/reader-notes")
def session_reader_notes(session_id: str):
    """How many of the reader's Kindle highlights and notes this book has —
    whether "notlarımla" export is worth offering."""
    session = get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return reader_notes.count_for_session(session)


@app.post("/api/session/{session_id}/export")
def export_epub(session_id: str, notes: bool = False):
    session = get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    out_path = _build_session_epub(session, with_notes=notes)
    if counter.count(session):
        save_session(session)
    safe_name = "".join(c for c in session.book_title if c.isalnum() or c in " -_").strip() or "book"
    return FileResponse(
        out_path,
        media_type="application/epub+zip",
        filename=f"{safe_name}.epub",
    )


@app.delete("/api/session/{session_id}")
def close_session(session_id: str):
    delete_session(session_id)
    return {"status": "deleted"}


# --- Serve the built frontend (single-process "just run one exe" mode) ----
# Mounted LAST and deliberately: FastAPI/Starlette match routes in
# registration order, so every /api/* route above always takes precedence
# over this catch-all. In normal dev (`npm run dev` + `uvicorn --reload`)
# this directory won't exist, so nothing is mounted and the two dev servers
# keep working exactly as before.
_frontend_dist = resource_path("frontend_dist")
if os.path.isdir(_frontend_dist):
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=_frontend_dist, html=True), name="frontend")
