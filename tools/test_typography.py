"""Typesetting text the way a printed Turkish book does (backend/app/typography.py).

    python tools/test_typography.py

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

from app.typography import NBSP, set_html, set_text  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        failures.append(name)


print("\nQuotes and apostrophes")
check("double quotes open and close", set_text('O "kent hakkı" dedi.') == "O “kent hakkı” dedi.")
check("a quote opening the text opens", set_text('"Evet," dedi.') == "“Evet,” dedi.")
check("the apostrophe of a suffix", set_text("Simmel'in büyük şehri, 1980'lerde") == "Simmel’in büyük şehri, 1980’lerde")
check("single quotes as quotation marks", set_text("ona 'yoldaş' dedi") == "ona ‘yoldaş’ dedi")
check("a quote after an opening bracket opens", set_text('("Devlet ve İhtilal")') == "(“Devlet ve İhtilal”)")
check("two single quotes are a double one", set_text("''Aaa!'' deyip") == "“Aaa!” deyip")
check("a quote inside a quote", set_text("buen vivir \"'sağlığa'\" ve '\"normal\"'") ==
      "buen vivir “‘sağlığa’” ve ‘“normal”’")

print("\nEllipsis and dashes")
check("three full stops are an ellipsis", set_text("Beklemek... Gündemde. . . ayaklanma") == "Beklemek… Gündemde… ayaklanma")
check("a double hyphen is an em dash", set_text("kent--ve köy") == "kent—ve köy")
check("a spaced hyphen is an en dash", set_text("Lenin - Stalin dönemi") == "Lenin – Stalin dönemi")
check("a range of years or pages takes an en dash", set_text("1990-1995 arası, s. 12-15") ==
      "1990–1995 arası, s." + NBSP + "12–15")
check("a hyphenated word keeps its hyphen", set_text("Marksizm-öncesi mekan-zamansal") == "Marksizm-öncesi mekan-zamansal")
check("a web address keeps every character", set_text('bkz. http://example.org/a--b "x"') ==
      'bkz. http://example.org/a--b “x”')

print("\nNo-break spaces")
check("between 's.' and its page number", set_text("bkz. s. 87") == "bkz. s." + NBSP + "87")
check("inside an era and its year", set_text("M.Ö. 500 yılında") == "M.Ö." + NBSP + "500 yılında")

print("\nHTML: text nodes only")
src = '<p class="x" data-a="a--b">O &quot;kent&quot; dedi; Simmel&#x27;in <em>şehri</em>... <a href="#fn_1">1</a></p>'
out = set_html(src)
check("tags and attributes are untouched", 'class="x" data-a="a--b"' in out and '<a href="#fn_1">1</a>' in out)
check("escaped quotes in text become curly", "O “kent” dedi; Simmel’in <em>şehri</em>… " in out)
check("an ampersand stays escaped", set_html("<p>Marx &amp; Engels</p>") == "<p>Marx &amp; Engels</p>")
check("a quote right after an inline tag closes when a word stands before it",
      set_html('<p><em>şehir</em>"</p>') == "<p><em>şehir</em>”</p>")
check("a quote opening a paragraph opens, whatever the last one ended with",
      set_html('<p>bitti.</p><p>"Evet," dedi.</p>') == "<p>bitti.</p><p>“Evet,” dedi.</p>")
check("a contents page's leader dots stay as printed", set_text("Giriş ........ 5") == "Giriş ........ 5")
check("four dots (a full stop and an ellipsis) stay as printed", set_text("bitti. . . .") == "bitti. . . .")

print("\nIn the exported book")
import tempfile  # noqa: E402
import zipfile  # noqa: E402

from app.builders.css_template import MATBAA_CSS  # noqa: E402
from app.builders.epub_builder import build_epub  # noqa: E402
from app.hyphenate import SHY  # noqa: E402
from app.models import ChapterOut, Footnote  # noqa: E402
from app.validate import check_epub  # noqa: E402

chapter = ChapterOut(
    id="ch_0001", index=0, title='"Kent Hakkı" Üzerine',
    html='<p>Lefebvre&#x27;in &quot;kent hakkı&quot; dediği şey... toplumsal bir talepti (bkz. s. 12-15).'
         '<sup class="footnote-ref"><a href="#fn_1" id="fnref_fn_1" epub:type="noteref">1</a></sup></p>',
    footnotes=[Footnote(id="fn_1", marker="1", text='Bkz. "Le droit à la ville", 1968.')],
)
out_dir = tempfile.mkdtemp()


def book_xhtml(**kw) -> str:
    path = build_epub(book_title="Deneme", author="Yazar", chapters=[chapter], css=MATBAA_CSS,
                      output_path=os.path.join(out_dir, f"b{len(os.listdir(out_dir))}.epub"), **kw)
    with zipfile.ZipFile(path) as z:
        text = z.read("EPUB/ch_0001.xhtml").decode("utf-8")
    errors = [f for f in check_epub(path) if f.severity == "error"]
    return text, errors


xhtml, errors = book_xhtml(language="tr")
check("the text is typeset", "Lefebvre’in “kent hakkı” dediği şey… toplumsal" in xhtml
      and "s." + NBSP + "12–15" in xhtml)
check("the heading and the note too", "“Kent Hakkı” Üzerine" in xhtml and "Bkz. “Le droit à la ville”, 1968." in xhtml)
check("the note reference is untouched", '<a href="#fn_1" id="fnref_fn_1" epub:type="noteref">1</a>' in xhtml)
check("no soft hyphens unless asked", SHY not in xhtml)
check("a valid EPUB", not errors)

xhtml, errors = book_xhtml(language="tr", hyphenate=True)
check("asked, a Turkish book is hyphenated", "top" + SHY + "lum" + SHY + "sal" in xhtml)
check("but not its headings", "“Kent Hakkı” Üzerine</h1>" in xhtml)
check("and stays valid", not errors)
xhtml, _ = book_xhtml(language="en", hyphenate=True)
check("a book in another language is left to the Kindle's own dictionaries", SHY not in xhtml)

if failures:
    print(f"\n{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("\nALL CHECKS PASSED")
