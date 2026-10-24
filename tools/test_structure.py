"""Book structure from the printed contents page.

    python tools/test_structure.py

Two parts. Unit cases pin backend/app/parsers/toc_structure.py on plain line
records — the three contents layouts real books use, title repair, the
printed-page offset. The acceptance part converts the real Tenin Gözleri PDF
(skipped if the corpus is absent) and checks the structure its owner reads.
Exit code is 1 if anything fails.
"""
from __future__ import annotations

import glob
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

from app.parsers.toc_structure import (  # noqa: E402
    Vocabulary,
    build_vocabulary,
    parse_printed_toc,
    printed_page_offset,
    split_author,
    vote_title,
)

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        failures.append(name)


def row(text, x0, y0, size=10.8, font="entry", page=0, x1=None):
    return {"text": text, "x0": x0, "y0": y0, "x1": x1 if x1 is not None else x0 + 6 * len(text),
            "y1": y0 + size, "font": font, "size": size, "page": page}


def shape(entries):
    return [(e.title, e.printed_page, e.path, e.is_label) for e in entries]


print("-- layout 1: centred labels, page numbers in their own column --")
lines = [
    row("İÇİNDEKİLER", 90, 55, size=17.5, font="head"),
    row("ÖN SÖZ", 137, 113, size=10.6, font="label", x1=178),
    row("İnce Buz, Steven Holl", 15, 137),
    row("1. BÖLÜM", 131, 224, size=8.9, font="label", x1=185),
    row("Görme ve Bilgi", 16, 247),
    row("Gözmerkezciliğin Eleştirmenleri", 16, 265),
    # numbers come last in the stream, as they did on the real page
    row("7", 292, 139, size=8.9, font="num", x1=299),
    row("19", 289, 247, size=8.9, font="num", x1=299),
    row("24", 288, 265, size=8.9, font="num", x1=300),
]
got = shape(parse_printed_toc(lines, 318))
check("labels, entries and numbers are paired by baseline", got == [
    ("ÖN SÖZ", None, [], True),
    ("İnce Buz, Steven Holl", 7, ["ÖN SÖZ"], False),
    ("1. BÖLÜM", None, [], True),
    ("Görme ve Bilgi", 19, ["1. BÖLÜM"], False),
    ("Gözmerkezciliğin Eleştirmenleri", 24, ["1. BÖLÜM"], False),
])

print("-- layout 2: dot leaders, wrapped titles, back matter --")
lines = [
    row("İçindekiler", 148, 118, size=16, font="f"),
    row("BİRİNCİ BÖLÜM", 54, 211, size=8, font="f"),
    row("MARX'IN KURAMI . . . . . . . . . 17", 54, 223, size=9, font="f"),
    row("DÖRDÜNCÜ BÖLÜM", 54, 319, size=8, font="f"),
    row("İNGİLİZ DEVRİMİ SIRASINDA SINIF", 54, 331, size=9, font="f"),
    row("VE NEWTON'IN DÜNYA GÖRÜŞÜ . . . . . .63", 54, 344, size=9, font="f"),
    row("DİZİN . . . . . . . . . . . . . . . .126", 54, 465, size=9, font="f"),
]
got = shape(parse_printed_toc(lines, 383))
check("a title set over two lines is one entry", (
    "İNGİLİZ DEVRİMİ SIRASINDA SINIF VE NEWTON'IN DÜNYA GÖRÜŞÜ", 63, ["DÖRDÜNCÜ BÖLÜM"], False
) in got)
check("the index sits at the top level, not under the last part",
      ("DİZİN", 126, [], False) in got)

