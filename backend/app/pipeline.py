"""One PDF to one EPUB, end to end, with the defaults a person accepts by
clicking through: read the pages that need OCR, take each page's suggested
mode, convert, build the EPUB, check it, and report on it.

Used by the batch converter (tools/batch_convert.py); the app's own flow
runs the same steps one screen at a time.
"""
from __future__ import annotations

import os
import time
from typing import Callable, Dict, Optional

import fitz

from app import ocr_layer
from app.book_names import fill as fill_from_filename
from app.builders.css_template import book_css
from app.builders.epub_builder import build_epub
from app.cover import clean_base64
from app.diagnosis import build_report
from app.fonts import DEFAULT_FONT
from app.imprint import read_pdf as read_imprint
from app.models import ChapterImage, ChapterOut, Footnote
from app.parsers.pdf_parser import _page_text_is_ocr, convert_pdf_to_chapters, get_pdf_page_previews
from app.validate import check_epub, summary


def chapters_out(result) -> list:
    """The parser's chapters as the app's session and builder take them."""
    return [
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


def readable_pdf(pdf: str, work_dir: str, log: Callable[[str], None] = print) -> str:
    """The PDF to convert: the file itself, or a searchable copy when some of
    its pages need OCR (cached in work_dir by size and date)."""
    needs = ocr_layer.pages_needing_ocr(pdf)
    if not needs.pages:
        return pdf
    if not ocr_layer.ocr_available():
        log(f"  {len(needs.pages)} sayfa OCR istiyor ama Tesseract kurulu değil; olduğu gibi dönüştürülüyor.")
        return pdf
    stat = os.stat(pdf)
    name = os.path.splitext(os.path.basename(pdf))[0][:60]
    cached = os.path.join(work_dir, f"{name}-{stat.st_size}-{int(stat.st_mtime)}-v{ocr_layer.OCR_LAYER_VERSION}.pdf")
    if not os.path.exists(cached):
        os.makedirs(work_dir, exist_ok=True)
        log(f"  {len(needs.pages)} sayfa OCR ile okunuyor…")
        ocr_layer.build_searchable_copy(pdf, cached, pages=needs.pages)
    return cached


def convert_file(pdf: str, out_epub: str, work_dir: str, use_ocr: bool = True,
                 log: Callable[[str], None] = print) -> Dict:
    t0 = time.time()
    source = readable_pdf(pdf, work_dir, log) if use_ocr else pdf
    previews = get_pdf_page_previews(source)
    modes = {m: {p.index for p in previews if p.suggested_mode == m} for m in ("image", "toc", "exclude")}
    result = convert_pdf_to_chapters(source, excluded_pages=modes["exclude"], image_pages=modes["image"],
                                     toc_pages=modes["toc"])
    os.makedirs(os.path.dirname(os.path.abspath(out_epub)), exist_ok=True)
    title, author = fill_from_filename(result.detected_title, result.detected_author, pdf,
                                       result.detected_language)
    imprint = read_imprint(source)
    build_epub(book_title=title, author=author, chapters=chapters_out(result),
               css=book_css(result.paragraph_style), output_path=out_epub,
               cover_image_base64=clean_base64(result.cover_image_base64), language=result.detected_language,
               font=DEFAULT_FONT, imprint=None if imprint.empty() else imprint.to_dict())
    with fitz.open(source) as doc:
        context = {"producer": (doc.metadata or {}).get("producer") or "",
                   "ocr_pages": sum(1 for page in doc if _page_text_is_ocr(page))}
    report = build_report(result, context).to_dict()
    findings = check_epub(out_epub)
    return {
        "pdf": pdf, "epub": out_epub, "title": title, "author": author,
        "chapters": sum(1 for c in result.chapters if c.kind == "chapter" and not c.is_split_continuation),
        "seconds": round(time.time() - t0, 1), "report": report,
        "validation": {**summary(findings), "findings": [f.to_dict() for f in findings if f.severity != "info"]},
    }
