"""The reader's Kindle marks carried back into the book (backend/app/reader_notes.py).

    python tools/test_reader_notes.py

Uses a scratch notebook folder; exit code is 1 if anything fails.
"""
from __future__ import annotations

import os
import sys
import tempfile
import zipfile
from types import SimpleNamespace

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "backend"))
os.environ["MATBAA_NOTEBOOK"] = tempfile.mkdtemp()

from app import notebook, reader_notes  # noqa: E402
from app.builders.css_template import MATBAA_CSS  # noqa: E402
from app.builders.epub_builder import build_epub  # noqa: E402
from app.clippings import parse_any  # noqa: E402
from app.models import ChapterOut  # noqa: E402
from app.validate import check_epub  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        failures.append(name)


PAGE = '<span epub:type="pagebreak" role="doc-pagebreak" id="page-12" aria-label="12"></span>'
body = ("<p>Kent hakkı üzerine bir tartışma burada " + PAGE + "başlar ve uzun bir cümleyle sürer.</p>"
        "<p>Meydanlar <em>müşterekleşmenin</em> sahnesidir ve orada herkes eşit görünür.</p>"
        "<p>Bu paragrafta kimsenin altını çizmediği bir cümle var.</p>")
session = SimpleNamespace(session_id="t", book_title="Kent Hakkı Defteri", author="Yazar", css=MATBAA_CSS,
                          language="tr", cover_image_base64=None,
                          chapters=[ChapterOut(id="ch_0001", index=0, title="Giriş", html=body)])
clips = ("Kent Hakkı Defteri (Yazar)\n- Your Highlight on page 3 | Location 30-31 | Added on Sunday, 18 October 2026 10:00:00\n\n"
         "bir tartışma burada başlar\n==========\n"
         "Kent Hakkı Defteri (Yazar)\n- Your Note on page 3 | Location 31 | Added on Sunday, 18 October 2026 10:00:10\n\n"
         "?bu tartışma nerede başlıyor\n==========\n"
         "Kent Hakkı Defteri (Yazar)\n- Your Highlight on page 4 | Location 40-41 | Added on Sunday, 18 October 2026 10:01:00\n\n"
         "Meydanlar müşterekleşmenin sahnesidir\n==========\n"
         "Kent Hakkı Defteri (Yazar)\n- Your Note on page 4 | Location 41 | Added on Sunday, 18 October 2026 10:01:10\n\n"
         "!Gezi tam olarak buydu\n==========\n")
notebook.import_clips(parse_any(clips))

print("\nThe reader's Kindle book is found for the Matbaa book")
book = reader_notes.book_for_session(session)
check("by its title", book is not None and book.title == "Kent Hakkı Defteri")
check("and counted", reader_notes.count_for_session(session) == {"highlights": 2, "notes": 2})

print("\nPassages are marked, the book's markup untouched")
chapters, marked = reader_notes.annotate(session, book)
html = chapters[0].html
check("the exact words are underlined, across a printed page break",
      '<span class="reader-mark" id="hl-' in html and "bir tartışma burada " + PAGE + "başlar</span>" in html)
check("a passage across emphasis marks its paragraph instead, keeping the emphasis",
      'class="reader-marked"' in html and "<em>müşterekleşmenin</em>" in html)
check("an unmarked paragraph is left exactly as it was",
      "<p>Bu paragrafta kimsenin altını çizmediği bir cümle var.</p>" in html)
check("both passages count as marked", marked == 2)
check("the session itself is not changed", session.chapters[0].html == body)

print("\nThe appendix lists the notes, questions first, each linked to its passage")
appendix = chapters[-1]
check("it is the last chapter", appendix.id == reader_notes.APPENDIX_ID and appendix.title == "Notlarım ve Sorularım")
check("questions come before the reader's ideas",
      appendix.html.index("Sorularım") < appendix.html.index("bu tartışma nerede başlıyor")
      < appendix.html.index("Notlarım") < appendix.html.index("Ben: Gezi tam olarak buydu"))
check("each note links back to its passage", appendix.html.count('href="ch_0001.xhtml#hl-') == 2)

print("\nThe book with the reader's marks is a valid EPUB")
out = os.path.join(tempfile.mkdtemp(), "notlarimla.epub")
build_epub(book_title=session.book_title, author=session.author, chapters=chapters,
           css=session.css + reader_notes.CSS, output_path=out, language="tr")
errors = [f for f in check_epub(out) if f.severity == "error"]
check("no errors, every appendix link resolving", not errors)
with zipfile.ZipFile(out) as z:
    nav = z.read("EPUB/nav.xhtml").decode("utf-8")
check("and the appendix is in the contents", "Notlarım ve Sorularım" in nav)

if failures:
    print(f"\n{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("\nALL CHECKS PASSED")
