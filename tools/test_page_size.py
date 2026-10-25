"""A page cut to another size is a cover or a fold-out; a scan's drifting
trim is not (pdf_parser._book_page_size, get_pdf_page_previews).

    python tools/test_page_size.py

Exit code is 1 if anything fails.
"""
from __future__ import annotations

import os
import sys
import tempfile

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "backend"))

import pymupdf as fitz  # noqa: E402

from app.parsers.pdf_parser import _book_page_size, get_pdf_page_previews  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        failures.append(name)


print("\nThe book's own page")
w, h, tol = _book_page_size([(340, 522)] * 40)
check("a typeset book: its one size, the 3% bound", (w, h) == (340, 522) and tol == 0.03)
# a scanned periodical's trims, as they are (84 pages)
trims = {(400, 638): 23, (402, 639): 18, (403, 640): 8, (404, 640): 9, (405, 641): 6, (406, 641): 1,
         (406, 642): 5, (407, 642): 5, (408, 643): 2, (410, 644): 3, (412, 645): 1, (413, 646): 1,
         (415, 647): 1, (435, 659): 1}
drifting = [size for size, n in trims.items() for _ in range(n)]
w, h, tol = _book_page_size(drifting)
check("a scan whose trim drifts: the median, not the narrowest", w == 403 and abs(415 - w) <= w * tol
      and abs(435 - w) > w * tol)
sideways = [(340, 522)] * 336 + [(522, 340)] * 38 + [(380, 549)]
w, h, tol = _book_page_size(sideways)
check("a tenth of the pages turned sideways does not widen the bound past the cover",
      tol == 0.03 and abs(380 - w) > w * tol)

print("\nIn the page review")
work = tempfile.mkdtemp()
path = os.path.join(work, "drift.pdf")
doc = fitz.open()
text = "Bu bir metin sayfasıdır, okunacak kelimelerle dolu. " * 30
for k, width in enumerate([380, 400, 404, 405, 403, 404, 415, 405, 404, 403, 402, 404]):
    page = doc.new_page(width=width if k else 520, height=640 if k else 700)
    page.insert_textbox(fitz.Rect(30, 30, width - 30, 610), text, fontsize=9)
doc.save(path)
modes = [p.suggested_mode for p in get_pdf_page_previews(path)]
check("a page a little wider than its neighbours is still text", modes[6] == "text")
check("a cover cut to another size is shown as a picture", modes[0] == "image")
check("the rest is text", modes[1:] == ["text"] * 11)

if failures:
    print(f"\n{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("\nALL CHECKS PASSED")
