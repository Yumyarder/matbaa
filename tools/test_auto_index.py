"""An index for a book without one (backend/app/auto_index.py, the export).

    python tools/test_auto_index.py

Exit code is 1 if anything fails.
"""
from __future__ import annotations

import os
import re
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
os.environ["MATBAA_PROJECTS"] = tempfile.mkdtemp()

from app import auto_index  # noqa: E402
from app.models import ChapterOut, Footnote  # noqa: E402
from app.notebook import book_blocks  # noqa: E402
from app.turkish_words import Lemmatizer  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        failures.append(name)


PAGE = '<span epub:type="pagebreak" role="doc-pagebreak" id="page-{0}" aria-label="{0}"></span>'


def chapter(cid: str, title: str, paragraphs, footnotes=()):
    return ChapterOut(id=cid, index=int(cid[-1]), title=title, html="".join(paragraphs),
                      footnotes=[Footnote(id=f"fn{k}", marker=str(k), text=t) for k, t in enumerate(footnotes, 1)])


book = SimpleNamespace(chapters=[
    chapter("ch_0001", "Giriş", [
        f"<p>Kentin müşterekleri üzerine bir giriş.{PAGE.format(12)} Antonio Gramsci bu konuda yazmıştır.</p>",
        "<p>Gramsci'nin hegemonya kavramı burada önemlidir. Marx'ın da söyledikleri var.</p>",
        f"<p>{PAGE.format(13)}Ama Lenin'e göre durum farklıydı, Marx'a göre de öyle.</p>",
        "<p>Devlet meselesi Lenin'in eserinde merkezdedir; devlet her yerdedir, devlet de öyle.</p>",
    ], footnotes=["Bkz. Harvey, D. Rebel Cities, Verso Press, 2012."]),
    chapter("ch_0002", "Paris Komünü Üzerine", [
        f"<p>{PAGE.format(40)}Paris Komünü bir müşterekleşme deneyimiydi. Bu Gramsci'nin değil Marx'ın konusuydu.</p>",
        "<p>Ocak ayında Paris Komünü kuruldu; Lenin onu inceledi. Alman askerleri kenti kuşattı.</p>",
        f"<p>{PAGE.format(41)}Antonio Gramsci hapisteydi. Müştereklerin savunusu sürdü; TİP'in programı da.</p>",
        "<p>TİP'in tavrı belirsizdi. TİP'e göre Paris Komünü bir örnekti. Üçüncü Bölüm bunu ele alır.</p>",
    ]),
    chapter("ch_0003", "Kaynakça", ["<p>Harvey, David. Rebel Cities. London: Verso Press, 2012.</p>",
                                    "<p>Harvey, David. Social Justice and the City. Verso Press.</p>"]),
])

print("\nNames")
names = auto_index.find_names(book_blocks(book))
terms = {e.term for e in names.values()}
check("names marked by their apostrophe, used enough", {"Marx", "Lenin", "TİP"} <= terms)
check("a name of two words, and its surname counted under it", "Antonio Gramsci" in terms and "Gramsci" not in terms
      and next(e for e in names.values() if e.term == "Antonio Gramsci").count >= 4)
check("a place of two words", "Paris Komünü" in terms)
check("a common word capitalised at a sentence's start is no name", not ({"Devlet", "Ama", "Bu", "Kentin"} & terms))
check("months, nationalities and the book's own headings are left out", not ({"Ocak", "Alman", "Üçüncü Bölüm"} & terms))
check("names in the notes and the bibliography are not counted", not ({"Harvey", "Verso Press", "London"} & terms))

print("\nThe reader's concepts")
lem = Lemmatizer({"müşterek", "hegemonya"}).lemma
concepts = {"musterek": "Müşterek", "hegemonya": "Hegemonya", "kent hakki": "Kent Hakkı"}
found = auto_index.find_concepts(book_blocks(book), concepts, lem)
check("a concept found in its forms (\"müşterekleri\", \"Müştereklerin\", \"müşterekleşme\")",
      "musterek" in found and found["musterek"].count == 3)
check("a concept found as it is", "hegemonya" in found and found["hegemonya"].kind == "kavram")
check("a concept the book does not use is not listed", "kent hakki" not in found)

