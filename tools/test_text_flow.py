"""Regression coverage for line reconstruction and running-head removal.

    python tools/test_text_flow.py

Two defects live here, and they are connected: PyMuPDF hands one printed
line back in several pieces when justification stretches a gap, and a
running head printed outside the crop band is never recognised as
furniture. Fixing the first without the second turns "header glued into
the middle of a sentence" into "header promoted to a chapter title", so
both are pinned together. Exit code is 1 if anything fails.
"""
from __future__ import annotations

import os
import re
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

from app.parsers.pdf_parser import (  # noqa: E402
    _merge_baseline_fragments,
    convert_pdf_to_chapters,
)

OUT_DIR = os.path.join(REPO_ROOT, ".matbaa-work", "qa")
os.makedirs(OUT_DIR, exist_ok=True)

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        failures.append(name)


def line(x0, y0, x1, y1, text):
    return {"bbox": [x0, y0, x1, y1], "spans": [{"text": text, "size": 10, "bbox": [x0, y0, x1, y1]}]}


print("-- rejoining one printed line handed back in pieces --")
# The real shape, measured off a justified page: both fragments report the
# same baseline and the second starts just left of where the first ended.
frags = [
    line(62.4, 145.93, 141.5, 160.77, "Simdi de tasima, "),
    line(139.1, 145.93, 328.4, 160.77, "sanayi ve madenciligin gelismesiyle ortaya "),
    line(62.4, 160.93, 92.2, 175.77, "cikan "),
    line(89.7, 160.93, 260.9, 175.77, "fizik problemlerini ele alalim."),
]
merged = _merge_baseline_fragments(frags, 10.89)
check("four fragments become two printed lines", len(merged) == 2)
check("the pieces are joined in reading order, left to right",
      [s["text"] for s in merged[0]["spans"]] == ["Simdi de tasima, ", "sanayi ve madenciligin gelismesiyle ortaya "])
check("the merged line's box spans both pieces",
      merged[0]["bbox"][0] == 62.4 and merged[0]["bbox"][2] == 328.4)

print("-- spaces PyMuPDF invented inside a word are dropped, real ones kept --")
from app.parsers.pdf_parser import RawBlock, _reading_order, _reconstruct_chars  # noqa: E402


def glyphs(spec, size=10.0):
    """spec: list of (char, x0, x1)."""
    return [{"c": c, "bbox": (x0, 0, x1, size)} for c, x0, x1 in spec]


# "Maddesel lik": a 0.17 em space that fills its gap exactly
invented = glyphs([("l", 0, 3), (" ", 3, 4.7), ("l", 4.7, 7.7), ("i", 7.7, 10)])
check("an invented narrow space inside a word is dropped",
      _reconstruct_chars(invented, 10.0, 0.25) == "lli")
# a real 0.25 em space glyph between two words
real = glyphs([("a", 0, 5), (" ", 5, 7.5), ("b", 7.5, 12)])
check("a space with the font's own width is kept",
      _reconstruct_chars(real, 10.0, 0.25) == "a b")
# lowercase followed by capital is a word break even when narrow
case = glyphs([("i", 0, 3), (" ", 3, 4.6), ("J", 4.6, 9)])
check("a narrow space before a capital is kept",
      _reconstruct_chars(case, 10.0, 0.25) == "i J")
check("nothing is dropped when the font's usual space is unknown",
      _reconstruct_chars(invented, 10.0, None) == "l li")
# next to punctuation a coincidence is possible, so it stays
punct = glyphs([("-", 0, 3), (" ", 3, 4.7), ("T", 4.7, 9)])
check("a narrow space next to punctuation is kept",
      _reconstruct_chars(punct, 10.0, 0.25) == "- T")

print("-- a single-column page is read top to bottom --")


def rb(text, x0, y0, x1, y1):
    return RawBlock(text=text, size=10, bbox=(x0, y0, x1, y1), page_num=0,
                    page_width=300, page_height=500)


stream = [rb("TITLE", 20, 45, 150, 60), rb("GİRİŞ", 250, 10, 300, 35), rb("body", 20, 250, 300, 400)]
check("a label printed above the title is read before it",
      [b.text for b in _reading_order(stream)] == ["GİRİŞ", "TITLE", "body"])
