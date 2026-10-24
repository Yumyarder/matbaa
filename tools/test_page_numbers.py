"""Printed page numbers from the folios in the margins (backend/app/parsers/page_numbers.py).

    python tools/test_page_numbers.py

Exit code is 1 if anything fails.
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
sys.path.insert(0, os.path.join(REPO_ROOT, "backend"))

from app.parsers.page_numbers import printed_pages  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        failures.append(name)


print("\nOne numbering through the book")
# 20 pages; the text starts on PDF page 4 as page 1; chapter openers (4, 10) print no folio
folios = {p: p - 3 for p in range(5, 20) if p != 10}
pages = printed_pages(folios, 20)
check("every page from the first numbered one on", pages[5] == 2 and pages[19] == 16)
check("a chapter opener without a folio is numbered", pages[4] == 1 and pages[10] == 7)
check("front matter before page 1 is not", 0 not in pages and 3 not in pages)

print("\nA misread folio")
folios = {p: p - 3 for p in range(5, 20)}
folios[11] = 71                      # "7 1", or a figure number in the margin
pages = printed_pages(folios, 20)
check("does not move the page", pages[11] == 8)

print("\nA list numbered in the margin")
folios = {p: p - 6 for p in range(19, 112)}
folios.update({113: 7, 114: 8, 115: 9})              # "7, 8, 9": three in a row, a run of its own
folios.update({p: p - 6 for p in range(116, 200)})
pages = printed_pages(folios, 200)
check("does not stop the numbering", pages.get(150) == 144 and pages.get(114) == 108)

print("\nA folio read with the rule beside it as a leading one")
folios = {p: p + 1 for p in range(100, 110)}
folios.update({p: 1000 + p + 1 for p in range(110, 200)})   # "|157" read "1157", ninety times
pages = printed_pages(folios, 200)
check("is read without it", pages.get(156) == 157 and max(pages.values()) == 200)

print("\nPlates the numbering skips")
# pages 0..9 are 1..10; PDF pages 10 and 11 are unnumbered plates; page 12 is 11
folios = {p: p + 1 for p in range(0, 10)}
folios.update({p: p - 1 for p in range(13, 20)})
text = set(range(20)) - {10, 11}
pages = printed_pages(folios, 20, text_pages=text)
check("the plates get no number", 10 not in pages and 11 not in pages)
check("the page after them is the next number", pages[12] == 11 and pages[13] == 12)
check("numbers never repeat", len(set(pages.values())) == len(pages))

print("\nA page missing from the scan")
folios = {p: p + 1 for p in range(0, 10)}
folios.update({p: p + 2 for p in range(11, 20)})      # page 11 printed is never scanned
pages = printed_pages(folios, 20)
check("the page before the gap keeps its number", pages[10] == 11)
check("the numbering jumps after it", pages[11] == 13)

print("\nFar from any folio")
folios = {p: p + 10 for p in range(110, 130)}         # a scan whose first 110 folios were unreadable
pages = printed_pages(folios, 200)
check("the book does not say, and the page has no number", 50 not in pages and 85 not in pages)
check("near the run, it does", pages.get(95) == 105 and pages.get(140) == 150)

print("\nNo numbering to trust")
check("too few folios", printed_pages({4: 1, 5: 2}, 20) == {})
check("a spread per PDF page (numbers going up by two)", printed_pages({p: 2 * p for p in range(1, 15)}, 20) == {})

print("\nThe numbering starts again")
folios = {p: p + 1 for p in range(0, 10)}
folios.update({p: p - 9 for p in range(11, 20)})     # a second volume from page 2
pages = printed_pages(folios, 20)
check("numbered up to the restart and no further", pages.get(9) == 10 and 15 not in pages)
check("numbers never repeat", len(set(pages.values())) == len(pages))

print("\nA converted book carries its printed pages")
import re  # noqa: E402
import tempfile  # noqa: E402
import zipfile  # noqa: E402

import fitz  # noqa: E402

from app.builders.css_template import MATBAA_CSS  # noqa: E402
from app.builders.epub_builder import build_epub  # noqa: E402
from app.models import ChapterOut  # noqa: E402
from app.parsers.pdf_parser import convert_pdf_to_chapters  # noqa: E402
from app.validate import check_epub  # noqa: E402

SENTENCE = ("The city is made of shared spaces and of the practices that open them to all who pass "
            "through, and every square holds the memory of an assembly ")
work = tempfile.mkdtemp()
pdf_path = os.path.join(work, "numbered.pdf")
d = fitz.open()
d.new_page(width=382, height=552).insert_text((120, 200), "A TITLE PAGE", fontsize=18)
for n in range(1, 12):                     # PDF pages 1..11 are printed pages 5..15
    pg = d.new_page(width=382, height=552)
    # a page ends mid-sentence and the next takes it up in lower case; page 6
    # ends its sentence and page 7 opens a new paragraph
    text = ("Every page begins here. " if n == 7 else "and so it goes on, ") + SENTENCE * 6
    text += "and this sentence ends." if n == 6 else "" if n in (5, 11) else "and this sentence runs on"
    pg.insert_textbox(fitz.Rect(50, 60, 332, 500), text, fontsize=10)
    if n != 6:                             # a page that prints no folio
        pg.insert_text((186, 530), str(n + 4), fontsize=8)
d.save(pdf_path)
d.close()

result = convert_pdf_to_chapters(pdf_path)
paragraphs = [p for c in result.chapters for p in c.paragraphs]
whole = "".join(paragraphs)
found = [int(n) for n in re.findall(r'epub:type="pagebreak" role="doc-pagebreak" id="page-(\d+)"', whole)]
check("every printed page is marked once, in order", found == list(range(5, 16)))
check("the decision is in the book's report", result.decisions.get("printed_pages") == 11)
check("the page without a folio too", 10 in found)
check("no paragraph starts or ends with a page mark",
      not any(re.match(r"<p[^>]*><span epub:type=\"pagebreak\"", p) or p.endswith("></span></p>") for p in paragraphs))
check("no sentinel is left in the text",
      not re.search("[" + chr(0x12) + chr(0x13) + chr(0xE000) + "-" + chr(0xE009) + "]", whole))
check("a page broken mid-sentence is marked where the page begins",
      re.search(r'runs on <span epub:type="pagebreak"[^>]*id="page-6"[^>]*></span>and so', whole) is not None)
check("a page opening a paragraph is marked after its first word",
      re.search(r'<p[^>]*>Every<span epub:type="pagebreak"[^>]*id="page-11"[^>]*></span> page begins', whole) is not None)

epub_path = os.path.join(work, "numbered.epub")
build_epub(book_title="Numbered", author="Someone", chapters=[
    ChapterOut(id=c.id, index=i, title=c.title, html="".join(c.paragraphs)) for i, c in enumerate(result.chapters)],
    css=MATBAA_CSS, output_path=epub_path, language="en")
with zipfile.ZipFile(epub_path) as z:
    nav = z.read("EPUB/nav.xhtml").decode("utf-8")
listed = re.findall(r'<a href="[^"]+#page-(\d+)">(\d+)</a>', nav)
check("the nav's page-list lists them", [int(a) for a, _ in listed] == list(range(5, 16)))
check("and nothing else (no footnote counted as a page)", nav.count('epub:type="page-list"') == 1)
check("the EPUB is valid", not [f for f in check_epub(epub_path) if f.severity == "error"])

if failures:
    print(f"\n{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("\nALL CHECKS PASSED")