print("-- layout 3: an unnumbered entry with indented sub-entries --")
lines = [
    row("Giriş ........................ 7", 35, 207, size=10.3),
    row("Üçüncü Hatırat", 35, 266, size=10.3),
    row("I ............................ 62", 49, 286, size=10.3),
    row("II. ........................... 89", 49, 306, size=10.3),
    row("Kapanış ...................... 113", 35, 327, size=10.3),
]
got = shape(parse_printed_toc(lines, 328))
check("sub-entries nest under their parent, which starts at its first child", got == [
    ("Giriş", 7, [], False),
    ("Üçüncü Hatırat", 62, [], False),
    ("I", 62, ["Üçüncü Hatırat"], False),
    ("II", 89, ["Üçüncü Hatırat"], False),
    ("Kapanış", 113, [], False),
])

print("-- printed page numbers, titles and authors --")
check("the folio offset is the majority", printed_page_offset({6: 7, 7: 8, 8: 9, 9: 10, 27: 60}) == 1)
check("no offset without agreement", printed_page_offset({1: 5, 2: 9}) is None)
check("a name after a comma is the author", split_author("İnce Buz, Steven Holl") == ("İnce Buz", "Steven Holl"))
check("the rest of an all-caps title is not an author",
      split_author("NEWTON DÖNEMİNDE İKTİSAT, TEKNOLOJİ VE FİZİK")[1] is None)

vocab = build_vocabulary([
    "Retinal imgeler retinal mimarlık retinal bakış.",
    "Steven Holl'ün yapıları. Steven Holl ile konuştuk. Steven Holl yazdı.",
    "Odak kaybı ve derinlik kaybı; kaybı hissettik.",
    "Akustik samimiyet, samimiyet duygusu.",
    "Bugünkü yıkıcıları anlamak, makine kırıcıları ile kırıcıları.",
])
check("OCR '!' for a final 'l' is repaired from the book's own words",
      vote_title("Retina! Mimarlık", None, vocab) == "Retinal Mimarlık")
check("a word the contents page misread is replaced by the chapter page's reading",
      vote_title("Akustik Samimryet", "Akustik Samimiyet", vocab) == "Akustik Samimiyet")
check("a name both sources misread is repaired from how the book prints it",
      vote_title("Steven Hali", "Steven Hali", vocab) == "Steven Holl")
check("an ordinary word is not swapped for a similar one elsewhere in the title",
      vote_title("BUGÜNKÜ YIKICILARI", "MAKİNE KIRICILARI BUGÜNKÜ YIKICILARI", vocab) == "BUGÜNKÜ YIKICILARI")
check("short words are never touched", vote_title("II", "il", vocab) == "II")
check("words with an apostrophe are kept whole",
      vote_title("HESSEN’İN NEWTON’I", None, vocab) == "HESSEN’İN NEWTON’I")

print("-- acceptance: Tenin Gözleri --")
pdfs = glob.glob(os.path.join(REPO_ROOT, "test-corpus", "Tenin*.pdf"))
if not pdfs:
    print("  (corpus not present — skipped)")