columns = [rb("right", 160, 10, 300, 400), rb("left", 10, 10, 150, 400)]
check("side-by-side blocks keep their stream order",
      [b.text for b in _reading_order(columns)] == ["right", "left"])

print("-- genuinely separate text is left alone --")
two_columns = [
    line(60, 100, 200, 114, "left column text"),
    line(340, 100, 480, 114, "right column text"),   # same baseline, wide gutter
]
check("a wide gutter is not treated as one line",
      len(_merge_baseline_fragments(two_columns, 10.0)) == 2)

stacked = [
    line(60, 100, 300, 114, "first line"),
    line(60, 120, 300, 134, "second line"),
]
check("consecutive lines stay separate",
      len(_merge_baseline_fragments(stacked, 10.0)) == 2)
check("an unfragmented block is returned untouched",
      _merge_baseline_fragments(stacked, 10.0) is stacked)

print("-- a running head outside the crop band is still removed --")
# 552pt tall, so the default 0.045 crop band is only ~24.9pt — this head
# sits at y=36, outside it, exactly like the real book that exposed this.
HEAD = "Sunus Yerine: Boris Hessenin Newtoni"
BODY = ("Bu govde metni sayfanin gercek icerigidir ve hicbir kosulda "
        "silinmemelidir cunku tekrar etmez.")
doc = fitz.open()
for n in range(6):
    page = doc.new_page(width=382, height=552)
    page.insert_text((60, 36), f"{HEAD} {10 + n}", fontsize=8)
    page.insert_text((60, 120), f"{BODY} Sayfa {n}.", fontsize=10)
path = os.path.join(OUT_DIR, "running_head.pdf")
doc.save(path)
doc.close()

result = convert_pdf_to_chapters(path)
text = " ".join(re.sub(r"<[^>]+>", "", p) for ch in result.chapters for p in ch.paragraphs)
titles = " ".join(ch.title or "" for ch in result.chapters)
check("the running head is not in the body text", HEAD not in text)
check("the running head did not become a chapter title", HEAD not in titles)
check("the body text is fully preserved", text.count("gercek icerigidir") == 6)

print("-- a line that repeats but is NOT in the margin survives --")
doc = fitz.open()
for _ in range(6):
    page = doc.new_page(width=382, height=552)
    page.insert_text((60, 260), "Bu tekrar eden dize sayfanin ortasindadir.", fontsize=10)
    page.insert_text((60, 300), BODY, fontsize=10)
path = os.path.join(OUT_DIR, "mid_page_repeat.pdf")
doc.save(path)
doc.close()
result = convert_pdf_to_chapters(path)
text = " ".join(re.sub(r"<[^>]+>", "", p) for ch in result.chapters for p in ch.paragraphs)
check("repetition alone does not delete mid-page text",
      text.count("tekrar eden dize") == 6)

print("-- a title page and imprint do not become a chapter --")
doc = fitz.open()
page = doc.new_page(width=382, height=552)
page.insert_text((60, 150), "KITABIN ADI", fontsize=18)
page.insert_text((60, 220), "Yazar Adsoyad", fontsize=18)
page.insert_text((60, 260), "Ceviren: Birisi", fontsize=9)
page = doc.new_page(width=382, height=552)
for i, imprint in enumerate([
    "ISBN 978-000-000-000-0", "Birinci Basim: 2019", "Baski: Bir Matbaa (Sertifika No: 1)",
    "Tel: 0212 000 00 00", "www.yayinevi.com",
]):
    page.insert_text((60, 380 + i * 12), imprint, fontsize=7)
long_body = " ".join([BODY] * 3)
for n in range(3):
    page = doc.new_page(width=382, height=552)
    if n == 0:
        page.insert_text((60, 100), "BIRINCI BOLUM", fontsize=18)
    page.insert_textbox(fitz.Rect(60, 130, 330, 520), long_body, fontsize=10)