print("\nThe entries and their pages")
entries = auto_index.build(book, concepts, lem)
by = {e.term: e for e in entries}
check("pages from the book's page marks", by["Antonio Gramsci"].pages() == ["12", "40", "41"]
      and by["Lenin"].pages() == ["13", "40"] and by["Paris Komünü"].pages() == ["40", "41"])
check("Turkish alphabetical order (c < ç, ı < i)", [e.term for e in entries] ==
      sorted([e.term for e in entries], key=auto_index.sort_key)
      and auto_index.sort_key("Çin") > auto_index.sort_key("Cin") and auto_index.sort_key("İş") > auto_index.sort_key("Işık"))
check("a term the reader removed is gone", "Marx" not in {e.term for e in auto_index.build(book, removed=["Marx"])})
html = auto_index.chapter_html(entries, paged=True)
check("letter headings and linked pages", '<p class="index-letter">A</p>' in html
      and '<a href="#page-40">40</a>' in html and "Müşterek ◦" in html)

print("\nA book without printed pages")
plain = SimpleNamespace(chapters=[ChapterOut(id=c.id, index=c.index, title=c.title,
                                             html=re.sub(r'<span epub:type="pagebreak"[^>]*></span>', "", c.html),
                                             footnotes=c.footnotes) for c in book.chapters])
entries2 = auto_index.build(plain)
html2 = auto_index.chapter_html(entries2, paged=False)
anchored = auto_index.anchor_ids(plain, entries2)
gram = next(e for e in entries2 if e.term == "Antonio Gramsci")
target = gram.places[0]
check("numbered links to the paragraphs", f'href="{target.chapter_id}.xhtml#ix-{target.block}">1</a>' in html2)
check("each paragraph pointed at gets its id, in the exported copy only",
      f'<p id="ix-{target.block}">' in anchored[target.chapter_id] and "ix-" not in plain.chapters[0].html)
check("the text of an anchored chapter is unchanged", re.sub(r' id="ix-\d+"', "", anchored["ch_0001"]) == plain.chapters[0].html)
check("a book with its own printed index is told apart", not auto_index.has_printed_index(book.chapters)
      and auto_index.has_printed_index([ChapterOut(id="x", index=0, title="Dizin",
                                                   html='<p class="index-entry">Marx, 12</p>')]))

print("\nIn the exported book")
from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402
from app.builders.css_template import MATBAA_CSS  # noqa: E402
from app.models import ConversionSession  # noqa: E402
from app.session_store import save_session  # noqa: E402
from app.validate import check_epub  # noqa: E402

client = TestClient(main.app)
s = ConversionSession(session_id="s-dizin", book_title="Dizinli", author="Yazar", language="tr",
                      chapters=book.chapters, css=MATBAA_CSS)
save_session(s)
listed = client.get("/api/session/s-dizin/index").json()
check("the proposed index, with its terms and pages", listed["available"] and listed["paged"]
      and any(e["term"] == "Antonio Gramsci" and e["pages"] == ["12", "40", "41"] for e in listed["entries"]))
client.put("/api/session/s-dizin/meta", json={"auto_index": True, "index_removed": ["Marx"]})
path = main._build_session_epub(main.get_session("s-dizin"))
with zipfile.ZipFile(path) as z:
    names_in = z.namelist()
    index_file = next((n for n in names_in if n.endswith("dizin.xhtml")), None)
    index_html = z.read(index_file).decode("utf-8") if index_file else ""
    nav = z.read("EPUB/nav.xhtml").decode("utf-8")
check("a \"Dizin\" chapter at the end, in the contents", index_file is not None and "dizin.xhtml" in nav)
check("its page links point at the chapter holding the page", 'href="ch_0002.xhtml#page-40"' in index_html
      and "Marx" not in index_html)
check("the exported book is valid", not [f for f in check_epub(path) if f.severity == "error"])
check("the session's own text is unchanged", "Dizin" not in [c.title for c in main.get_session("s-dizin").chapters])
client.put("/api/session/s-dizin/meta", json={"auto_index": False})
with zipfile.ZipFile(main._build_session_epub(main.get_session("s-dizin"))) as z:
    check("and it can be left out", not any(n.endswith("dizin.xhtml") for n in z.namelist()))

if failures:
    print(f"\n{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("\nALL CHECKS PASSED")
