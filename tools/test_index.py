"""A printed index read into a chapter of its own, its page numbers links to
the printed pages (backend/app/parsers/pdf_parser.py, the builder).

    python tools/test_index.py

Exit code is 1 if anything fails.
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
import zipfile

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "backend"))

import pymupdf as fitz  # noqa: E402

from app.builders.css_template import book_css  # noqa: E402
from app.builders.epub_builder import build_epub  # noqa: E402
from app.diagnosis import measure  # noqa: E402
from app.parsers.pdf_parser import convert_pdf_to_chapters  # noqa: E402
from app.pipeline import chapters_out  # noqa: E402
from app.validate import check_epub  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        failures.append(name)


SENTENCE = ("The city is made of shared spaces and of the practices that open them to all who pass "
            "through, and every square holds the memory of an assembly. ")
LEFT, RIGHT, SUB = 40, 200, 52

# (x, text) down each column; a sub-entry is set in, a long entry's later
# lines too, and the last entry of the first page goes on overleaf
INDEX_PAGES = [
    [(LEFT, "DIZIN"), (LEFT, "A"), (LEFT, "Agamben, Giorgio, 13, 15-16"), (LEFT, "ag olusturma, 12, 14,"),
     (SUB + 10, "18"), (LEFT, "Alexandras Kompleksi:"), (SUB, "sosyal konut, 15"), (SUB, "tasarim, 16-7"),
     (SUB, "Ayrica bkz."), (SUB, "Atina"), (LEFT, "B"), (LEFT, "balkonlar, 17"), (LEFT, "Bourdieu, Pierre, 99"),
     (RIGHT, "C"), (RIGHT, "Certeau, Michel, 12"), (RIGHT, "cok uzun bir terim ki iki satira"),
     (RIGHT + 22, "yayiliyor, 19"), (RIGHT, "D"), (RIGHT, "deniz, 11"), (RIGHT, "kent, 11, 13,")],
    [(LEFT, "17"), (LEFT, "E"), (LEFT, "Edensor, Tim, 14"), (LEFT, "egemen iktidar, 12-13"),
     (LEFT, "F"), (LEFT, "flaneur, 18"), (LEFT, "Foucault, Michel, 16"), (LEFT, "G"),
     (LEFT, "grafiti, 15, 19"), (LEFT, "gozetim, 13")],
]

work = tempfile.mkdtemp()
pdf_path = os.path.join(work, "indexed.pdf")
d = fitz.open()
d.new_page(width=382, height=552).insert_text((120, 200), "A TITLE PAGE", fontsize=18)
for n in range(1, 10):                      # PDF pages 1..9 are printed pages 11..19
    pg = d.new_page(width=382, height=552)
    pg.insert_textbox(fitz.Rect(50, 60, 332, 500), SENTENCE * 7, fontsize=10)
    pg.insert_text((186, 530), str(n + 10), fontsize=8)
for k, lines in enumerate(INDEX_PAGES):     # PDF pages 10, 11 are printed 20, 21
    pg = d.new_page(width=382, height=552)
    ys = {LEFT: 60, RIGHT: 60}
    for x, text in lines:
        column = LEFT if x < RIGHT else RIGHT
        pg.insert_text((x, ys[column]), text, fontsize=9)
        ys[column] += 13
    pg.insert_text((186, 530), str(20 + k), fontsize=8)
d.save(pdf_path)
d.close()

result = convert_pdf_to_chapters(pdf_path)
index = next((c for c in result.chapters if any("index-entry" in p for p in c.paragraphs)), None)

print("\nThe index is a chapter of its own")
check("found, and titled as the page titles it", index is not None and index.title == "Dizin")
# the page marks (printed pages) are not what these checks are about
paras = [re.sub(r'<span epub:type="pagebreak"[^>]*></span>', "", p) for p in (index.paragraphs if index else [])]
plain = [re.sub(r"<[^>]+>", "", p) for p in paras]
check("the big letters are letters", [t for p, t in zip(paras, plain) if "index-letter" in p] == list("ABCDEFG"))
check("an entry keeps its pages, each a link to the printed page",
      any('Agamben, Giorgio, <a href="#page-13">13</a>, <a href="#page-15">15-16</a>' in p for p in paras))
check("a line of page numbers carries on the entry above",
      "ag olusturma, 12, 14, 18" in plain and '<a href="#page-18">18</a>' in "".join(paras))
check("a sub-entry is set in", any('class="index-entry index-sub"' in p and "sosyal konut" in p for p in paras))
check("a long term's second line joins its first", "cok uzun bir terim ki iki satira yayiliyor, 19" in plain)
check("a cross-reference joins the name it points to", "Ayrica bkz. Atina" in plain)
check("an entry carries on overleaf", "kent, 11, 13, 17" in plain)
check("the title is not an entry", not any("DIZIN" in t for t in plain))
check("no page number is taken for a note reference", not any("footnote-ref" in p for p in paras))
check("an index entry starting in lower case is not a broken paragraph", measure(result)["lower_ratio"] == 0)

print("\nIn the EPUB")
out = os.path.join(work, "indexed.epub")
build_epub(book_title="Indexed", author="Someone", chapters=chapters_out(result),
           css=book_css(result.paragraph_style), output_path=out, language="en")
with zipfile.ZipFile(out) as z:
    xhtml = {n: z.read(n).decode("utf-8") for n in z.namelist() if n.endswith(".xhtml")}
index_file = next(n for n, t in xhtml.items() if "index-entry" in t)
links = re.findall(r'<a class="page-link" href="([^"]+)">', xhtml[index_file])
check("every link points at the chapter that holds the page",
      links and all(re.fullmatch(r"(ch_\d{4}\.xhtml)?#page-\d+", h) for h in links)
      and all(f'id="page-{h.split("#page-")[1]}"' in xhtml.get("EPUB/" + h.split("#")[0], xhtml[index_file])
              for h in links))
check("a page the book does not mark stays a number, unlinked",
      "Bourdieu, Pierre, 99" in re.sub(r"<[^>]+>", "", xhtml[index_file]) and "#page-99" not in xhtml[index_file])
check("the EPUB is valid", not [f for f in check_epub(out) if f.severity == "error"])

if failures:
    print(f"\n{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("\nALL CHECKS PASSED")
