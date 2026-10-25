"""Measure one PDF of the personal library through the real pipeline.

Run by tools/run_library.py in its own process (one book cannot take the
rest down, and a timeout can kill it). Prints a single JSON line.

    python tools/qa/library_one.py <book.pdf>

The numbers are chosen so each defect class seen in the library survey has
a measurement that moves when it is fixed — see FLAGS in run_library.py.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import traceback
import unicodedata
from collections import Counter
from difflib import SequenceMatcher

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "backend"))

import pymupdf as fitz  # noqa: E402

from app.parsers.pdf_parser import convert_pdf_to_chapters, get_pdf_page_previews  # noqa: E402
from app.utils.text_quality import garbage_share  # noqa: E402
from app.parsers.outline_structure import reading_order as outline_reading_order  # noqa: E402
from app import diagnosis  # noqa: E402
from app.builders.css_template import book_css  # noqa: E402
from app.builders.epub_builder import build_epub  # noqa: E402
from app.models import ChapterImage, ChapterOut, Footnote  # noqa: E402
from app.validate import check_epub  # noqa: E402
from app import ocr_layer  # noqa: E402

OCR_CACHE = os.path.join(REPO_ROOT, ".matbaa-work", "library", "ocr")

IMPRINT_TITLE = re.compile(
    r"ilk defa|yayınlanmıştır|ISBN|Sertifika|Alıntılarda|kaynak gösterilmesi|Telegram|@\w|www\.|https?://",
    re.IGNORECASE,
)
LEADER_TITLE = re.compile(r"(\.\s*){4,}|…{2,}")
TAG = re.compile(r"<[^>]+>")
LIST_ITEM = re.compile(r"^(?:[a-zçğıöşü]|[ivx]{1,4})[)\]]\s")
EM_RUN = re.compile(r"<em>(.*?)</em>", re.S)


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    return re.sub(r"[^a-z0-9]+", "", "".join(c for c in text if not unicodedata.combining(c)).replace("ı", "i"))


def outline_coverage(outline, titles, page_count: int, book_title) -> tuple:
    """Share of the chapters the PDF's bookmarks describe that came out as
    chapters, and how many that is. Bookmarks that are not a contents (one
    per page, placeholders) describe none — the same judgement the app
    makes (app.parsers.outline_structure)."""
    expected = []
    for item in outline_reading_order(outline, page_count, book_title):
        key = _fold(item.title)
        if item.kind == "chapter" and len(key) >= 4 and key not in expected:
            expected.append(key)
    if not expected:
        return None, 0
    folded = [_fold(t) for t in titles]
    hit = 0
    for key in expected:
        if any(key == t or key in t or (len(t) >= 4 and t in key)
               or SequenceMatcher(None, key, t).ratio() >= 0.8 for t in folded):
            hit += 1
    return round(hit / len(expected), 3), len(expected)


def readable_copy(pdf: str, rec: dict) -> str:
    """The PDF the app would convert: the upload itself, or — when its pages
    need reading — the searchable copy OCR makes of it. Copies are cached by
    file size and date, so only the first run pays for OCR."""
    needs = ocr_layer.pages_needing_ocr(pdf)
    rec["ocr_pages"] = len(needs.pages)
    rec["ocr_reason"] = needs.reason or ("scan" if needs.pages else None)
    if not needs.pages or not ocr_layer.ocr_available():
        return pdf
    stat = os.stat(pdf)
    name = os.path.splitext(os.path.basename(pdf))[0][:60]
    cached = os.path.join(OCR_CACHE, f"{name}-{stat.st_size}-{int(stat.st_mtime)}-v{ocr_layer.OCR_LAYER_VERSION}.pdf")
    if not os.path.exists(cached):
        os.makedirs(OCR_CACHE, exist_ok=True)
        t0 = time.time()
        ocr_layer.build_searchable_copy(pdf, cached, pages=needs.pages)
        rec["ocr_seconds"] = round(time.time() - t0, 1)
    rec["ocr_applied"] = True
    return cached


def epub_check(result) -> dict:
    """Build the EPUB the app would export (as main.py does) and check it."""
    import tempfile
    chapters = [
        ChapterOut(
            id=ch.id, index=ch.index, title=ch.title, kind=ch.kind, eyebrow=ch.eyebrow,
            html="".join(ch.paragraphs),
            footnotes=[Footnote(id=f.id, marker=f.marker, text=f.text) for f in ch.footnotes],
            is_split_continuation=ch.is_split_continuation, image_base64=ch.image_base64,
            images=[ChapterImage(**img) for img in ch.images], byline=ch.byline,
            toc_path=list(ch.toc_path), opener=ch.opener,
        )
        for ch in result.chapters
    ]
    path = os.path.join(tempfile.mkdtemp(), "book.epub")
    try:
        build_epub(book_title=result.detected_title, author=result.detected_author, chapters=chapters,
                   css=book_css(result.paragraph_style), output_path=path,
                   cover_image_base64=result.cover_image_base64, language=result.detected_language)
    except Exception as exc:  # noqa: BLE001
        return {"epub_errors": 1, "epub_error_codes": {"build-failed": 1}, "epub_note": str(exc)[:200]}
    findings = check_epub(path)
    errors = [f for f in findings if f.severity == "error"]
    return {"epub_errors": len(errors), "epub_error_codes": dict(Counter(f.code for f in errors)),
            "epub_mb": round(os.path.getsize(path) / 1e6, 1)}


def main(pdf: str, use_ocr: bool = True) -> dict:
    rec = {"file": os.path.basename(pdf), "folder": os.path.basename(os.path.dirname(pdf)),
           "mb": round(os.path.getsize(pdf) / 1e6, 1)}
    doc = fitz.open(pdf)
    rec["pages"] = doc.page_count
    meta = doc.metadata or {}
    rec["producer"] = (meta.get("producer") or "")[:40]
    outline = doc.get_toc() or []
    rec["outline"] = len(outline)
    texts = [p.get_text("text") for p in doc]
    rec["source_words"] = sum(len(t.split()) for t in texts)
    rec["textless_pages"] = sum(1 for t in texts if len(t.strip()) < 20)
    rec["source_garbage"] = garbage_share("\n".join(texts[:80]))
    doc.close()

    source = pdf
    pdf = readable_copy(pdf, rec) if use_ocr else pdf
    if pdf == source and rec["textless_pages"] > rec["pages"] * 0.8:
        rec["status"] = "scanned"
        return rec

    t0 = time.time()
    previews = get_pdf_page_previews(pdf)
    modes = {m: {p.index for p in previews if p.suggested_mode == m} for m in ("image", "toc", "exclude")}
    result = convert_pdf_to_chapters(
        pdf, excluded_pages=modes["exclude"], image_pages=modes["image"], toc_pages=modes["toc"]
    )
    rec["seconds"] = round(time.time() - t0, 1)

    # the same numbers the book's own report (app.diagnosis) is built on
    rec.update(diagnosis.measure(result))
    # Pieces of a long chapter split for the reader carry its title; they
    # are not chapters, and counting them made every long book look like it
    # repeated its titles.
    real = [c for c in result.chapters if c.kind == "chapter" and not c.is_split_continuation]
    labels = [c.title for c in real] + [c.eyebrow for c in real if c.eyebrow]
    rec["outline_coverage"], rec["outline_keys"] = outline_coverage(
        outline, labels, rec["pages"], (meta.get("title") or None))
    rec["recovery"] = round(rec["words"] / max(1, rec["source_words"]), 3)
    rec["book_title"], rec["book_author"] = result.detected_title, result.detected_author
    rec.update(epub_check(result))
    rec["status"] = "ok"
    return rec


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    path = sys.argv[1]
    try:
        out = main(path, use_ocr="--no-ocr" not in sys.argv[2:])
    except Exception as exc:  # noqa: BLE001 — reported as a result, never hidden
        out = {"file": os.path.basename(path), "status": "error",
               "error": f"{type(exc).__name__}: {exc}"[:300], "trace": traceback.format_exc()[-1200:]}
    print(json.dumps(out, ensure_ascii=False))
