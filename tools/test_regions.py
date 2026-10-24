"""Regression coverage for the PDF Editor's image/OCR region wiring.

    python tools/test_regions.py

Builds a small synthetic PDF with fitz — full control over exact text
positions and sizes, so the test doesn't depend on guessing what happens
to sit on a real corpus page — converts it with image_regions/ocr_regions
set, and asserts on both the resulting Chapter objects AND the built
EPUB's actual zip contents. Exit code is 1 if anything fails, so this is
usable as a pre-commit gate the same way tools/run_qa.py is.

This is deliberately a second, narrower harness rather than a new entry in
tools/qa: that one measures whole-book behavior against the three-book
corpus, this one pins down one specific mechanism (region suppression,
OCR substitution, caption binding, image embedding) against inputs built
to isolate it.
"""
from __future__ import annotations

import os
import re
import sys
import zipfile

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if os.path.join(REPO_ROOT, "backend") not in sys.path:
    sys.path.insert(0, os.path.join(REPO_ROOT, "backend"))

import fitz  # noqa: E402

from app.builders.css_template import MATBAA_CSS  # noqa: E402
from app.builders.epub_builder import build_epub  # noqa: E402
from app.models import ChapterImage, ChapterOut, Footnote  # noqa: E402
from app.parsers.pdf_parser import convert_pdf_to_chapters  # noqa: E402

OUT_DIR = os.path.join(REPO_ROOT, ".matbaa-work", "qa")
PDF_PATH = os.path.join(OUT_DIR, "regions_test.pdf")
EPUB_PATH = os.path.join(OUT_DIR, "regions_test.epub")

PAGE_W, PAGE_H = 400, 600
BODY_SIZE = 10
HEADING_SIZE = 16
CAPTION_SIZE = 8
CAPTION_TEXT = "Figure 1: an example caption"
# Simulates the PDF-level font corruption OCR exists to route around
# (PROJECT_CONTEXT bug #6) — garbage glyphs at heading size.
GARBLED_HEADING = "CH4PT3R TW0 !@#$"
PROSE_LINE = "This whole line is real running prose, not a picture at all."
SHORT_NEXT_LINE = "and it just keeps going here."


