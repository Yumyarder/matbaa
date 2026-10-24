"""Regression coverage for reading a scanned PDF.

    python tools/test_ocr_layer.py

A scanned book has no text layer at all: every page is a photograph, so
nothing downstream can find a single word on it. app/ocr_layer.py gives
such a PDF a real text layer before anything reads it. This builds a
page that is only a picture of text, runs that pass over it, and checks
that the words come back, that the page keeps its printed size, and that
the whole converter then reads the page as text.

Skipped (not failed) where Tesseract is not installed — the engine is a
native binary, not a pip package.
"""
from __future__ import annotations

import os
import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if os.path.join(REPO_ROOT, "backend") not in sys.path:
    sys.path.insert(0, os.path.join(REPO_ROOT, "backend"))

import fitz  # noqa: E402

from app import ocr_layer  # noqa: E402
from app.parsers.pdf_parser import (  # noqa: E402
    _ocr_text_reads_as_words,
    _strip_title_note_mark,
    convert_pdf_to_chapters,
    get_pdf_page_previews,
)

OUT_DIR = os.path.join(REPO_ROOT, ".matbaa-work", "qa")
os.makedirs(OUT_DIR, exist_ok=True)

PAGE_W, PAGE_H = 420, 620
TITLE = "Oturmak ve Insa Etmek"
BODY = (
    "Bu sayfa yalnizca bir fotograftir ve uzerinde hicbir metin katmani "
    "yoktur. Program sayfayi okumadan once kendi metin katmanini yazmali, "
    "yoksa kitapta tek bir kelime bile cikmaz. Ikinci cumle de burada durur "
    "ve paragrafin butun olarak geri gelmesi gerekir."
)

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        failures.append(name)


# --- text-only judgements, no OCR engine needed -----------------------------
print("\nOCR'd lines that are words, and lines that are recognition noise")
check("a read title reads as words", _ocr_text_reads_as_words(TITLE))
check("a decorated masthead the scanner guessed at does not",
      not _ocr_text_reads_as_words("aa My0ODoGAAKASTIRMA ARLKIM,"))
check("a line that switches case inside its words does not",
      not _ocr_text_reads_as_words("ICINDEKILER |VARIe Ik bILGIAHLAKAR"))
check("a note mark left on a title is dropped",
      _strip_title_note_mark("Insa Etmek Oturmak Dusunmek”") == "Insa Etmek Oturmak Dusunmek")
check("a real quotation in a title is kept",
      _strip_title_note_mark('“Oturmak” Uzerine') == '“Oturmak” Uzerine')


def build_picture_of_a_page(path: str) -> None:
    """A PDF page that is a photograph of text: rendered, then re-inserted
    as an image, so the text layer is gone exactly as a scanner leaves it."""
    typeset = fitz.open()
    page = typeset.new_page(width=PAGE_W, height=PAGE_H)
    page.insert_text((60, 90), TITLE, fontsize=19, fontname="helv")
    y = 140
    for line in [BODY[i:i + 58] for i in range(0, len(BODY), 58)]:
        page.insert_text((60, y), line, fontsize=11, fontname="helv")
        y += 20
    pix = page.get_pixmap(matrix=fitz.Matrix(3, 3))
    typeset.close()

    scanned = fitz.open()
    scan_page = scanned.new_page(width=PAGE_W, height=PAGE_H)
    scan_page.insert_image(fitz.Rect(0, 0, PAGE_W, PAGE_H), pixmap=pix)
    scanned.save(path)
    scanned.close()


print("\nGiving a scanned PDF a text layer")
if not ocr_layer.ocr_available():
    print("  (Tesseract not installed — skipped)")