else:
    from app.builders.css_template import MATBAA_CSS
    from app.builders.epub_builder import build_epub
    from app.models import ChapterImage, ChapterOut, Footnote
    from app.parsers.pdf_parser import convert_pdf_to_chapters, get_pdf_page_previews

    pdf = pdfs[0]
    previews = get_pdf_page_previews(pdf)
    modes = {m: {p.index for p in previews if p.suggested_mode == m} for m in ("image", "toc", "exclude")}
    check("the back cover is suggested as a picture", 89 in modes["image"])
    result = convert_pdf_to_chapters(
        pdf, excluded_pages=modes["exclude"], image_pages=modes["image"], toc_pages=modes["toc"]
    )
    real = [c for c in result.chapters if c.kind == "chapter"]
    titles = [c.title for c in real]
    printed = [
        "İnce Buz", "Dünyaya Dokunmak",
        "Görme ve Bilgi", "Gözmerkezciliğin Eleştirmenleri", "Narsistik Göz ve Nihilistik Göz",
        "Görsel Mekana Karşı Oral Mekan", "Retinal Mimarlık ve Plastisitenin Kaybı",
        "Görsel İmgeler Mimarlığı", "Maddesellik ve Zaman", "Alberti Penceresinin Reddi",
        "Yeni Bir Görme ve Duyusal Denge",
        "Merkezdeki Beden", "Çokduyulu Deneyim", "Gölgenin Önemi", "Akustik Samimiyet",
        "Sessizlik, Zaman ve Yalnızlık", "Koku Mekanları", "Dokunmanın Şekli", "Taşın Tadı",
        "Kas ve Kemik İmgeleri", "Eylem İmgeleri", "Bedensel Özdeşleşme", "Bedenin Mimesisi",
        "Bellek ve İmgelem Mekanları", "Bir Duyular Mimarlığı", "Mimarlığın Görevi",
    ]
    check("chapter titles are exactly the printed contents", titles == printed)
    by_title = {c.title: c for c in real}
    check("the foreword opens with its label and author",
          by_title["İnce Buz"].eyebrow == "ÖN SÖZ" and by_title["İnce Buz"].byline == "Steven Holl")
    check("the introduction is its own chapter with its author",
          by_title["Dünyaya Dokunmak"].eyebrow == "GİRİŞ"
          and by_title["Dünyaya Dokunmak"].byline == "Juhani Pallasmaa")
    check("part labels sit on the first chapter of each part",
          by_title["Görme ve Bilgi"].eyebrow == "1. BÖLÜM"
          and by_title["Merkezdeki Beden"].eyebrow == "2. BÖLÜM"
          and by_title["Gözmerkezciliğin Eleştirmenleri"].eyebrow is None)
    check("every chapter knows its part",
          all(c.toc_path == ["1. BÖLÜM"] for c in real[2:11])
          and all(c.toc_path == ["2. BÖLÜM"] for c in real[11:]))
    body = " ".join(re.sub(r"<[^>]+>", "", p) for c in result.chapters for p in c.paragraphs)
    check("the back-cover blurb is not in the text", "Mimarlık esin verir" not in body)
    check("no invented spaces in words", not any(w in body for w in ("Maddesel lik", "M imarlık", "Bel lek")))
    check("no critical warnings", not any(w["severity"] == "critical" for w in result.warnings))
    check("words the OCR split into runs are whole again",
          not any(w in body for w in ("du yarlı", "koru yucumuz", "ka yganlığını", "Ü niversitesi")))
    check("the book is measured as separating paragraphs with space", result.paragraph_style == "spaced")
    intro = by_title["Dünyaya Dokunmak"].paragraphs
    check("the indented Montagu passage is a quotation",
          any('class="quote-block"' in p and "en eski ve en duyarlı" in p for p in intro))
    sources = [re.sub(r"<[^>]+>", "", p) for p in intro if 'class="attribution"' in p]
    check("each epigraph keeps its own source",
          [re.sub(r"\d+$", "", s) for s in sources] == [
              "Johann Wolfgang von Goethe", "Friedrich Nietzsche", "Richard Rorty",
              "Jorge Luis Borges", "Maurice Merleau-Ponty"])
    all_html = " ".join(p for c in real for p in c.paragraphs)
    check("words the book sets in italic are italic",
          "<em>Experiencing Architecture</em>" in all_html and "<em>(peripheral)</em>" in all_html
          and all_html.count("<em>") >= 30)
    check("emphasis never reaches a title", not any("\x0e" in c.title or "\x0f" in c.title for c in real))
    plates = [p for c in real for p in c.paragraphs if p.startswith('<figure class="plate">')]
    plate_nums = [re.findall(r'<p class="plate-num">(\d+)</p>', p) for p in plates]
    check("every plate numbers its captions as printed, one box each",
          len(plates) == 12 and plate_nums == [[str(i), str(i + 1)] for i in range(1, 25, 2)])
    check("the plate titles are kept",
          all('class="plate-title"' in p for p in plates)
          and any("GÖZ ŞEHRİ - DOKUNSAL ŞEHİR" in p for p in plates))
    check("plate numbers do not turn into note references",
          not any("footnote-ref" in p for p in plates)
          and not any('class="page-aside"' in p for c in real for p in c.paragraphs))
    # read as text: where the sentence runs on, a printed page begins
    check("a sentence runs on past the plate that interrupts it",
          any("duyumsallıktan ve erotizmden arınarak" in re.sub(r"<[^>]+>", "", p)
              for c in real for p in c.paragraphs))
    check("and the page it runs on to is marked there",
          any(re.search(r'duyumsallıktan <span epub:type="pagebreak"[^>]*id="page-43"[^>]*></span>ve erotizmden', p)
              for c in real for p in c.paragraphs))
    epigraph_notes = [f for f in by_title["Dünyaya Dokunmak"].footnotes if "Brooke Hodge" in f.text]
    check("the epigraph page's notes are notes, numbered as printed",
          len(epigraph_notes) == 1 and epigraph_notes[0].marker == "1"
          and "Harvard Üniversitesi" in epigraph_notes[0].text
          and not any("Brooke Hodge" in p for p in intro))

    out = os.path.join(REPO_ROOT, ".matbaa-work", "qa", "structure_tenin.epub")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    build_epub(
        book_title="Tenin Gözleri", author="Juhani Pallasmaa", css=MATBAA_CSS, output_path=out,
        cover_image_base64=result.cover_image_base64, language="tr",
        chapters=[
            ChapterOut(
                id=c.id, index=c.index, title=c.title, kind=c.kind, eyebrow=c.eyebrow,
                html="".join(c.paragraphs),
                footnotes=[Footnote(id=f.id, marker=f.marker, text=f.text) for f in c.footnotes],
                is_split_continuation=c.is_split_continuation, image_base64=c.image_base64,
                images=[ChapterImage(**i) for i in c.images], byline=c.byline, toc_path=c.toc_path,
            )
            for c in result.chapters
        ],
    )
    with zipfile.ZipFile(out) as z:
        nav = z.read("EPUB/nav.xhtml").decode("utf-8")
        opener = z.read(f"EPUB/{by_title['İnce Buz'].id}.xhtml").decode("utf-8")
    labels = re.findall(r"<a href=\"[^\"]+\">([^<]+)</a>\s*<ol>", nav)
    check("the reader's menu nests under the printed labels",
          labels == ["ÖN SÖZ", "GİRİŞ", "1. BÖLÜM", "2. BÖLÜM"])
    check("the menu entry carries the author as printed", "İnce Buz, Steven Holl" in nav)
    check("plates are not in the menu", "Görsel Sayfa" not in nav)
    check("the opener prints label, title and author in order",
          re.search(r'class="opener".*ÖN SÖZ.*<h1>İnce Buz</h1>.*Steven Holl', opener, re.S) is not None)