def _build_synthetic_pdf() -> tuple[list, list, list, list]:
    """Returns (IMG_BBOX, GARBLED_BBOX) — the real bboxes fitz recorded,
    not guessed coordinates. insert_text()'s y is the text BASELINE, not
    the glyph's top edge, so a guessed box easily misses the block
    _extract_page_blocks later computes for the same text; deriving it
    from what fitz actually wrote removes that whole class of flakiness.

    Plain ASCII throughout, and no line of filler prose starts with
    "Chapter"/"Part"/etc.: those are genuine heading keywords the real
    pipeline matches regardless of size (HEADING_KEYWORDS), so either
    choice would make this test measure a naming collision instead of the
    region-wiring behavior it exists to check. Turkish-text handling is
    already covered by the real three-book corpus (tools/run_qa.py).
    """
    doc = fitz.open()

    # Page 0: heading, several body paragraphs (enough for body-size
    # detection), a picture placeholder (a filled rect, no text under it),
    # a caption line right below it, then a closing paragraph.
    p0 = doc.new_page(width=PAGE_W, height=PAGE_H)
    y = 40
    p0.insert_text((40, y), "CHAPTER ONE", fontsize=HEADING_SIZE)
    y += 30
    for i in range(6):
        p0.insert_text((40, y), f"This is an ordinary body paragraph line {i}.", fontsize=BODY_SIZE)
        y += 16
    y += 20
    img_bbox = [40, y, 200, y + 100]
    p0.draw_rect(fitz.Rect(*img_bbox), color=(0, 0, 0), fill=(0.6, 0.6, 0.6))
    y += 100 + 6
    p0.insert_text((45, y + CAPTION_SIZE), CAPTION_TEXT, fontsize=CAPTION_SIZE)
    y += 20
    p0.insert_text((40, y + 20), "A second paragraph continues right after the figure.", fontsize=BODY_SIZE)

    # Page 1: a garbled "heading" plus body text, for the OCR-region
    # substitution path.
    p1 = doc.new_page(width=PAGE_W, height=PAGE_H)
    p1.insert_text((40, 40), GARBLED_HEADING, fontsize=HEADING_SIZE)
    y = 70
    for i in range(6):
        p1.insert_text((40, y), f"Some ordinary filler prose for the second page, line {i}.", fontsize=BODY_SIZE)
        y += 16

    # Page 2: an image region with nothing nearby that qualifies as a
    # caption (the next text starts well below it, and reads as a full
    # paragraph, not a short caption-shaped line) — the region must still
    # convert, just without a bound caption.
    p2 = doc.new_page(width=PAGE_W, height=PAGE_H)
    p2.insert_text((40, 40), "CHAPTER THREE", fontsize=HEADING_SIZE)
    uncaptioned_img_bbox = [40, 80, 200, 180]
    p2.draw_rect(fitz.Rect(*uncaptioned_img_bbox), color=(0, 0, 0), fill=(0.6, 0.6, 0.6))
    p2.insert_text(
        (40, 260),
        "This paragraph sits far enough below the picture, and reads as ordinary prose, "
        "not a short caption underneath it.",
        fontsize=BODY_SIZE,
    )

    # Page 3: an image region drawn directly over a line of REAL running
    # prose (not a picture) — the exact false positive found during manual
    # acceptance testing on a real book: the region swallows a sentence,
    # and the short line right after it would satisfy every spatial
    # signal (close, aligned, body-size, short) despite being nothing but
    # the next line of that same paragraph. The region must still convert
    # to a figure — that part of the feature is working as designed — but
    # must NOT bind that next line as a caption.
    p3 = doc.new_page(width=PAGE_W, height=PAGE_H)
    p3.insert_text((40, 40), "CHAPTER FOUR", fontsize=HEADING_SIZE)
    p3.insert_text((40, 80), PROSE_LINE, fontsize=BODY_SIZE)
    p3.insert_text((40, 100), SHORT_NEXT_LINE, fontsize=BODY_SIZE)

    os.makedirs(OUT_DIR, exist_ok=True)
    doc.save(PDF_PATH)
    doc.close()

    doc = fitz.open(PDF_PATH)
    garbled_bbox = None
    prose_bbox = None
    for block in doc[1].get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                if span.get("text", "").strip() == GARBLED_HEADING:
                    garbled_bbox = list(span["bbox"])
    for block in doc[3].get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                if span.get("text", "").strip() == PROSE_LINE:
                    prose_bbox = list(span["bbox"])
    doc.close()
    if garbled_bbox is None:
        raise RuntimeError("setup failed — could not locate the garbled heading's own bbox")
    if prose_bbox is None:
        raise RuntimeError("setup failed — could not locate the real-prose line's own bbox")

    return img_bbox, garbled_bbox, uncaptioned_img_bbox, prose_bbox