else:
    scan_path = os.path.join(OUT_DIR, "ocr_scanned_page.pdf")
    build_picture_of_a_page(scan_path)

    doc = fitz.open(scan_path)
    check("the scan has no text of its own", not doc[0].get_text().strip())
    doc.close()
    check("and the pass knows which pages it has to read",
          ocr_layer.pages_without_text(scan_path) == [0])

    read_path = os.path.join(OUT_DIR, "ocr_scanned_page_read.pdf")
    seen: list = []
    ocr_layer.build_searchable_copy(
        scan_path, read_path, progress=lambda done, total: seen.append((done, total))
    )
    read = fitz.open(read_path)
    text = read[0].get_text()
    check("the page keeps the size it is printed at",
          abs(read[0].rect.width - PAGE_W) < 1 and abs(read[0].rect.height - PAGE_H) < 1)
    check("the words are there now", "Insa Etmek" in text.replace("\n", " "))
    check("and so is the body text", "metin katmani" in text.replace("\n", " ").replace("-\n", ""))
    check("progress is reported page by page", seen and seen[-1] == (1, 1))
    read.close()

    previews = get_pdf_page_previews(read_path)
    check("page review offers the read page as text", previews[0].suggested_mode == "text")

    result = convert_pdf_to_chapters(read_path)
    body = " ".join(p for c in result.chapters for p in c.paragraphs)
    check("the converter reads the page it could not read before",
          "metin katmani" in body and len(body.split()) > 30)

    print("\nA text layer that is noise is read again")
    # A broken font encoding: the page shows real words, the text layer
    # under it says something else entirely.
    noisy_path = os.path.join(OUT_DIR, "ocr_noisy_layer.pdf")
    noisy = fitz.open(scan_path)
    noise = "fiF#Ii;fsSff aBcD9 x7Qz Rr%tY kLmN0p " * 12
    for y in range(80, 560, 40):
        noisy[0].insert_text((40, y), noise[:70], fontsize=9, fontname="helv", render_mode=3)
    noisy.save(noisy_path)
    noisy.close()
    needs = ocr_layer.pages_needing_ocr(noisy_path)
    check("a page whose text layer is noise is found", needs.unreadable == [0] and needs.reason == "broken-text")
    reread = os.path.join(OUT_DIR, "ocr_noisy_layer_read.pdf")
    ocr_layer.build_searchable_copy(noisy_path, reread)
    doc = fitz.open(reread)
    reread_text = doc[0].get_text().replace("\n", " ")
    doc.close()
    check("and the printed words replace the noise",
          "metin katmani" in reread_text and "fiF#Ii" not in reread_text)

    print("\nA picture page in a book that has its text is left a picture")
    mixed_path = os.path.join(OUT_DIR, "ocr_mixed_book.pdf")
    mixed = fitz.open()
    for i in range(5):
        page = mixed.new_page(width=PAGE_W, height=PAGE_H)
        page.insert_text((60, 90), f"Bolum {i + 1}. " + BODY[:60], fontsize=11, fontname="helv")
    picture = fitz.open(scan_path)
    mixed.insert_pdf(picture)  # one picture-only page among typeset ones
    picture.close()
    mixed.save(mixed_path)
    mixed.close()
    check("its picture page is not sent to OCR", ocr_layer.pages_needing_ocr(mixed_path).pages == [])

    print("\nMany pages are read side by side")
    multi_path = os.path.join(OUT_DIR, "ocr_scanned_book.pdf")
    multi = fitz.open()
    for _ in range(5):
        one = fitz.open(scan_path)
        multi.insert_pdf(one)
        one.close()
    multi.save(multi_path)
    multi.close()
    multi_read = os.path.join(OUT_DIR, "ocr_scanned_book_read.pdf")
    steps: list = []
    ocr_layer.build_searchable_copy(multi_path, multi_read, progress=lambda d, t: steps.append((d, t)))
    doc = fitz.open(multi_read)
    check("every page of a scanned book is read, in order",
          doc.page_count == 5 and all("Insa Etmek" in p.get_text().replace("\n", " ") for p in doc))
    doc.close()
    check("and progress reaches the last page", steps[-1] == (5, 5))

if failures:
    print(f"\n{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("\nALL CHECKS PASSED")