# --- the PDF's own bookmarks ------------------------------------------------
print("\nBookmarks as the book's structure")
from app.parsers.outline_structure import clean_title, reading_order, title_variants  # noqa: E402

page_index = [[1, f"Untitled.FR12 - {i:04d}_1L", i] for i in range(1, 60)]
check("a scanner's one-bookmark-per-page index is not a contents", reading_order(page_index, 60) == [])
check("placeholder bookmarks are not a contents",
      reading_order([[1, "Boş Sayfa", 1], [1, "Boş Sayfa", 2], [1, "Boş Sayfa", 3]], 50) == [])
check("letter-spaced bookmark titles close up", clean_title("Ö n s ö z") == "Önsöz")

lenin = [[1, "V. İ. Lenin, Ne Yapmalı?", 1], [1, "İçindekiler", 5], [1, "Önsöz", 9],
         [1, "BİR - Dogmacılık", 12], [2, "A. Eleştiri", 12], [2, "B. Savunucular", 16],
         [1, "İKİ - Kendiliğindenlik", 33], [2, "A. Kabarma", 34], [2, "B. Eğilme", 38]]
items = reading_order(lenin, 212)
chapters = [(i.title, i.path) for i in items if i.kind == "chapter"]
check("title page and contents bookmarks stay front matter", chapters[0][0] == "Önsöz")
check("a part's chapters are filed under it",
      ("A. Eleştiri", ["BİR - Dogmacılık"]) in chapters and ("B. Eğilme", ["İKİ - Kendiliğindenlik"]) in chapters)