path = os.path.join(OUT_DIR, "title_imprint.pdf")
doc.save(path)
doc.close()
result = convert_pdf_to_chapters(path)
titles = [ch.title for ch in result.chapters]
text = " ".join(re.sub(r"<[^>]+>", "", p) for ch in result.chapters for p in ch.paragraphs)
check("the author's name is not a chapter", "Yazar Adsoyad" not in titles)
check("the real first chapter is still a chapter", "BIRINCI BOLUM" in titles)
check("the imprint text is kept, not deleted", "ISBN 978-000-000-000-0" in text)
check("the folded title line is kept, not deleted", "Yazar Adsoyad" in text)

print("-- an approved OCR correction on a contents page is applied --")
doc = fitz.open()
page = doc.new_page(width=382, height=552)
page.insert_text((60, 60), "ICINDEKILER", fontsize=14)
toc_rows = ["Birinci Bolum . . . . . . . 7", "Gxrb1eD Bxlxm . . . . . . . 19",
            "Ucuncu Bolum . . . . . . . 31", "Dorduncu Bolum . . . . . . 44"]
for i, row in enumerate(toc_rows):
    page.insert_text((60, 120 + i * 30), row, fontsize=10)
page = doc.new_page(width=382, height=552)
page.insert_textbox(fitz.Rect(60, 80, 330, 520), long_body, fontsize=10)
path = os.path.join(OUT_DIR, "toc_ocr.pdf")
doc.save(path)
doc.close()
result = convert_pdf_to_chapters(
    path, toc_pages={0},
    ocr_regions=[{"page_index": 0, "bbox": [55, 140, 330, 155],
                  "text": "Ikinci Bolum . . . . . . . 19"}],
)
toc_html = " ".join(p for ch in result.chapters if ch.kind == "toc" for p in ch.paragraphs)
check("the approved correction appears in the contents", "Ikinci Bolum" in toc_html)
check("the garbled original is gone from the contents", "Gxrb1eD" not in toc_html)
check("no 'could not apply' warning for that page",
      not any("uygulanamadı" in w["message"] for w in result.warnings))

print("-- the EPUB opens on its cover, not on a contents page --")
import zipfile  # noqa: E402

from app.builders.css_template import MATBAA_CSS  # noqa: E402
from app.builders.epub_builder import build_epub  # noqa: E402
from app.models import ChapterImage, ChapterOut, Footnote  # noqa: E402

epub_path = os.path.join(OUT_DIR, "structure.epub")
build_epub(
    book_title="Test", author="Test", css=MATBAA_CSS, output_path=epub_path,
    cover_image_base64=result.cover_image_base64, language="tr",
    chapters=[
        ChapterOut(
            id=ch.id, index=ch.index, title=ch.title, kind=ch.kind, eyebrow=ch.eyebrow,
            html="".join(ch.paragraphs),
            footnotes=[Footnote(id=f.id, marker=f.marker, text=f.text) for f in ch.footnotes],
            is_split_continuation=ch.is_split_continuation, image_base64=ch.image_base64,
            images=[ChapterImage(**img) for img in ch.images],
        )
        for ch in result.chapters
    ],
)
with zipfile.ZipFile(epub_path) as z:
    opf = z.read("EPUB/content.opf").decode("utf-8")
itemrefs = re.findall(r"<itemref[^>]*/>", opf)
check("the cover is the first page of the reading flow",
      bool(itemrefs) and 'idref="cover"' in itemrefs[0] and "linear" not in itemrefs[0])
check("the generated contents page is kept out of the reading flow",
      not any('idref="nav"' in r for r in itemrefs) and 'properties="nav"' in opf)
check("a guide names the cover for Kindle", 'type="cover"' in opf and "<guide>" in opf)
check("a guide names where the text starts", 'type="text"' in opf)

# --- paragraphs that cross a change of kind -----------------------------------
print("\nA sentence is one paragraph whatever its halves were classified as")
from app.parsers.pdf_parser import convert_pdf_to_chapters as _conv  # noqa: E402

FILLER = "Bu satir sayfanin gercek govde metnidir ve uzunca devam eder."


def _book(path: str, pages) -> None:
    d = fitz.open()
    for lines in pages:
        pg = d.new_page(width=400, height=600)
        for x, y, text, font, size in lines:
            pg.insert_text((x, y), text, fontname=font, fontsize=size)
    d.save(path)
    d.close()