def main() -> int:
    failures: list[str] = []

    def check(name: str, cond: bool) -> None:
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
        if not cond:
            failures.append(name)

    img_bbox, garbled_bbox, uncaptioned_img_bbox, prose_bbox = _build_synthetic_pdf()
    image_regions = [
        {"page_index": 0, "bbox": img_bbox},
        {"page_index": 2, "bbox": uncaptioned_img_bbox},
        {"page_index": 3, "bbox": prose_bbox},
    ]
    ocr_regions = [{"page_index": 1, "bbox": garbled_bbox, "text": "CHAPTER TWO", "confidence": 91}]

    result = convert_pdf_to_chapters(
        PDF_PATH,
        excluded_pages=set(),
        cover_page_index=0,
        image_pages=set(),
        toc_pages=set(),
        header_ratio=None,
        footer_ratio=None,
        excluded_text_regions=None,
        image_regions=image_regions,
        ocr_regions=ocr_regions,
    )

    titles = [c.title for c in result.chapters]
    print("chapter titles:", titles)
    for w in result.warnings:
        print(f"  warning [{w['severity']}] {w['message']}")

    print("\n-- image region --")
    ch1 = next((c for c in result.chapters if c.title == "CHAPTER ONE"), None)
    check("first chapter found", ch1 is not None)
    if ch1:
        full_html = "".join(ch1.paragraphs)
        check("figure present in chapter html", "<figure" in full_html and "<img" in full_html)
        check("chapter carries exactly one embedded image", len(ch1.images) == 1)
        check("caption bound into figcaption", f"<figcaption>{CAPTION_TEXT}</figcaption>" in full_html)
        # No duplication: the caption text must appear exactly once
        # (inside the figcaption), never again as an ordinary paragraph.
        check("caption not duplicated as a plain paragraph", full_html.count(CAPTION_TEXT) == 1)
        check(
            "text following the figure still present (surrounding text untouched)",
            "second paragraph continues right after the figure" in full_html,
        )

    print("\n-- image region with no qualifying caption nearby --")
    ch3 = next((c for c in result.chapters if c.title == "CHAPTER THREE"), None)
    check("third chapter found", ch3 is not None)
    if ch3:
        full_html3 = "".join(ch3.paragraphs)
        check("figure still emitted without a caption", "<figure" in full_html3)
        check("no figcaption bound on weak spatial evidence", "<figcaption" not in full_html3)
        check(
            "the distant paragraph stays ordinary text, as its own <p>, not folded into the figure",
            "<p>This paragraph sits far enough below the picture" in full_html3,
        )
        check(
            "an info warning flags the unbound caption for manual review",
            any(
                w["severity"] == "info" and "başlık/açıklama otomatik" in w["message"]
                for w in result.warnings
            ),
        )

    print("\n-- image region drawn over real prose (caption false-positive guard) --")
    ch4 = next((c for c in result.chapters if c.title == "CHAPTER FOUR"), None)
    check("fourth chapter found", ch4 is not None)
    if ch4:
        full_html4 = "".join(ch4.paragraphs)
        check("region text suppressed from the ordinary paragraph stream", PROSE_LINE not in full_html4)
        check("figure still emitted for the region", "<figure" in full_html4)
        check(
            "the next line is NOT bound as a caption despite matching every spatial signal",
            "<figcaption" not in full_html4,
        )
        check(
            "the next line survives as ordinary text instead of being silently dropped",
            SHORT_NEXT_LINE in full_html4,
        )

    print("\n-- OCR region --")
    ch2 = next((c for c in result.chapters if c.title == "CHAPTER TWO"), None)
    check("OCR-corrected heading detected as a real heading (chapter split on it)", ch2 is not None)
    all_text = "".join(p for c in result.chapters for p in c.paragraphs) + " ".join(titles)
    check("garbled original heading text is absent from the output", GARBLED_HEADING not in all_text)
    if ch2:
        check(
            "body text after the OCR'd heading is still present",
            "ordinary filler prose for the second page" in "".join(ch2.paragraphs),
        )

    print("\n-- built EPUB artifact --")
    chapters_out = [
        ChapterOut(
            id=c.id, index=c.index, title=c.title, kind=c.kind, eyebrow=c.eyebrow,
            html="".join(c.paragraphs),
            footnotes=[Footnote(id=f.id, marker=f.marker, text=f.text) for f in c.footnotes],
            is_split_continuation=c.is_split_continuation,
            image_base64=c.image_base64,
            images=[ChapterImage(**img) for img in c.images],
        )
        for c in result.chapters
    ]
    build_epub(
        book_title="Region Test", author="Test", chapters=chapters_out, css=MATBAA_CSS,
        output_path=EPUB_PATH, cover_image_base64=result.cover_image_base64,
        language=result.detected_language,
    )
    with zipfile.ZipFile(EPUB_PATH) as z:
        names = z.namelist()
        image_files = [n for n in names if n.startswith("EPUB/images/") and n.endswith("_img1.png")]
        check("all region images present in built EPUB package", len(image_files) == 3)
        found_ref = False
        for n in names:
            if n.endswith(".xhtml"):
                content = z.read(n).decode("utf-8", "replace")
                m = re.search(r'<img src="(images/[^"]+\.png)"', content)
                if m and ("EPUB/" + m.group(1)) in names:
                    found_ref = True
        check("figure's <img src> resolves to a real file in the EPUB", found_ref)

    print()
    if failures:
        print(f"FAIL — {len(failures)} check(s) failed: {failures}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