check("a part that starts before its first chapter opens with its own pages",
      ("İKİ - Kendiliğindenlik", ["İKİ - Kendiliğindenlik"]) in chapters)
check("a part that is only a label over its first chapter is not a chapter of its own",
      ("BİR - Dogmacılık", ["BİR - Dogmacılık"]) not in chapters)

workbook = [[1, "Chapter 1", 16], [2, "Shyness and Social Anxiety", 16],
            [1, "Chapter 2", 40], [2, "Why Do You Have These Fears?", 40]]
items = reading_order(workbook, 274)
check("a label bookmark over its title becomes one chapter with the label above it",
      [(i.title, i.label) for i in items] == [("Shyness and Social Anxiety", "Chapter 1"),
                                              ("Why Do You Have These Fears?", "Chapter 2")])

essays = [[1, "Bütün Yazılar", 1], [1, "İÇİNDEKİLER", 5],
          [2, "Revizyonizmin Kokusu", 9], [3, "I", 10], [3, "II", 13],
          [2, "Sağ Sapma", 52], [3, "Objektif Şartlar", 59], [3, "İttifaklar", 81]]
items = reading_order(essays, 314)
kinds = [(i.kind, i.title) for i in items]
check("a book filed under its contents bookmark is read from under it",
      ("chapter", "Revizyonizmin Kokusu") in kinds)
check("bare section numbers under an essay are its sub-headings",
      ("subheading", "I") in kinds and ("chapter", "I") not in kinds)
check("named entries under a part are its chapters", ("chapter", "Objektif Şartlar") in kinds)
check("a numbered bookmark also matches its name printed alone",
      "Dogmacılık ve Eleştiri" in title_variants("BİR - Dogmacılık ve Eleştiri")
      and "İki Dünya Görüşü" in title_variants("I. İki Dünya Görüşü"))

print("\nA book whose headings look like its body still splits where its bookmarks say")
import fitz  # noqa: E402

from app.parsers.pdf_parser import convert_pdf_to_chapters as _convert  # noqa: E402

bm_path = os.path.join(REPO_ROOT, ".matbaa-work", "qa", "outline_book.pdf")
os.makedirs(os.path.dirname(bm_path), exist_ok=True)
bm = fitz.open()
sentence = "Bu bolumun metni burada akar ve sayfayi doldurur. "
names = ["Birinci Konu Burada Baslar", "Ikinci Konu Sonra Gelir", "Ucuncu Konu En Sonda"]  # helv has no Turkish glyphs
for name in names:
    for k in range(2):
        page = bm.new_page(width=400, height=600)
        y = 70
        if k == 0:
            page.insert_text((50, y), name, fontsize=10, fontname="helv")  # body size: no heading cue
            y += 30
        for _ in range(18):
            page.insert_text((50, y), sentence[:60], fontsize=10, fontname="helv")
            y += 14
bm.set_toc([[1, n, 1 + 2 * i] for i, n in enumerate(names)])
bm.save(bm_path)
bm.close()
res = _convert(bm_path)
real = [c for c in res.chapters if c.kind == "chapter"]
check("each bookmarked chapter is a chapter", [c.title for c in real] == names)
check("and the printed title is not repeated as text",
      not any(names[0] in re.sub(r"<[^>]+>", "", p) for p in real[0].paragraphs))