def _paras(path: str) -> list:
    res = _conv(path)
    return [re.sub(r"<[^>]+>", "", p) for c in res.chapters for p in c.paragraphs]


work = os.path.join(REPO_ROOT, ".matbaa-work", "qa")
os.makedirs(work, exist_ok=True)
body_page = [(40, 60 + 14 * i, FILLER, "helv", 10) for i in range(20)]
cross = os.path.join(work, "flow_cross_kind.pdf")
_book(cross, [body_page, body_page[:10] + [
    (40, 220, "Hikmet Kivilcimli: Evet. Peki. Yani konular cok genis. Bu sorula-", "tiit", 10),
    (40, 234, "rin hepsi bir oturumda tartisilmasi gereken genis konulardir.", "helv", 10),
]])
paras = _paras(cross)
# (compared without spaces: one line of a base-14 italic is too little for
# the per-font space measure to learn from, which is a property of this
# synthetic page, not of the join)
check("a line in another face that ends mid-word joins the next",
      any("busorularinhepsibiroturumda" in p.replace(" ", "").lower() for p in paras))

credits = os.path.join(work, "flow_credits.pdf")
_book(credits, [
    [(160, 100 + 16 * i, t, "helv", 9) for i, t in enumerate(
        ["Yayin Yonetmeni: Alican", "Duzelti: Emre Aygun", "Kapak Tasarimi: Hamdi", "Sertifika No: 63989"])],
    body_page, body_page,
])
paras = _paras(credits)
check("centered credit lines stay lines", sum(1 for p in paras if p.startswith(("Yayin", "Duzelti", "Kapak"))) == 3)

centered = os.path.join(work, "flow_all_centered.pdf")
narrow = "Bu kitapta butun metin dar ve ortali dizilmistir ve"
_book(centered, [[(110, 60 + 14 * i, narrow, "helv", 10) for i in range(24)] for _ in range(3)])
paras = _paras(centered)
check("a book set narrow and centered throughout reads as paragraphs, not a box per line",
      len(paras) < 10)

# --- lines the book repeats or the publisher adds -----------------------------
print("\nWatermarks and imprint lines")
from app.parsers.pdf_parser import RunningElements, _is_heading  # noqa: E402


def _line(text: str, size: float = 10.0, y: float = 300.0) -> RawBlock:
    return RawBlock(text=text, size=size, bbox=(40, y, 360, y + size), page_num=3,
                    page_width=400, page_height=600)


marks = RunningElements(signatures={"telegram ornekkanal"})
check("a watermark is furniture", marks.is_running(_line("Telegram: @ornekkanal")))
check("so is the watermark run together with a stray letter", marks.is_running(_line("Telegram: @ornekkanal N")))
check("a line that only starts like it is not",
      not marks.is_running(_line("Telegram ornekkanal kanalında yayımlanan bütün kitaplar")))
check("an edition note set large does not open a chapter",
      _is_heading(_line("Bu kitap ilk defa: 1974 yılında yayınlanmıştır.", size=16), 10.0) is None)
check("nor does a citation request",
      _is_heading(_line("Alıntılarda kaynak gösterilmesi dilenir.", size=16), 10.0) is None)
check("a real title set large still does", _is_heading(_line("Felsefi Materyalizm", size=16), 10.0) is not None)


def _ocr(text: str, size: float = 16.0) -> RawBlock:
    block = _line(text, size=size)
    block.font_name = "GlyphLessFont"
    return block


check("on a read page, noise from an illustration is not a title",
      _is_heading(_ocr("igs! e SP ğ ai"), 10.0) is None and _is_heading(_ocr("RR ln q |ii ;"), 10.0) is None)
check("nor is a sentence that measured large",
      _is_heading(_ocr("İki değil, daima üç adamdır bara giden. Neden? Çünkü birinci ortamı"), 10.0) is None)
check("nor a contents line with its leader dots",
      _is_heading(_ocr("BÖLÜM 1 - TEORİ VE ARAŞTIRMA........ 9"), 10.0) is None)
check("but a read title is", _is_heading(_ocr("Duygusal Problemlerin Tedavisinde Yeni Bir Çağ"), 10.0) is not None)

