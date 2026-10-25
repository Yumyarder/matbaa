"""Give a scanned PDF a real text layer, once, before anything reads it.

A scanner's PDF is a stack of photographs: PyMuPDF reports zero characters
on every page, so page review suggests "Görsel" for the whole book and
marking a page "Metin" produces an empty chapter — the book comes out as
pictures with no words in it. Nothing downstream can fix that, because
there is no text to find.

So the fix is upstream: OCR the pages that have no text of their own and
write a searchable copy of the upload, page for page, at the same page
size. Everything after this point — page suggestions, body size, headings,
footnotes, masks, figure regions, the editor, the EPUB — then works on an
ordinary text PDF and needs no special case at all.

Measured on a 15-page scanned journal article: ~2.5 s per page, the page
rectangle preserved exactly (418x628), 4.5k words recovered where there
had been none.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

import pymupdf as fitz

from app.ocr_env import find_tessdata, installed_languages
from app.utils.text_quality import garbage_share

# Tesseract reads a page by shape, so resolution matters more than anything
# else here: 3x a 72-dpi page is ~216 dpi, the point where Turkish
# diacritics stop being guesses. Lower is faster and measurably worse.
OCR_RENDER_ZOOM = 3.0
OCR_DPI = 216
# Turkish first — these are Turkish books — with English alongside it for
# the quotations and bibliographies academic books are full of.
OCR_LANGUAGE = "tur+eng"
# Below this a page's own text layer is not a text layer: a stray caption
# the scanner's software recognised, a stamped page number.
MIN_PAGE_TEXT_CHARS = 20


class OcrUnavailable(Exception):
    """OCR cannot run here. The message is written for the person to read."""


def ocr_language(preferred: str = OCR_LANGUAGE) -> Optional[str]:
    """The best of the preferred languages that is actually installed."""
    available = installed_languages()
    if not available:
        return None
    wanted = [part for part in preferred.split("+") if part in available]
    if wanted:
        return "+".join(wanted)
    return "eng" if "eng" in available else sorted(available)[0]


def ocr_available() -> bool:
    return bool(find_tessdata()) and ocr_language() is not None


def unavailable_message() -> str:
    return (
        "Bu PDF taranmış — sayfalarda okunabilir yazı katmanı yok. Metni çıkarmak için "
        "Tesseract OCR kurulmalı (Windows: https://github.com/UB-Mannheim/tesseract/wiki) "
        "ve Türkçe dil paketi seçilmeli. Kurulumdan sonra PDF'i yeniden yükleyin."
    )


# A page's text layer is noise when this much of it is not words (see
# utils.text_quality): the library's broken books score over 0.3 on every
# page; a sound book has at most a stray page of decoration above 0.17.
UNREADABLE_PAGE_GARBAGE = 0.45
# A whole book is read again when half its pages are past this.
UNREADABLE_BOOK_GARBAGE = 0.25
UNREADABLE_BOOK_SHARE = 0.5
# A scanned book whose OCR layer found this few words per page did not read
# the page: measured 31 on a scan whose pages print ~300.
SPARSE_SCAN_WORDS_PER_PAGE = 100
SCAN_PAGE_IMAGE_RATIO = 0.8
# Share of a book's pages that must be text-less pictures before the book
# counts as a scan whose pages all need reading.
SCANNED_BOOK_SHARE = 0.5
# Bumped whenever what a searchable copy contains changes, so cached copies
# made by older code are not mistaken for current ones. 2: bookmarks and
# metadata are carried over.
OCR_LAYER_VERSION = 2
# Pages are read side by side in this many worker processes.
MAX_OCR_WORKERS = 6


@dataclass
class OcrNeeds:
    """Which pages OCR has to read, and why."""
    textless: List[int] = field(default_factory=list)
    unreadable: List[int] = field(default_factory=list)
    # "broken-text" when the book's own text layer is noise, "sparse-scan"
    # when a scanner's OCR layer read almost nothing; None otherwise.
    reason: Optional[str] = None

    @property
    def pages(self) -> List[int]:
        return sorted(set(self.textless) | set(self.unreadable))


def _image_cover(page) -> float:
    area = page.rect.width * page.rect.height or 1.0
    best = 0.0
    for info in page.get_image_info():
        x0, y0, x1, y1 = info["bbox"]
        best = max(best, max(0.0, x1 - x0) * max(0.0, y1 - y0) / area)
    return min(best, 1.0)


def pages_needing_ocr(pdf_path: str) -> OcrNeeds:
    """Pages whose words can only be had by reading the page image.

    Three cases, each from the library survey: pages with no text at all (a
    plain scan), a text layer that is noise (a broken font encoding), and a
    scanner's OCR layer that recognised almost nothing.
    """
    doc = fitz.open(pdf_path)
    try:
        texts = [page.get_text("text") for page in doc]
        has_image = [bool(page.get_images()) for page in doc]
        needs = OcrNeeds()
        textless = [
            i for i, t in enumerate(texts) if len(t.strip()) < MIN_PAGE_TEXT_CHARS and has_image[i]
        ]
        # A picture-only page in a book that otherwise has its text is a
        # cover, a plate or an illustration — reading it would turn
        # hand-lettering into text. Only a book that is mostly scan has its
        # text-less pages read.
        if len(textless) >= doc.page_count * SCANNED_BOOK_SHARE:
            needs.textless = textless
        with_text = [i for i, t in enumerate(texts) if len(t.strip()) >= MIN_PAGE_TEXT_CHARS]
        scores = {i: garbage_share(texts[i]) for i in with_text}
        broken = [i for i in with_text if scores[i] > UNREADABLE_BOOK_GARBAGE]
        if with_text and len(broken) / len(with_text) >= UNREADABLE_BOOK_SHARE:
            needs.unreadable = list(with_text)
            needs.reason = "broken-text"
            return needs
        needs.unreadable = [i for i in with_text if scores[i] > UNREADABLE_PAGE_GARBAGE]
        if needs.unreadable:
            needs.reason = "broken-text"

        if doc.page_count >= 10 and with_text:
            scanned = sum(1 for page in doc if _image_cover(page) >= SCAN_PAGE_IMAGE_RATIO)
            words = sorted(len(texts[i].split()) for i in with_text)
            if (scanned / doc.page_count >= 0.8
                    and words[len(words) // 2] < SPARSE_SCAN_WORDS_PER_PAGE):
                needs.unreadable = [i for i in range(doc.page_count) if has_image[i]]
                needs.reason = "sparse-scan"
        return needs
    finally:
        doc.close()


def pages_without_text(pdf_path: str) -> List[int]:
    """Every page OCR has to read (kept for callers that only need the list)."""
    return pages_needing_ocr(pdf_path).pages


def _ocr_in_workers(src_path: str, targets: List[int], lang: str, tessdata: str,
                    progress: Optional[Callable[[int, int], None]]) -> dict:
    """Read the target pages in parallel worker processes; returns
    {page: single-page searchable PDF bytes}."""
    workers = max(1, min(MAX_OCR_WORKERS, (os.cpu_count() or 2) - 1, len(targets)))
    shares = [targets[i::workers] for i in range(workers)]
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = {**os.environ, "PYTHONPATH": backend_dir, "OMP_THREAD_LIMIT": "1"}
    with tempfile.TemporaryDirectory(prefix="matbaa-ocr-") as out_dir:
        procs = [
            subprocess.Popen(
                [sys.executable, "-m", "app.ocr_worker", src_path, out_dir, lang, tessdata,
                 ",".join(str(p) for p in share)],
                cwd=backend_dir, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            for share in shares if share
        ]
        try:
            while True:
                done = sum(1 for name in os.listdir(out_dir) if name.endswith(".pdf"))
                if progress:
                    progress(done, len(targets))  # may raise to cancel
                if all(p.poll() is not None for p in procs):
                    break
                time.sleep(0.3)
        except BaseException:
            for p in procs:
                p.kill()
            for p in procs:
                p.wait()
            raise
        for p in procs:
            if p.returncode != 0:
                err = (p.stderr.read() or b"").decode("utf-8", "replace")[-500:]
                raise OcrUnavailable(f"Tesseract OCR çalıştırılamadı ({lang}). Orijinal hata: {err}")
        pages = {}
        for number in targets:
            with open(os.path.join(out_dir, f"{number}.pdf"), "rb") as f:
                pages[number] = f.read()
        return pages


def _ocr_in_process(src, targets: List[int], lang: str, tessdata: str,
                    progress: Optional[Callable[[int, int], None]]) -> dict:
    from app.ocr_worker import ocr_page_pdf

    pages = {}
    for done, number in enumerate(targets, start=1):
        try:
            pages[number] = ocr_page_pdf(src[number], lang, tessdata, OCR_RENDER_ZOOM, OCR_DPI)
        except Exception as exc:  # noqa: BLE001 — surfaced to the person
            raise OcrUnavailable(f"Tesseract OCR çalıştırılamadı ({lang}). Orijinal hata: {exc}") from exc
        if progress:
            progress(done, len(targets))
    return pages


def build_searchable_copy(
    src_path: str,
    dst_path: str,
    pages: Optional[List[int]] = None,
    language: Optional[str] = None,
    progress: Optional[Callable[[int, int], None]] = None,
) -> str:
    """Write a copy of `src_path` whose unreadable pages carry OCR'd text.

    The target pages are rendered and read again, so whatever text layer
    they had — none, or noise — is replaced by what is printed on them.
    Other pages are copied through untouched, so a born-digital book with a
    few scanned inserts keeps its real text where it has one. The copy is
    written to a temporary file and moved into place at the end, so a
    half-finished OCR run can never be picked up as a finished one.
    """
    lang = language or ocr_language()
    tessdata = find_tessdata()
    if not tessdata or not lang:
        raise OcrUnavailable(unavailable_message())

    src = fitz.open(src_path)
    out = fitz.open()
    try:
        targets = sorted(set(pages if pages is not None else pages_needing_ocr(src_path).pages))
        if progress:
            progress(0, len(targets))
        # A frozen .exe cannot start `python -m`, and a handful of pages is
        # not worth the start-up of several processes.
        if getattr(sys, "frozen", False) or len(targets) < 4:
            read = _ocr_in_process(src, targets, lang, tessdata, progress)
        else:
            read = _ocr_in_workers(src_path, targets, lang, tessdata, progress)
        for page in src:
            if page.number not in read:
                out.insert_pdf(src, from_page=page.number, to_page=page.number)
                continue
            one = fitz.open("pdf", read[page.number])
            try:
                out.insert_pdf(one)
            finally:
                one.close()

        # The copy is the same book: its bookmarks and metadata go with it.
        # Without them a scanned book lost the bookmark structure that is
        # often the only clean statement of its chapters.
        try:
            # by page number: the source's link targets do not exist in the copy
            out.set_toc(src.get_toc(simple=True))
        except Exception:  # noqa: BLE001 — a malformed outline is not worth failing OCR over
            pass
        out.set_metadata({k: v for k, v in (src.metadata or {}).items() if v and k != "format"})
        partial = dst_path + ".part"
        out.save(partial, garbage=3, deflate=True)
        os.replace(partial, dst_path)
        return dst_path
    finally:
        out.close()
        src.close()