print("-- a flat outline repeating a method's step --")
items = reading_order([[1, "Eksiklik Teorisi", 4], [1, "Niçin Değişmeliyim?", 10], [1, "Duygu Sözcükleri", 16],
                       [1, "Jed ve Marjoire", 20], [1, "Beşinci Adım — Düzeltilmiş Yanıt", 24],
                       [1, "Harriet ve Jerry", 30], [1, "Beşinci Adım— Düzeltilmiş Yanıt", 34],
                       [1, "Anna ve Richard", 40]], 60)
check("the repeated step is a sub-heading, not a chapter",
      [it.title for it in items if it.kind == "chapter"]
      == ["Eksiklik Teorisi", "Niçin Değişmeliyim?", "Duygu Sözcükleri", "Jed ve Marjoire",
          "Harriet ve Jerry", "Anna ve Richard"])
items = reading_order([[1, "Birinci Kısım", 5], [2, "Giriş", 5], [2, "Toprak", 12], [2, "Hava", 16],
                       [1, "İkinci Kısım", 20], [2, "Giriş", 20], [2, "Deniz", 26], [2, "Ateş", 30]], 40)
check("but a chapter repeated across parts stays one",
      sum(1 for it in items if it.kind == "chapter" and it.title == "Giriş") == 2)

print("-- a contents page with its numbers in a column of their own --")
from app.parsers.pdf_parser import _toc_page_number_column  # noqa: E402

col = ["İÇİNDEKİLER", "ÖNSÖZ", "9", "Batıda Kapitalist Sınıfı", "15", "Tarihte İşçi Sınıfımız", "24",
       "I. Kadim Tarih Bakımından", "24", "II. Çağdaş Tarih Bakımından", "26", "Bankanın Dokunulmazlığı", ".40",
       "Müslüman'ı Tehdit", "44"]
check("two entries on one page do not stop it being a contents page", _toc_page_number_column(col))
notes = ["245", "1", "Bkz. Marx, Kapital.", "2", "Aynı eser.", "3", "Engels.", "4", "Lenin.", "5", "a.g.e."]
check("an endnote page, its markers restarting under a folio, still is not",
      not _toc_page_number_column(notes))

print("-- page numbers a scanner misread --")
from app.parsers.toc_structure import _read_ocr_number  # noqa: E402

check("letters read for digits become the number",
      [_read_ocr_number(t) for t in ("ı7", "2S", "S3", "7ı", "ll", "ıs", "ı 7")]
      == ["17", "25", "53", "71", "11", "15", "17"])
check("a part's roman numeral is not a page", _read_ocr_number("II") == "II")
check("nor a word", _read_ocr_number("Son") == "Son")
lines = [
    row("1. Plehanov'un Anarşistlerle Tartışması", 18, 100), row("132", 300, 100, font="num", x1=310),
    row("2. Kautsky'nin Oportünistlerle Tartışması", 18, 114), row("ı34", 300, 114, font="num", x1=310),
    row("3. Kautsky'nin Pannekoek'le Tartışması. 143", 18, 128),
]
got = [(e.title, e.printed_page) for e in parse_printed_toc(lines, 320)]
check("misread and leaderless numbers still pair with their entries", got == [
    ("1. Plehanov'un Anarşistlerle Tartışması", 132), ("2. Kautsky'nin Oportünistlerle Tartışması", 134),
    ("3. Kautsky'nin Pannekoek'le Tartışması.", 143)])

print("-- words a contents line set with no space between them --")
from app.parsers.toc_structure import unglue_words  # noqa: E402
from app.utils.text_quality import garbage_share  # noqa: E402

check("a capital inside a word starts the next one",
      unglue_words("KumandaÜstünlüğü:TemkinliSorumlulukGüvenidir.") == "Kumanda Üstünlüğü: Temkinli Sorumluluk Güvenidir.")
check("a name's short prefix is kept", unglue_words("McCarthy Dönemi") == "McCarthy Dönemi")
check("a dash-joined compound is words, not noise", garbage_share("Evrensel Savaş-Evrensel Devrim-Rusya") == 0)