# --- inline emphasis --------------------------------------------------------
from app.parsers.pdf_parser import (  # noqa: E402
    EM_END, EM_START, _finalize_html_text, _join_line_pieces, _looks_paragraph_complete,
)
from app.utils.text_cleaning import repair_hyphenation  # noqa: E402

check("an italic run becomes <em>",
      _finalize_html_text(f"okudum {EM_START}Principia{EM_END}'yı") == "okudum <em>Principia</em>&#x27;yı")
check("an italic word OCR split into pieces is one run to the word's edge",
      _finalize_html_text(f"{EM_START}Experiencing A{EM_END}r{EM_START}chit{EM_END}ecture'ından")
      == "<em>Experiencing Architecture</em>&#x27;ından")
check("a run left open by a paragraph split is closed",
      _finalize_html_text(f"{EM_START}yarım kalan") == "<em>yarım kalan</em>")
check("a word hyphenated inside an italic run is rejoined",
      "Hegemonya" in repair_hyphenation(f"{EM_START}Hege­{EM_END}\n{EM_START}monya{EM_END}").replace(EM_START, "").replace(EM_END, ""))
check("a sentence ending inside an italic run is complete",
      _looks_paragraph_complete(f"bitti {EM_START}son.{EM_END}"))
check("touching OCR runs join without a space",
      _join_line_pieces([("du", 124.6, 133.7, 9.35), ("yarlı", 132.0, 149.4, 9.35)]) == "duyarlı")
check("runs a real gap apart keep their space",
      _join_line_pieces([("ve", 10.0, 20.0, 10.0), ("yol", 23.0, 40.0, 10.0)]) == "ve yol")

# --- footnote linking -------------------------------------------------------
from app.parsers.pdf_parser import Chapter as _Ch, Footnote as _Fn, _link_footnote_markers  # noqa: E402


def _linked(paragraphs, notes):
    ch = _Ch(id="ch_0001", index=1, title="t", paragraphs=list(paragraphs),
             footnotes=[_Fn(id=f"fn_ch_0001_{i}", marker=m, text=t) for i, (m, t) in enumerate(notes)])
    _link_footnote_markers(ch)
    return ch


ch = _linked(["İlk sayfa iyi1 ve kötü.", "İkinci sayfa yine1 başlar."], [("1", "a"), ("1", "b")])
check("per-page numbers link each reference to its own note",
      'href="#fn_ch_0001_0"' in ch.paragraphs[0] and 'href="#fn_ch_0001_1"' in ch.paragraphs[1])
ch = _linked(["sosyal-demokrasi* ve Komitesi** dedi."], [("*", "-Ed. ** Cellat")])
ids = [f.id for f in ch.footnotes]
check("a star note run into the one before it is split off", [f.marker for f in ch.footnotes] == ["*", "**"])
check("star notes get ids an href can name", all("*" not in i for i in ids)
      and all(f'href="#{i}"' in ch.paragraphs[0] for i in ids))
ch = _linked(["O 1995&#x27;te geldi."], [("27", "x")])
check("a character reference is not a note number", ch.paragraphs[0] == "O 1995&#x27;te geldi.")
ch = _linked(["bir5 iki6 üç7 dört8 beş9 sonra tek3."], [("3", "x")])
check("a reference outside the ordered window is still found", 'href="#fn_ch_0001_0"' in ch.paragraphs[0])

# --- OCR running feet -------------------------------------------------------
from app.parsers.pdf_parser import _detect_running_elements, _should_drop_as_furniture  # noqa: E402

_FEET = ["10 | V.İ. Lenin Karl Marks", "Vv. i. Lenin | 11 Karl Marks", "12 | V.i. Lenin Karl Marks",
         "V.i. Lenin | 13 Karl Marks", "14 | V.i. Lenin Karl Marks", "V.İ.Lenin | 15 Karl Marks"]


def _ocr_block(text, page, y0, y1):
    return RawBlock(text=text, size=9.0, bbox=(59.0, y0, 340.0, y1), page_num=page,
                    page_width=420.0, page_height=595.0, font_name="GlyphLessFont")


_pages = {}
for i, foot in enumerate(_FEET):
    _pages[i] = [_ocr_block("Gövde metni bu sayfada sürüyor ve bitmiyor", i, 80.0, 500.0),
                 _ocr_block(foot, i, 534.0, 550.0)]