print("-- parts, chapter numbers and a section's author on a contents page --")
from app.parsers.toc_structure import tidy_number  # noqa: E402
from app.parsers.pdf_parser import CHAPTER_LABEL_PREFIX, _tidy_label  # noqa: E402

lines = [
    row("Teşekkür", 43, 100, size=7.8, font="head"), row("9", 300, 100, font="num", x1=306),
    row("Ön söz", 43, 120, size=7.8, font="head"),
    row("Massimo De Angelis", 43, 132, size=6.7), row("11", 300, 132, font="num", x1=306),
    row("BİRİNCİ KISIM", 125, 160, size=7.8, font="head"),
    row("MEKANI MÜŞTEREKLEŞTİRMEK", 89, 172, size=7.8, font="head"),
    row("1.", 43, 190, size=6.9, font="numlabel"),
    row("Çitlenmiş Kentsel Takımada", 43, 202, size=6.7), row("27", 300, 202, font="num", x1=306),
    row("il.", 43, 222, size=6.9, font="numlabel"),
    row("Genişleyen Müşterekleşme", 43, 234, size=6.7), row("43", 300, 234, font="num", x1=306),
    row("Konut ve Kentsel Müşterekleşme", 43, 254, size=6.7), row("99", 300, 254, font="num", x1=306),
]
toc = [e for e in parse_printed_toc(lines, 320) if not e.is_label]
part = "BİRİNCİ KISIM — MEKANI MÜŞTEREKLEŞTİRMEK"
check("a label with a name under it is a section and its author",
      toc[1].title == "Ön söz, Massimo De Angelis" and toc[1].path == [])
check("two labels in a row name one part, and a chapter number groups nothing",
      [(e.title, e.path, e.number) for e in toc[2:4]]
      == [("Çitlenmiş Kentsel Takımada", [part], "1."), ("Genişleyen Müşterekleşme", [part], "il.")])
check("a scanner's roman numeral is set right", tidy_number("il.") == "II." and _tidy_label("iV. Bölüm") == "IV. Bölüm")
check("the label a chapter page prints over its title is found",
      CHAPTER_LABEL_PREFIX.match("vn. Bölüm Tahrifat Pratikleri").group(0) == "vn. Bölüm "
      and CHAPTER_LABEL_PREFIX.match("Bölümler arası") is None)

print("-- the book's title and author --")
from app.parsers.pdf_parser import _author_line, _choose_title_author, turkish_title_case  # noqa: E402

check("an all-caps title is set in Turkish title case",
      turkish_title_case("DEVLET VE DEVRİM") == "Devlet ve Devrim" and turkish_title_case("İYİ HİSSETMEK") == "İyi Hissetmek")
check("two credited authors are one author line",
      _author_line("Jeffrey E. Young, Ph.D. • Janet S. Klosko, Ph.D.") == "Jeffrey E. Young & Janet S. Klosko")
check("a title is not a name", _author_line("Halk Savaşının Planları") is None
      and _author_line("Türkiye’de Kapitalizm’in Gelişimi") is None and _author_line("V. İ. Lenin") == "V. İ. Lenin")
check("metadata with title and author swapped is put right by the title page",
      _choose_title_author("Dr. Hikmet Kıvılcımlı", "Halk Savaşının Planları", "Halk Savaşının Planları", None)
      == ("Halk Savaşının Planları", "Dr. Hikmet Kıvılcımlı"))
check("a file-name title gives way to the title page's spelling",
      _choose_title_author("turkiyede kapitalizmin gelisimi", "Mac", "Türkiye’de Kapitalizm’in Gelişimi", "Dr. Hikmet Kıvılcımlı")
      == ("Türkiye’de Kapitalizm’in Gelişimi", "Dr. Hikmet Kıvılcımlı"))
check("a catalogue's ISBN and inverted name are tidied",
      _choose_title_author("Four Thousand Weeks : Time Management for Mortals (9780374715243)", "Burkeman, Oliver", None, None)
      == ("Four Thousand Weeks: Time Management for Mortals", "Oliver Burkeman"))