_pages[2].append(_ocr_block("Kapital, Birinci Cilt, s. 781. -Ed", 2, 505.0, 515.0))
_pages[4].append(_ocr_block("Kapital, Birinci Cilt, s. 500. -Ed", 4, 505.0, 515.0))
_pages[5].append(_ocr_block("Kapital, Birinci Cilt, s. 12. -Ed", 5, 505.0, 515.0))
_run = _detect_running_elements(_pages)
check("an OCR running foot read differently on every page is furniture",
      all(_should_drop_as_furniture(_pages[i][1], _run) for i in _pages))
check("found by the OCR match, which reaches above the narrow foot band", not _run.is_running(_pages[0][1]))
check("but body text is not", not any(_should_drop_as_furniture(_pages[i][0], _run) for i in _pages))
_pages2 = {i: [_ocr_block(_FEET[i % 6], i, 534.0, 550.0)] for i in range(12)}
for i in range(3):
    _pages2[i].append(_ocr_block(f"Kapital, Birinci Cilt, s. {9 + i}. -Ed", i, 505.0, 515.0))
_run2 = _detect_running_elements(_pages2)
check("nor a citation repeated on a few pages of the notes",
      not any(_should_drop_as_furniture(b, _run2) for i in range(3) for b in _pages2[i] if "Kapital" in b.text))

# --- OCR'd bracketed note numbers -------------------------------------------
from app.parsers.pdf_parser import OCR_BRACKETED_REF, SUP_END, SUP_START, _split_note_marker  # noqa: E402


def _refs(text):
    return OCR_BRACKETED_REF.sub(lambda m: f"{SUP_START}{m.group(1) or m.group(2)}{SUP_END}", text)


check("a raised [8] read as !8! is a note reference",
      _refs("4 Mayıs 1919 hareketi!8! sırasında") == f"4 Mayıs 1919 hareketi{SUP_START}8{SUP_END} sırasında")
check("so is one after a closing quote that lost its opening bracket",
      _refs("budur.”5! Ama") == f"budur.”{SUP_START}5{SUP_END} Ama")
check("a year in parentheses is not", _refs("Lenin (1915) yazdı") == "Lenin (1915) yazdı")
check("nor a numbered list item", _refs("şunlar: (2) ikinci") == "şunlar: (2) ikinci")
check("a note opening with its bracketed number read as 8! keeps it",
      _split_note_marker("8! 4 Mayıs 1919 hareketi") == ("8", "4 Mayıs 1919 hareketi"))
check("and one whose closing bracket was lost", _split_note_marker("'1 Yi Ho Tuan hareketi")[0] == "1")
check("a note without one still has none", _split_note_marker("Bkz. Lenin, s. 34.")[0] is None)
check("a translator's note marked with a bullet is a starred note",
      _split_note_marker("• Hane anlamındaki Antik Yunanca sözcük.") == ("*", "Hane anlamındaki Antik Yunanca sözcük.")
      and _split_note_marker("•• (Fr.) Canlı resmi.")[0] == "**")
check("a note number whose 1 a scanner read as a letter",
      _split_note_marker("ı4 Navarinou Park web sayfası") == ("14", "Navarinou Park web sayfası")
      and _split_note_marker("1l Halk ve kitleler")[0] == "11")
check("but a word starting with I or l is not a number", _split_note_marker("Il Manifesto dergisi")[0] is None)
ch = _linked(["Yazar (2000) diyor1 ve oikos* alanında; durumda.3"],
             [("*", "Hane anlamındaki sözcük."), ("1", "Görüşme."), ("3", "USINA tartışması.")])
check("a starred note printed above the numbered ones still takes its reference",
      'href="#fn_ch_0001_0">*' in ch.paragraphs[0] and 'href="#fn_ch_0001_2">3' in ch.paragraphs[0])

# --- full stops that do not end a sentence ---------------------------------
from app.parsers.pdf_parser import _sentence_left_open  # noqa: E402

check("an ordinal before a lowercase line leaves the sentence open",
      _sentence_left_open("Kapitalizm, daha 20.", "yüzyıl başlarken"))