from collections import Counter as _C  # noqa: E402
from app.parsers.pdf_parser import _respell_from_book  # noqa: E402

check("a title word takes the book's own spelling",
      _respell_from_book("Newton’ın Prıncıpıa’sının Kökleri", _C({"Principia": 36, "Prıncıpıa": 2, "Newton": 40}))
      == "Newton’ın Principia’sının Kökleri")
check("a spelling the book itself uses is kept",
      _respell_from_book("Devlet ve Devrim", _C({"Devlet": 30, "DEVLET": 3})) == "Devlet ve Devrim")
from app.parsers.pdf_parser import _tidy_author  # noqa: E402
check("an author set in capitals on the title page reads as the book spells the name",
      _tidy_author("STAVROS STAVRIDES ", _C({"Stavrides": 12})) == "Stavros Stavrides")
check("a Turkish name in capitals keeps its Turkish letters",
      _tidy_author("METİN ÇULHAOĞLU", _C()) == "Metin Çulhaoğlu")
check("an author already in mixed case is only trimmed", _tidy_author("  Louis  Althusser ", _C()) == "Louis Althusser")
check("a single word the front pages never print is the PDF tool's name, not an author",
      _tidy_author("Atom", _C(), ["BİRLİKTE İYİ HİSSETMEK", "David D. Burns"]) == "Unknown"
      and _tidy_author("mac", _C(), ["Türkiye Solu"]) == "Unknown")
check("a single-word author the title page prints is kept",
      _tidy_author("Lenin", _C(), ["V. İ. LENİN", "Devlet ve Devrim"]) == "Lenin")

print("-- leaders whose page number the text layer lost --")
lines = [
    row("1. Şemalar ................................ 17", 18, 100),
    row("2. Sizde Hangi Şemalar Var? .....................", 18, 114),
    row("3. Şemaları Anlamak ........................ 63", 18, 128),
]
titles = [e.title for e in parse_printed_toc(lines, 320)]
check("no title keeps its leader dots", not any("..." in t for t in titles))
check("and the entries are still read", "1. Şemalar" in titles and "3. Şemaları Anlamak" in titles)

print("-- a back cover at the book's own size is shown as printed --")
import tempfile  # noqa: E402

import fitz  # noqa: E402

from app.parsers.pdf_parser import _reads_as_back_cover, get_pdf_page_previews  # noqa: E402

check("ISBN with a price reads as a back cover",
      _reads_as_back_cover("Bir blurb.\nISBN 978-605-5541-06-4\n40 TL. KDV'den muaftır"))
check("ISBN alone (an imprint page) does not", not _reads_as_back_cover("Baskı: 2017\nISBN 978-605-5541-06-4"))
path = os.path.join(tempfile.mkdtemp(), "backcover.pdf")
d = fitz.open()
for k in range(6):
    page = d.new_page(width=382, height=552)
    if k == 0:
        page.insert_text((60, 100), "ISBN 978-605-5541-06-4 Baski 2017", fontsize=9)   # the imprint, at the front
    page.insert_textbox(fitz.Rect(50, 120, 332, 500), "Metin sayfasi. " * 80, fontsize=10)
back = d.new_page(width=382, height=552)
back.insert_textbox(fitz.Rect(50, 80, 332, 300), "Bu kitap kentin hafizasi uzerine bir denemedir. " * 4, fontsize=10)
back.insert_text((60, 450), "ISBN 978-605-5541-06-4", fontsize=9)
back.insert_text((60, 470), "40 TL  KDV dahil", fontsize=9)
d.save(path)
d.close()
modes = {p.index: p.suggested_mode for p in get_pdf_page_previews(path)}
check("the last page with an ISBN and a price is suggested as a picture", modes[6] == "image")
check("the imprint at the front stays text", modes[0] == "text")

if failures:
    print(f"\n{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("\nALL CHECKS PASSED")