check("so does an abbreviation", _sentence_left_open("Ayrıntı için bkz.", "ikinci bölüm"))
check("a number ending a sentence before a capital does not",
      not _sentence_left_open("sayısı 2500.", "Bugün ise"))
check("nor a plain sentence end", not _sentence_left_open("bitti.", "sonra"))

def _large(text):
    return RawBlock(text=text, size=14.0, bbox=(60, 100, 300, 116), page_num=5,
                    page_width=420, page_height=595, font_name="Times")


check("a broken layer's noise set large is not a heading",
      all(_is_heading(_large(t), 10.0) is None for t in ("® @ ©", "·r:::::::::::: t;::::", "Ƿ;f :ǸǹǺ,:Ȝ:IS;:ǻ,Ǽ")))
check("nor a sentence picked up mid-way",
      _is_heading(_large("giriş ve çıkıştaki depresyon ağırlığı puanlamasını"), 10.0) is None)
check("but a title with a misread letter is",
      _is_heading(_large("ÖNSÖZ: 5TEVEN HOLL"), 10.0) is not None)
from app.parsers.pdf_parser import _normalize_page_scales  # noqa: E402


def _lines_page(page, size, pitch, n=20, height=12.0, odd=None):
    blocks = []
    for k in range(n):
        y = 30 + k * pitch
        sz = odd if (odd and k == 5) else size
        blocks.append(RawBlock(text="gövde metni satırı " * 3, size=sz, bbox=(10, y, 290, y + height),
                               page_num=page, page_width=306, page_height=523,
                               line_boxes=[(10, y, 290, y + height)]))
    return blocks


_scaled = {p: _lines_page(p, 10.8, 13.2) for p in range(8)}
_scaled[8] = _lines_page(8, 8.2, 13.2, odd=10.9)       # a scan page whose size the layer misreports
_scaled[9] = _lines_page(9, 8.2, 9.8, height=9.0)      # a notes page really set small
_normalize_page_scales(_scaled, 10.8)
check("a page on the book's pitch but reported small is set back to body size",
      all(b.size == 10.8 for b in _scaled[8]))
check("a page set small and close stays small", all(b.size == 8.2 for b in _scaled[9]))
from app.parsers.pdf_parser import _subheading_styles  # noqa: E402


def _sub_page(page, heading, next_text, head_y=200.0, size=7.8):
    return [
        RawBlock(text=heading, size=size, bbox=(10, head_y, 200, head_y + 10), page_num=page,
                 page_width=306, page_height=523, font_name="Sub", line_boxes=[(10, head_y, 200, head_y + 10)]),
        RawBlock(text=next_text, size=10.8, bbox=(10, head_y + 16, 296, head_y + 120), page_num=page,
                 page_width=306, page_height=523, font_name="Body",
                 line_boxes=[(10, head_y + 16 + 13 * k, 296, head_y + 28 + 13 * k) for k in range(8)]),
    ]


_prose = "Toplumsal hareketler üzerine olan tartışmalar kolektif bir talep etrafında örgütlenmiş etkinlikler üzerinde durur."
_sub_book = {p: _sub_page(p, h, _prose) for p, h in enumerate(
    ["Bir Meşruiyet Krizi mi?", "Meydanlardaki Müşterek Mekan", "Resmi Tahrifat Hamleleri", "Devleti Müşterekleştirmek mi?"])}
_sub_book.update({10 + k: _sub_page(10 + k, f"Sınıflı Toplum ve Devlet {21 + 6 * k}", _prose, head_y=12.0, size=8.4)
                  for k in range(4)})
_styles, _running_like = _subheading_styles(_sub_book, 10.8, lambda p: _sub_book[p])
check("a book's own sub-heading style is found from its repeats", (7.8, "Sub") in _styles)
check("a running head the furniture pass missed is not one", (8.4, "Sub") not in _styles and _running_like)
check("a section break set large is not a heading",
      _is_heading(RawBlock(text="* * *", size=13.0, bbox=(150, 400, 260, 415), page_num=8,
                           page_width=420, page_height=595, font_name="Times New Roman"), 10.0) is None)

if failures:
    print(f"\n{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("\nALL CHECKS PASSED")
