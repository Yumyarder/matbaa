"""
Core "Print-to-Digital" conversion engine — v2.

Rewritten against a real academic PDF (a Yordam Kitap Turkish translation)
and fixes three things that only show up once you look at real
InDesign-typeset output:

1. **Letter-tracking artifacts.** Small-caps headings ("BİRİNCİ BÖLÜM") are
   often typeset with real inter-glyph tracking, which naive text extraction
   misreads as word breaks ("B İ R İ N C İ B Ö L Ü M"). We reconstruct text
   from character bounding boxes and only insert a space where the visual
   gap actually indicates one, instead of trusting the byte stream's literal
   space characters.
2. **End-of-chapter endnotes.** Not every academic book puts footnotes at
   the bottom of each page — many collect them under a "Notlar" / "Notes"
   heading at the end of a chapter, as a numbered list. We detect that
   heading and switch into an endnote-collection mode, in addition to the
   original bottom-of-page/small-font heuristic (both can fire in the same
   document; whichever finds notes wins).
3. **Front matter & table of contents.** Half-title pages, translator's
   notes, colophon pages, and the "İçindekiler"/Contents page all need
   different treatment than body paragraphs — they're detected and styled
   distinctly rather than dumped in as regular text.

Pipeline
--------
1. Sample the document to find the dominant body font size (the mode).
2. Walk every page (skipping any the caller excluded), reconstructing each
   text block's characters into words using geometry, not literal codepoints.
3. Per page: check TOC-page and index/Fihrist-page patterns first — both
   bypass the normal paragraph pipeline entirely.
4. Per block, in priority order:
     a. Header/footer crop              -> discard
     b. Endnote heading ("Notlar")      -> switches to note-collection mode
     c. Collecting notes                -> stash as Footnote on current chapter
     d. Bottom-of-page small font       -> stash as Footnote (fallback mode)
     e. Eyebrow + heading pattern       -> starts a new chapter (buffers a
                                            one-line "BİRİNCİ BÖLÜM"-style
                                            label until the real title block)
     f. Ornamental divider / byline     -> `.ornamental-divider` / `.chapter-byline`
     g. Decorative symbol line          -> `.symbol-line`
     h. Academic blockquote             -> `.academic-blockquote`
     i. Regular paragraph               -> `<p>`, with `.text-muted`,
                                            `.text-italic`, `.text-center`
                                            applied from font metadata
5. After each chapter closes, footnote reference numbers inside its body
   text are linked to the matching endnote with a superscript anchor.
6. Silently auto-split any chapter that grows past ~70,000 characters.
"""

from __future__ import annotations

import html
import os
import sys
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

import fitz  # PyMuPDF

from difflib import SequenceMatcher

from app.parsers.outline_structure import reading_order as outline_reading_order, title_variants
from app.parsers.page_numbers import printed_pages
from app.parsers.toc_structure import (
    PART_JOIN,
    _reads_as_name,
    _is_toc_title,
    tidy_number,
    build_vocabulary,
    cut_title,
    parse_printed_toc,
    printed_page_offset,
    split_author,
    squash,
    vote_title,
)
from app.utils.language import DEFAULT_LANGUAGE, detect_language
from app.utils.text_quality import garbage_share
from app.utils.vocab_repair import build_vocabulary as build_word_counts, capitalised_forms, repair_text
from app.utils.text_cleaning import (
    clean_text,
    fix_broken_bracket_glyphs,
    is_mostly_punctuation_or_digits,
    is_symbol_line,
    looks_like_toc_line,
    repair_hyphenation,
    strip_dot_leaders,
)

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
# Header/footer cropping is proportional to the page's own height, not a
# fixed point value — a fixed 50pt is calibrated for a standard ~800pt-tall
# page, but a smaller physical trim size (e.g. a 537pt-tall compact
# paperback) can have its very first body line start at y≈29pt, which a
# fixed 50pt threshold would wrongly crop away as a "header" on every
# single page — silently deleting most of the book. The floors below keep
# behavior sane on unusually tiny custom page sizes.
HEADER_MARGIN_RATIO = 0.045
FOOTER_MARGIN_RATIO = 0.075
HEADER_MARGIN_FLOOR_PT = 15.0
FOOTER_MARGIN_FLOOR_PT = 25.0
FOOTNOTE_ZONE_RATIO = 0.30
FOOTNOTE_SIZE_DELTA = 1.2
HEADING_SIZE_DELTA = 2.0
MAX_CHAPTER_CHARS = 70_000
BLOCKQUOTE_MAX_WIDTH_RATIO = 0.62
BLOCKQUOTE_CENTER_TOLERANCE = 0.06
CENTER_TEXT_TOLERANCE = 0.045
CENTER_TEXT_MAX_WIDTH_RATIO = 0.85
INDEX_PAGE_DIGIT_RATIO = 0.55
INDEX_PAGE_MIN_CHECK_PROGRESS = 0.45
TOC_PAGE_LINE_RATIO = 0.35
TOC_PAGE_MIN_LINES = 4
# A contents page that sets its page numbers in their own column, rather
# than after a dot leader on the title's line — see
# _toc_page_number_column().
TOC_NUMBER_COLUMN_MIN_ENTRIES = 5
TOC_NUMBER_COLUMN_LINE_RATIO = 0.30
JUNK_PAGE_TEXT_MAX_CHARS = 800

HEADING_KEYWORDS = re.compile(
    r"^\s*(CHAPTER|BÖLÜM|PART|INTRODUCTION|GİRİŞ|PREFACE|ÖNSÖZ|CONCLUSION|"
    r"SONUÇ|APPENDIX|EK\b|EPILOGUE|PROLOGUE|SUNUŞ)\b",
    re.IGNORECASE,
)
ORDINAL_SECTION_LABEL = re.compile(
    r"^(BİRİNCİ|İKİNCİ|ÜÇÜNCÜ|DÖRDÜNCÜ|BEŞİNCİ|ALTINCI|YEDİNCİ|SEKİZİNCİ|"
    r"DOKUZUNCU|ONUNCU|FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH)\s+"
    r"(BÖLÜM|BÖLÜMÜ|KISIM|PART|CHAPTER)\.?\s*$",
    re.IGNORECASE,
)
BRACKET_EYEBROW = re.compile(r"^\[.{2,60}\]$")
NUMERIC_SECTION_LABEL = re.compile(r"^(BÖLÜM|PART|CHAPTER|KISIM)\s+\d{1,3}\.?\s*$", re.IGNORECASE)
# Turkish sets the part divider number-first — "1. BÖLÜM", and with OCR
# spacing "2 .  BÖLÜM" — which the label-first pattern above never matched.
# The dot is required: it is what separates a divider from an ordinary
# line that happens to start with a digit.
ORDINAL_NUMERIC_SECTION_LABEL = re.compile(r"^\d{1,3}\s*\.\s*(BÖLÜM|KISIM|PART|CHAPTER)\.?\s*$", re.IGNORECASE)

NOTE_SECTION_HEADING = re.compile(r"^(NOTLAR|DİPNOTLAR|NOTES|KAYNAKLAR|NOTES?\s+AND\s+REFERENCES)\s*$", re.IGNORECASE)

TOC_HEADING = re.compile(
    r"^[\s•\-\*\u2022\u2726\u2727\u25CF·]{0,12}(İÇİNDEKİLER|ICINDEKILER|CONTENTS|TABLE OF CONTENTS)"
    r"[\s•\-\*\u2022\u2726\u2727\u25CF·]{0,12}$",
    re.IGNORECASE,
)

MUTED_FONT_HINT = re.compile(r"light", re.IGNORECASE)
ITALIC_FONT_HINT = re.compile(r"italic|oblique|-it$|-it,|it-", re.IGNORECASE)
BOLD_FONT_HINT = re.compile(r"bold|black|semibold|heavy", re.IGNORECASE)

FLAG_ITALIC = 2
FLAG_BOLD = 16


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class RawBlock:
    text: str
    size: float
    bbox: tuple
    page_num: int
    page_width: float
    page_height: float
    bold: bool = False
    italic: bool = False
    muted: bool = False
    font_name: str = ""
    # (x0, y0, x1, y1) of each printed line, in order — the geometry a
    # quotation, an attribution or a paragraph gap is recognised by.
    line_boxes: List[tuple] = field(default_factory=list)


@dataclass
class Footnote:
    id: str
    marker: str
    text: str


@dataclass
class Chapter:
    id: str
    index: int
    title: str
    kind: str = "chapter"       # "chapter" | "frontmatter" | "toc" | "index" | "image"
    eyebrow: Optional[str] = None
    paragraphs: List[str] = field(default_factory=list)
    footnotes: List[Footnote] = field(default_factory=list)
    char_count: int = 0
    is_split_continuation: bool = False
    image_base64: Optional[str] = None
    # In-chapter figures from the PDF Editor's "Görsel" region marker — a
    # {"id", "base64"} pair per figure, referenced from `paragraphs` by
    # `<img src="images/{id}.png">`. Distinct from image_base64 above,
    # which stands in for an entire chapter (a whole page marked Görsel in
    # Page Review); these sit alongside ordinary text within one.
    images: List[dict] = field(default_factory=list)
    # The author line under a section title ("Steven Holl"), kept apart from
    # the title so the title can be matched and the byline styled.
    byline: Optional[str] = None
    # Where this chapter sits in the book's printed contents: the enclosing
    # labels / parent entries, outermost first ("1. BÖLÜM").
    toc_path: List[str] = field(default_factory=list)
    # How the book sets this chapter's opening, measured off its page — see
    # _measure_opener.
    opener: Optional[dict] = None


@dataclass
class ConversionResult:
    chapters: List[Chapter]
    warnings: List[dict]
    detected_title: str
    detected_author: str
    cover_image_base64: Optional[str] = None
    chapter_warnings: List[dict] = field(default_factory=list)
    detected_language: str = DEFAULT_LANGUAGE
    # "spaced" when the book separates paragraphs with white space rather
    # than a first-line indent — see _build_style_profile.
    paragraph_style: str = "indented"
    # What the engine decided about this book, for its report
    # (app.diagnosis): where the structure came from and what was repaired.
    decisions: Dict = field(default_factory=dict)


@dataclass
class PagePreview:
    index: int
    text_snippet: str
    thumbnail_base64: str
    likely_junk: bool
    suggested_mode: str = "text"  # "text" | "image" | "toc" | "exclude"


# ---------------------------------------------------------------------------
# Step 0: page thumbnails for the "remove junk pages" review step
# ---------------------------------------------------------------------------
# A back cover printed at the book's own size: its blurb, its price and the
# barcode with the ISBN under it. Read as text, the blurb ended the last
# chapter and the barcode's bars ("111111111111") opened a chapter of their
# own. Only the book's last pages are judged so: the imprint page at the
# front carries an ISBN too, and is text.
BACK_COVER_PAGES = 2
_BACK_COVER_ISBN = re.compile(r"\bISBN\b|\b97[89][\d\s-]{9,15}\d\b|\b9\s?7[89]\d{3}\s?\d{3,}")
_BACK_COVER_MARKS = re.compile(r"\bKDV\b|\b\d+(?:[.,]\d{2})?\s?(?:TL|₺)\b|1{8,}|\bwww\.[\w-]+\.com", re.I)


def _reads_as_back_cover(text: str) -> bool:
    """A page with an ISBN and one more mark of a back cover: a price, a
    tax note, the barcode's bars, the publisher's web address."""
    return bool(_BACK_COVER_ISBN.search(text)) and bool(_BACK_COVER_MARKS.search(text))


def get_pdf_page_previews(pdf_path: str, max_pages: Optional[int] = None) -> List[PagePreview]:
    import base64

    doc = fitz.open(pdf_path)
    out: List[PagePreview] = []
    n = doc.page_count if max_pages is None else min(max_pages, doc.page_count)

    # Read every page's text first, so each page can be judged against how
    # much text this *particular* book normally puts on a page. Whether a
    # page is "really an image page" is not answerable from that page alone
    # — see _typical_page_text_volume().
    page_texts = [doc[i].get_text("text").strip() for i in range(n)]
    typical_chars = _typical_page_text_volume(page_texts)
    # Whether each page's words were typeset or recovered by OCR — see
    # _page_is_carried_by_its_image, which judges a read photograph by a
    # different rule than a page that shipped with its own text.
    ocr_pages = [_page_text_is_ocr(doc[i]) for i in range(n)]

    # Likewise, whether a full-page image means "this page is a picture"
    # is a property of the whole document, not of one page — see
    # _raster_is_scan_substrate().
    image_ratios = [_largest_image_area_ratio(doc[i]) for i in range(n)]
    scan_substrate = _raster_is_scan_substrate(page_texts, image_ratios, typical_chars)

    # A page cut to a different size from the book's own pages is a cover, a
    # back cover or a fold-out — a designed object that should be shown as
    # printed. Reading it as text is what put a back-cover blurb and a
    # barcode at the end of the last chapter.
    book_w, book_h, size_tolerance = _book_page_size([(doc[i].rect.width, doc[i].rect.height) for i in range(n)])

    for i in range(n):
        page = doc[i]
        text = page_texts[i]
        pix = page.get_pixmap(matrix=fitz.Matrix(0.32, 0.32))
        b64 = base64.b64encode(pix.tobytes("png")).decode("ascii")
        mode = _suggest_page_mode(
            text, image_ratios[i], typical_chars, scan_substrate, ocr_pages[i]
        )
        off_size = book_w and (
            abs(page.rect.width - book_w) > book_w * size_tolerance
            or abs(page.rect.height - book_h) > book_h * size_tolerance
        )
        if off_size and mode == "text":
            mode = "image"
        if mode == "text" and i >= n - BACK_COVER_PAGES and _reads_as_back_cover(text):
            mode = "image"
        out.append(
            PagePreview(
                index=i,
                text_snippet=text[:220],
                thumbnail_base64=b64,
                likely_junk=_looks_like_junk_page(text, i),
                suggested_mode=mode,
            )
        )
    doc.close()
    # A contents page whose numbers the scanner misread ("ıs", "2S") scores
    # nothing on its own; when the page after it is contents and it opens
    # under the contents heading, it is the first page of the same list —
    # without it the plan began halfway through the book.
    for i in range(1, len(out)):
        prev = out[i - 1]
        if out[i].suggested_mode == "toc" and prev.suggested_mode == "text":
            first = next((ln for ln in page_texts[i - 1].split("\n") if ln.strip()), "")
            if _is_toc_title(first):
                prev.suggested_mode = "toc"
    return out


def _book_page_size(sizes: List[Tuple[float, float]]) -> Tuple[float, float, float]:
    """The book's own page (the median trim) and how far a page may differ
    from it, as a share, before it is a cover or a fold-out.

    A typeset book's pages are one size and 3% is the bound. A scan's trim
    drifts page by page with the scanner — one periodical runs from 400 to
    415 pt wide — and measured against the narrowest size (the commonest
    one there) a full text page at 415 pt was 3.75% off and shown as a
    picture, its words lost. Against the median, with the bound widened to
    three times the drift three quarters of the book's pages stay within,
    the drift is the book's own and a page cut to another size still stands
    out. (Three quarters, not nine tenths: a book with a tenth of its pages
    turned sideways, tables, would otherwise widen the bound past its own
    cover.)"""
    if not sizes:
        return 0.0, 0.0, OFF_SIZE_PAGE_TOLERANCE
    widths = sorted(w for w, _ in sizes)
    heights = sorted(h for _, h in sizes)
    w, h = widths[len(widths) // 2], heights[len(heights) // 2]
    if len(sizes) < 5 or not w or not h:
        return w, h, OFF_SIZE_PAGE_TOLERANCE
    drift = sorted(max(abs(pw - w) / w, abs(ph - h) / h) for pw, ph in sizes)
    usual = drift[int(len(drift) * 0.75) - 1]
    return w, h, max(OFF_SIZE_PAGE_TOLERANCE, 3 * usual)


def _typical_page_text_volume(page_texts: List[str]) -> float:
    """Median character count across the pages that carry any text at all.

    This is the reference point for "does this page's own text layer look
    like it's carrying the page's content, or like an incidental caption?".
    It has to be document-relative: a 9pt academic page holds several
    thousand characters, a large-print novel page a few hundred, and a
    fixed character threshold that suits one badly misjudges the other.

    Blank pages are excluded from the median so that a book padded with
    section-break blanks doesn't drag the reference down toward zero.
    """
    counts = sorted(len(t) for t in page_texts if len(t) >= MIN_CHARS_FOR_TEXT_BEARING_PAGE)
    if not counts:
        return 0.0
    return float(counts[len(counts) // 2])


def _largest_image_area_ratio(page: fitz.Page) -> float:
    """Fraction of the page's area covered by its largest embedded image —
    used to tell a full-bleed cover/photo page apart from a text page that
    just happens to have a small decorative image or two."""
    try:
        infos = page.get_image_info()
    except Exception:  # noqa: BLE001
        return 0.0
    page_area = page.rect.width * page.rect.height
    if page_area <= 0:
        return 0.0
    best = 0.0
    for info in infos:
        bbox = info.get("bbox")
        if not bbox:
            continue
        w = max(0.0, bbox[2] - bbox[0])
        h = max(0.0, bbox[3] - bbox[1])
        best = max(best, (w * h) / page_area)
    return best


IMAGE_DOMINANT_AREA_RATIO = 0.45
# OCR writes its text in a font with no glyphs in it — Tesseract's own name
# for it, and the one PyMuPDF reports. A page set in it had no text of its
# own: it is a photograph of a page that has been read, which is a
# different thing from a page that was typeset with text.
# Set to a list to record which code path closes each paragraph (diagnostics).
CLOSE_TRACE: Optional[list] = None
OCR_FONT_NAME_HINT = re.compile(r"glyphless", re.IGNORECASE)
OCR_EDGE_BAR = re.compile(r"^[|¦]+\s*|\s*[|¦]+$")
# A raised, bracketed note reference ("hareketi[8]") as OCR reads it: the
# brackets come back as "!", "|", "(" or "{" and the digits at full size,
# so neither the size nor the font finds it ("hareketi!8! sırasında").
OCR_BRACKETED_REF = re.compile(
    r"(?:(?<=[^\W\d_])|(?<=[.,;:?\"'’”)]))[!|\[{(](\d{1,3})[!|\]})](?=[\s.,;:?\"'’”)]|$)"
    # after a sentence's closing quote the opening bracket is often lost: ".”5!"
    r"|(?<=[.,;:?\"'’”)])(\d{1,3})[!|\]})](?=[\s.,;:?\"'’”)]|$)"
)
# How much of a read line may be recognition noise before it stops counting
# as a heading — see _ocr_text_reads_as_words.
OCR_HEADING_NOISE_MAX_SHARE = 0.25
# How far a page's trim may differ from the book's usual page before it is
# treated as a cover or fold-out rather than a text page.
OFF_SIZE_PAGE_TOLERANCE = 0.03
# A page whose own text layer is thinner than this share of the book's
# typical page — or below the absolute floor, for books with very little
# text anywhere — isn't carrying its content as text, whatever is drawn
# behind it.
IMAGE_PAGE_TEXT_SHARE_MAX = 0.20
IMAGE_PAGE_TEXT_FLOOR_CHARS = 120
MIN_CHARS_FOR_TEXT_BEARING_PAGE = 40
# Share of the book that has to look like "full-page raster with a full
# page's worth of live text on top of it" before the raster is read as the
# scanner's substrate rather than as page content. Measured across the
# corpus the two regimes are nowhere near each other — a scanned book sits
# at ~0.93 of its pages, a born-digital book with a photographic cover at
# 0.00 — so the exact cut matters much less than having one.
SCAN_SUBSTRATE_PAGE_SHARE = 0.50
# What a line off a page that sets no prose is marked as. It is not body
# text and must not be read as body text: a caption, an index entry, an
# imprint line. Two things read the mark — the stylesheet, which sets these
# smaller and unindented, and the readiness checks, whose "paragraph starts
# in lower case" test assumes running prose and is simply false about a
# list.
PAGE_ASIDE_CLASS = "page-aside"


def _raster_is_scan_substrate(
    page_texts: List[str], image_ratios: List[float], typical_page_chars: float
) -> bool:
    """Is this book's full-page imagery the scan it was made from, rather
    than pictures the book contains?

    `_text_layer_is_incidental()` already stops a scanned book from being
    classified as a stack of photographs wholesale, but it leaves the
    short pages behind: a chapter opener, a title page, a contents page or
    the last page of a chapter carries a few lines by design, so on a
    scanned book — where *every* page has a full-page raster under it —
    those pages still fail the area test and their text is thrown away.
    The thinness is real; the inference from it is not.

    The way out is that image-dominance is not a page-level fact here. A
    full-page image with a page's worth of live text on top of it is a
    scanner underlay, and a book stored that way is stored that way
    throughout. So count the pages that look like that: if they are most
    of the book, the raster is the substrate, it says nothing about any
    individual page, and "this page is a picture" has to be established
    some other way.

    A born-digital book fails this test decisively — its one or two
    image-dominant pages are the cover and the plates, and those carry no
    text — so the area test keeps its full force exactly where it works.
    """
    if not page_texts:
        return False
    substrate_like = sum(
        1
        for text, ratio in zip(page_texts, image_ratios)
        if ratio >= IMAGE_DOMINANT_AREA_RATIO
        and not _text_layer_is_incidental(text, typical_page_chars)
    )
    return substrate_like / len(page_texts) >= SCAN_SUBSTRATE_PAGE_SHARE


def _text_layer_is_incidental(page_text: str, typical_page_chars: float) -> bool:
    """Is this page's text layer too thin to be what the page is actually
    saying?

    This exists because "the largest image covers most of the page" is, on
    its own, a badly broken test for "this is a picture page". Every page of
    a scanner-OCR PDF has a full-page raster underlay behind the recognised
    text — Acrobat's ClearScan does exactly this — so area alone classifies
    an entire readable book as a stack of photographs and throws away all of
    its text while reporting success.

    Area is kept as a necessary condition, but the deciding question is
    whether the page's own text layer is already carrying the content. A
    genuine full-bleed plate has no text or a one-line caption; an OCR'd
    body page has a page's worth. Comparing against this book's own median
    page keeps that judgement independent of type size and trim.
    """
    n = len(page_text)
    threshold = max(IMAGE_PAGE_TEXT_FLOOR_CHARS, typical_page_chars * IMAGE_PAGE_TEXT_SHARE_MAX)
    return n < threshold


def _page_text_is_ocr(page: fitz.Page) -> bool:
    """Was this page's text read off the picture rather than typeset?"""
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                if span.get("text", "").strip():
                    return bool(OCR_FONT_NAME_HINT.search(span.get("font", "") or ""))
    return False


def _page_is_carried_by_its_image(
    page_text: str,
    typical_page_chars: float,
    raster_is_scan_substrate: bool,
    text_is_ocr: bool = False,
) -> bool:
    """Given that a large image covers the page, is the image what the page
    is actually saying?

    On a born-digital book the answer is `_text_layer_is_incidental()`:
    the image is there because someone placed it, so a thin text layer
    over it is a caption on a plate.

    On a scanned book the raster is under every page and means nothing
    (`_raster_is_scan_substrate()`), so a thin text layer is just a short
    page and the only thing that still argues for a picture is text the
    OCR could not find at all. Being stricter costs at worst a plate
    rendered as its own few lines of caption; being looser costs the text
    of every chapter opener in the book.
    """
    if raster_is_scan_substrate:
        if text_is_ocr:
            # A page that was read by OCR has no typesetting to speak for
            # it: everything about it is picture except the words that were
            # recovered. So the ordinary "is this text layer carrying the
            # page?" test applies — a cover, a half-title, a plate comes
            # back as a picture, which is what it is. This is deliberately
            # not applied to a book that shipped with its own OCR layer:
            # there a short page is a part title or the end of a chapter,
            # and calling it a picture would take its words out of the book.
            return _text_layer_is_incidental(page_text, typical_page_chars)
        return len(page_text) < MIN_CHARS_FOR_TEXT_BEARING_PAGE
    return _text_layer_is_incidental(page_text, typical_page_chars)


# ---------------------------------------------------------------------------
# Automatic figure detection
# ---------------------------------------------------------------------------
# A page that carries a figure alongside its body text used to lose the
# figure entirely: _extract_page_blocks only keeps type-0 (text) blocks, so
# every embedded raster on an ordinary page was dropped with no warning,
# while the only way to keep one was to hand-draw a Görsel region over it in
# the PDF Editor — per figure, per page, per book. Measured on the corpus
# specimen (Tenin Gözleri) that cost 14 of 14 real figures.
#
# These are the bounds that separate "a picture the book contains" from the
# three things that also arrive as embedded images: the scanner's full-page
# underlay, hairline rules and ornaments, and repeated furniture (logos,
# watermarks). Each bound is a separate failure mode, so they are kept as
# separate named tests rather than one score.
AUTO_FIGURE_MIN_AREA_RATIO = 0.03
AUTO_FIGURE_MAX_AREA_RATIO = 0.90
AUTO_FIGURE_BACKGROUND_AREA_RATIO = 0.95
AUTO_FIGURE_MIN_SIDE_PT = 24.0
AUTO_FIGURE_MIN_AREA_PT2 = 2500.0
AUTO_FIGURE_MAX_ASPECT = 12.0
AUTO_FIGURE_MIN_PIXELS = 10_000
AUTO_FIGURE_MIN_PIXEL_SIDE = 50
AUTO_FIGURE_MAX_PER_PAGE = 6
AUTO_FIGURE_MAX_PER_BOOK = 300
AUTO_FIGURE_TILE_GAP_PT = 2.0
AUTO_FIGURE_TILE_SHARED_EDGE = 0.90
AUTO_FIGURE_NESTED_SHARE = 0.90
# A person draws generously around a figure *and* its caption, so IoU
# against a hand-drawn region lands near 0.4 while containment is 1.0 —
# containment is what actually carries this test, IoU is the backstop.
AUTO_FIGURE_MANUAL_IOU = 0.30
AUTO_FIGURE_MANUAL_CONTAINMENT = 0.60
# A picture does not have paragraphs inside it. An image whose interior is
# carrying real prose is a background panel, a decorative frame or a page
# underlay — embedding it would be wrong twice over, because the region
# machinery also suppresses everything inside the bbox, so the prose would
# be deleted from the book to make room for a picture of itself. Measured:
# one such panel on Dazai p.3 swallowed 1132 characters. The bar is the same
# 40 characters the caption pre-pass already treats as "this region ate real
# text", which leaves room for a figure's own axis labels and callouts.
AUTO_FIGURE_MAX_INTERIOR_CHARS = 40
# Auto figures render at ~144dpi; a hand-drawn region stays at 3.0 because
# it is an explicit human choice about something that matters.
AUTO_FIGURE_RENDER_SCALE = 2.0


@dataclass
class AutoFigureProfile:
    """Document-level facts about imagery that no single page can establish.

    Both members answer questions that are meaningless page-locally: whether
    a full-page raster is the scanner's substrate is a property of how the
    book was made, and whether an image is furniture is a property of how
    often it recurs — the same repetition-not-position principle
    _detect_running_elements() uses for running heads.
    """
    scan_substrate: bool = False
    repeated_digests: Set[bytes] = field(default_factory=set)
    enabled: bool = True


def _rect_area(bbox) -> float:
    return max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])


def _rect_intersection_area(a, b) -> float:
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0.0, min(a[3], b[3]) - max(a[1], b[1])
    )


def _rect_iou(a, b) -> float:
    inter = _rect_intersection_area(a, b)
    union = _rect_area(a) + _rect_area(b) - inter
    return inter / union if union > 0 else 0.0


def _page_image_infos(page: fitz.Page) -> List[dict]:
    try:
        return page.get_image_info(hashes=True, xrefs=True)
    except Exception:  # noqa: BLE001
        try:
            return page.get_image_info()
        except Exception:  # noqa: BLE001
            return []


def _build_auto_figure_profile(
    doc: fitz.Document, page_texts: List[str], enabled: bool = True
) -> AutoFigureProfile:
    """One sweep for the two whole-document questions, before any page is
    converted."""
    if not enabled:
        return AutoFigureProfile(enabled=False)
    ratios: List[float] = []
    digest_pages: Dict[bytes, Set[int]] = {}
    for page_num in range(doc.page_count):
        page = doc[page_num]
        page_area = page.rect.width * page.rect.height
        best = 0.0
        for info in _page_image_infos(page):
            bbox = info.get("bbox")
            if bbox and page_area > 0:
                best = max(best, _rect_area(bbox) / page_area)
            digest = info.get("digest")
            if digest:
                digest_pages.setdefault(digest, set()).add(page_num)
        ratios.append(best)
    typical = _typical_page_text_volume(page_texts)
    # Same shape of bar as RUNNING_ELEMENT_MIN_PAGES: three occurrences is a
    # low bar precisely because an exact image match essentially never
    # repeats by accident, while a chapter-opener ornament still clears it.
    repeat_bar = max(3, int(round(doc.page_count * 0.25)))
    return AutoFigureProfile(
        scan_substrate=_raster_is_scan_substrate(page_texts, ratios, typical),
        repeated_digests={d for d, pages in digest_pages.items() if len(pages) >= repeat_bar},
        enabled=True,
    )


def _merge_image_tiles(boxes: List[List[float]]) -> List[List[float]]:
    """Union rasters that are really one figure sliced into strips.

    InDesign and several scanner exports emit a single photograph as a band
    of adjacent tiles. Filtering before merging rejects every one of them as
    "too small" and the figure disappears whole, so the merge has to happen
    first.
    """
    merged = [list(b) for b in boxes]
    changed = True
    while changed:
        changed = False
        for i in range(len(merged)):
            for j in range(i + 1, len(merged)):
                a, b = merged[i], merged[j]
                # Touching (or overlapping) on one axis, and sharing most of
                # their extent on the other — a strip of the same figure.
                x_gap = max(a[0], b[0]) - min(a[2], b[2])
                y_gap = max(a[1], b[1]) - min(a[3], b[3])
                if x_gap > AUTO_FIGURE_TILE_GAP_PT or y_gap > AUTO_FIGURE_TILE_GAP_PT:
                    continue
                x_overlap = min(a[2], b[2]) - max(a[0], b[0])
                y_overlap = min(a[3], b[3]) - max(a[1], b[1])
                x_share = x_overlap / max(1e-6, min(a[2] - a[0], b[2] - b[0]))
                y_share = y_overlap / max(1e-6, min(a[3] - a[1], b[3] - b[1]))
                if max(x_share, y_share) < AUTO_FIGURE_TILE_SHARED_EDGE:
                    continue
                merged[i] = [
                    min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])
                ]
                merged.pop(j)
                changed = True
                break
            if changed:
                break
    return merged


def _auto_figure_regions(
    page: fitz.Page,
    page_num: int,
    profile: AutoFigureProfile,
    manual_regions: List[dict],
    excluded_regions: Optional[List[List[float]]],
    ocr_regions: List[dict],
    body_blocks: Optional[List["RawBlock"]] = None,
) -> List[dict]:
    """The figures this page actually contains, as synthetic image regions.

    Returned in the same shape the PDF Editor's hand-drawn Görsel regions
    use, so everything downstream — interior-text suppression, caption
    binding, reading-order flush, EPUB image packaging — is the code that
    already works, not a parallel path.
    """
    if not profile.enabled:
        return []
    page_area = page.rect.width * page.rect.height
    if page_area <= 0:
        return []

    keep: List[dict] = []
    for info in _page_image_infos(page):
        bbox = info.get("bbox")
        if not bbox or _rect_area(bbox) <= 0:
            continue
        ratio = _rect_area(bbox) / page_area
        # The scanner's underlay sits behind every page of a scanned book.
        # Embedding it would re-ship the whole page as a picture next to the
        # very text that was recognised off it.
        if profile.scan_substrate and ratio >= IMAGE_DOMINANT_AREA_RATIO:
            continue
        if ratio >= AUTO_FIGURE_BACKGROUND_AREA_RATIO:
            continue
        if info.get("digest") in profile.repeated_digests:
            continue
        px_w, px_h = info.get("width") or 0, info.get("height") or 0
        if px_w * px_h < AUTO_FIGURE_MIN_PIXELS:
            continue
        if min(px_w, px_h) < AUTO_FIGURE_MIN_PIXEL_SIDE:
            continue
        keep.append({"bbox": [float(v) for v in bbox]})

    boxes = _merge_image_tiles([k["bbox"] for k in keep])

    candidates: List[List[float]] = []
    for bbox in boxes:
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        ratio = _rect_area(bbox) / page_area
        if not (AUTO_FIGURE_MIN_AREA_RATIO <= ratio <= AUTO_FIGURE_MAX_AREA_RATIO):
            continue
        if min(w, h) < AUTO_FIGURE_MIN_SIDE_PT or _rect_area(bbox) < AUTO_FIGURE_MIN_AREA_PT2:
            continue
        if max(w, h) / max(1e-6, min(w, h)) > AUTO_FIGURE_MAX_ASPECT:
            continue
        if w >= page.rect.width * 0.98 and h >= page.rect.height * 0.98:
            continue
        candidates.append(bbox)

    # Largest first, so a figure already accepted swallows anything drawn
    # inside it rather than the other way round.
    candidates.sort(key=_rect_area, reverse=True)
    accepted: List[List[float]] = []
    for bbox in candidates:
        own = _rect_area(bbox)
        if any(_rect_intersection_area(bbox, kept) / own >= AUTO_FIGURE_NESTED_SHARE
               for kept in accepted):
            continue
        accepted.append(bbox)

    # Anything the person already spoke about is theirs, not ours: a
    # hand-drawn Görsel region, an area they excluded, or one they OCR'd.
    claimed = (
        [r["bbox"] for r in manual_regions]
        + list(excluded_regions or [])
        + [r["bbox"] for r in ocr_regions]
    )
    out: List[dict] = []
    for bbox in accepted:
        own = _rect_area(bbox)
        cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
        if any(
            _rect_iou(bbox, c) >= AUTO_FIGURE_MANUAL_IOU
            or (c[0] <= cx <= c[2] and c[1] <= cy <= c[3])
            or _rect_intersection_area(bbox, c) / own >= AUTO_FIGURE_MANUAL_CONTAINMENT
            for c in claimed
        ):
            continue
        if body_blocks:
            interior = sum(
                len(b.text.strip())
                for b in body_blocks
                if _block_center_in_region(b, [bbox])
            )
            if interior > AUTO_FIGURE_MAX_INTERIOR_CHARS:
                continue
        out.append({"page_index": page_num, "bbox": bbox, "_auto": True})

    out.sort(key=lambda r: r["bbox"][1])
    return out[:AUTO_FIGURE_MAX_PER_PAGE]


def _suggest_page_mode(
    text: str,
    image_area_ratio: float,
    typical_page_chars: float = 0.0,
    raster_is_scan_substrate: bool = False,
    text_is_ocr: bool = False,
) -> str:
    """Best-effort default for the Page Review screen, so most PDFs need
    little to no manual per-page adjustment: blank pages default to
    excluded, pages dominated by one large image default to "image" (a
    cover/photo page's incidental text, if any, is very often garbled OCR
    anyway — visual fidelity matters more there), pages that read like a
    table of contents default to "toc", everything else defaults to "text".
    This never touches the actual conversion pipeline — it's purely a
    starting point the person can still override for any page."""
    stripped = text.strip()
    if not stripped and image_area_ratio < 0.05:
        return "exclude"
    if _looks_like_junk_page(text, 0):
        return "exclude"
    if image_area_ratio >= IMAGE_DOMINANT_AREA_RATIO and _page_is_carried_by_its_image(
        stripped, typical_page_chars, raster_is_scan_substrate, text_is_ocr
    ):
        return "image"
    # A leader set as spaced dots comes back one dot to a line: 473 lines
    # on one contents page, 442 of them a lone ".", and no line the
    # contents tests could see as an entry.
    lines = [ln for ln in text.split("\n") if ln.strip() and not LEADER_ONLY_LINE.fullmatch(ln.strip())]
    if lines:
        toc_hits = sum(1 for ln in lines if looks_like_toc_line(clean_text(ln)))
        if toc_hits / len(lines) >= 0.3:
            return "toc"
        # a contents page that sets its page numbers in their own column
        # scores zero above, since no single line carries both
        if _toc_page_number_column(lines):
            return "toc"
    return "text"


LEADER_ONLY_LINE = re.compile(r"[.·…•\s]+")


def _looks_like_junk_page(text: str, page_index: int) -> bool:
    if not text.strip():
        return False
    lower = text.lower()
    has_url = bool(re.search(r"https?://|www\.|t\.me/|\.com\b|telegram", lower))
    is_short = len(text.strip()) < JUNK_PAGE_TEXT_MAX_CHARS
    if has_url and is_short:
        return True
    return False


# ---------------------------------------------------------------------------
# Step 1: dominant body font size
# ---------------------------------------------------------------------------
def _detect_body_font_size(doc: fitz.Document, sample_pages: int = 40) -> float:
    sizes: Counter = Counter()
    n = min(sample_pages, doc.page_count)
    for i in range(n):
        page = doc[i]
        d = page.get_text("dict")
        for block in d.get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    if not text:
                        continue
                    sizes[round(span["size"], 1)] += len(text)
    if not sizes:
        return 11.0
    return sizes.most_common(1)[0][0]


# ---------------------------------------------------------------------------
# Step 2: geometry-aware text reconstruction (fixes letter-tracking)
# ---------------------------------------------------------------------------
INSERTED_SPACE_FIT_EM = 0.02
# A space narrower than this share of the font's usual space width is not
# that font's space glyph. Measured: invented spaces reach 0.916 of it, and a
# real (if squeezed) one at 0.928 was the closest genuine case, so the cut
# sits between them.
INSERTED_SPACE_NARROWER = 0.92
SPACE_MODE_TOLERANCE = 0.02
SPACE_MODE_MIN_SHARE = 0.6
SPACE_MODE_MIN_COUNT = 30


def _modal_space_em(widths: List[float]) -> Optional[float]:
    """The width a font's real space glyph has, if the samples agree on one.

    A font's space is one glyph with one advance, so real spaces cluster
    tightly. If they do not — a PDF with no space glyphs at all, where every
    word break is a gap PyMuPDF filled in — there is no "real" width to
    compare against and nothing may be dropped.
    """
    if len(widths) < SPACE_MODE_MIN_COUNT:
        return None
    counts = Counter(round(w, 3) for w in widths)
    mode = counts.most_common(1)[0][0]
    near = sum(1 for w in widths if abs(w - mode) <= SPACE_MODE_TOLERANCE * max(mode, 1e-6) + 0.002)
    return mode if near / len(widths) >= SPACE_MODE_MIN_SHARE else None


def _space_profile(doc: fitz.Document) -> dict:
    """Per-font usual space width (in em) for this document, measured once."""
    cached = getattr(doc, "_matbaa_space_profile", None)
    if cached is not None:
        return cached
    per_font: Dict[str, List[float]] = {}
    for page in doc:
        for block in page.get_text("rawdict").get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    size = span.get("size") or 0
                    if size <= 0:
                        continue
                    for ch in span.get("chars", []):
                        if ch.get("c") == " " and ch.get("bbox"):
                            w = (ch["bbox"][2] - ch["bbox"][0]) / size
                            per_font.setdefault(span.get("font", ""), []).append(w)
    everything = [w for ws in per_font.values() for w in ws]
    profile = {
        "fonts": {f: _modal_space_em(ws) for f, ws in per_font.items()},
        "global": _modal_space_em(everything),
    }
    try:
        doc._matbaa_space_profile = profile
    except Exception:  # noqa: BLE001
        pass
    return profile


def _is_inserted_space(chars: List[dict], i: int, size: float, usual_em: Optional[float]) -> bool:
    """Is chars[i] a space PyMuPDF made up rather than one the PDF contains?

    On OCR'd (ClearScan-style) PDFs PyMuPDF inserts a space wherever two
    glyphs of one word sit a little apart, and the space it invents is sized
    to fill exactly that gap. A space glyph the PDF really contains has the
    font's own advance — measured on one book, 0.250 em in 10,773 of 10,784
    cases; other fonts have other values (Minion 0.227, Helvetica 0.278),
    which is why the usual width is learnt per document, not assumed. The
    invented ones were 0.156–0.229 em there and filled their gaps to the
    thousandth of a point: that is how "Maddesellik" reached the book as
    "Maddesel lik" while every PDF viewer showed it whole.

    So a space is dropped only when it is both narrower than the font's own
    space and exactly the size of its gap, and only with a letter or digit on
    both sides: next to punctuation ("- The", "Bayer ©") a real space can
    coincide by chance, and keeping a stray space there costs far less than
    gluing two words.
    """
    if not size or not usual_em:
        return False
    j = i - 1
    while j >= 0 and chars[j].get("c", "").isspace():
        j -= 1
    k = i + 1
    while k < len(chars) and chars[k].get("c", "").isspace():
        k += 1
    if j < 0 or k >= len(chars) or k - j != 2:
        return False
    prev_c, next_c = chars[j].get("c", ""), chars[k].get("c", "")
    if not (prev_c.isalnum() and next_c.isalnum()):
        return False
    # A lowercase letter followed by a capital is a word boundary in running
    # text ("ailesi Japonya"); the invented spaces sit the other way round
    # ("M imarlık") or between two lowercase letters.
    if prev_c.islower() and next_c.isupper():
        return False
    sb = chars[i]["bbox"]
    width = sb[2] - sb[0]
    if width >= usual_em * size * INSERTED_SPACE_NARROWER:
        return False
    gap = chars[k]["bbox"][0] - chars[j]["bbox"][2]
    return abs(gap - width) < INSERTED_SPACE_FIT_EM * size


def _reconstruct_chars(chars: Iterable[dict], size: float, usual_space_em: Optional[float] = None) -> str:
    """
    Rebuild a span's text from its character bounding boxes.

    IMPORTANT: this trusts literal space characters from the PDF stream —
    it never drops them. It only ever *adds* a synthetic space, and only
    when two non-space glyphs are positioned with a gap far too large to be
    normal kerning (i.e. the PDF omitted a space character entirely, which
    happens on some exports). Letter-tracked ALL-CAPS headings like
    "B İ R İ N C İ" are repaired separately, at the text level, by
    collapse_tracked_caps() in text_cleaning.py — that keeps this function
    safe for ordinary body text, which is where words were previously being
    merged together.
    """
    out = []
    prev_end_x: Optional[float] = None
    # Only for the rare "PDF stream has no space glyph at all" case.
    # Normal proportional inter-word gaps are well under this, so it will
    # not misfire on ordinary text.
    missing_space_gap = max(size * 0.9, 3.0)
    chars = [ch for ch in chars if ch.get("bbox")]

    for i, ch in enumerate(chars):
        c = ch.get("c", "")
        bbox = ch["bbox"]
        x0, x1 = bbox[0], bbox[2]

        if c.isspace():
            if _is_inserted_space(chars, i, size, usual_space_em):
                continue
            # Always keep a real space; just collapse doubled-up ones.
            if out and out[-1] != " ":
                out.append(" ")
            prev_end_x = x1
            continue

        if prev_end_x is not None:
            gap = x0 - prev_end_x
            if gap > missing_space_gap and out and out[-1] != " ":
                out.append(" ")

        out.append(c)
        prev_end_x = x1

    return "".join(out)


PARA_BREAK = "\x04"          # sentinel: a genuine new-paragraph start (indent jump)
SUP_START, SUP_END = "\x02", "\x03"  # sentinel: wraps an inline footnote marker
# Inline emphasis the book sets in another face: a word in italic or bold
# inside a line of roman. Carried through cleaning as sentinels like the
# footnote markers, and turned into <em>/<strong> only when HTML is written.
EM_START, EM_END = "\x0e", "\x0f"
STRONG_START, STRONG_END = "\x10", "\x11"
INLINE_MARKS = EM_START + EM_END + STRONG_START + STRONG_END
# Where a printed page begins (app/parsers/page_numbers.py): the page's
# number between two sentinels, written in private-use digits so that
# nothing reading the text for note numbers or years sees a number there.
# Turned into an EPUB pagebreak marker when HTML is written.
PAGE_START, PAGE_END = chr(0x12), chr(0x13)
_PAGE_DIGITS = "".join(chr(0xE000 + d) for d in range(10))
PAGE_MARK_RE = re.compile(re.escape(PAGE_START) + "([" + _PAGE_DIGITS + "]+)" + re.escape(PAGE_END))
# An OCR'd book reports no italic flag; its italic words come back in a
# face of their own, set a little larger than the roman around them.
OCR_EMPHASIS_SIZE_RATIO = (1.02, 1.2)


def _strip_marks(text: str) -> str:
    for mark in INLINE_MARKS:
        text = text.replace(mark, "")
    return text


def _with_page_mark(text: str, number: int, continuing: bool) -> Optional[str]:
    """`text`, the first a page sets, with the mark of the printed page it
    begins: at its start where it continues a paragraph, otherwise after its
    first word — a paragraph never starts or ends with one, so every rule
    that reads a paragraph's first or last letter reads it as before. None
    where there is no such place (a paragraph of one word)."""
    mark = PAGE_START + str(number).translate(str.maketrans("0123456789", _PAGE_DIGITS)) + PAGE_END
    if continuing:
        return mark + text
    space = re.search(r"\s", text)
    if not space:
        return None
    return text[:space.start()] + mark + text[space.start():]


def _pagebreak_html(match: "re.Match") -> str:
    n = match.group(1).translate(str.maketrans(_PAGE_DIGITS, "0123456789"))
    return f'<span epub:type="pagebreak" role="doc-pagebreak" id="page-{n}" aria-label="{n}"></span>'


def _span_emphasis(span: dict, main_font: str, main_size: float, main_flags: int) -> Optional[tuple]:
    """Which emphasis, if any, a run inside a line is set in."""
    font = span.get("font", "") or ""
    if font == main_font or not main_size:
        return None
    flags = span.get("flags", 0)
    italic = bool(flags & FLAG_ITALIC) or bool(ITALIC_FONT_HINT.search(font))
    bold = bool(flags & FLAG_BOLD) or bool(BOLD_FONT_HINT.search(font))
    main_italic = bool(main_flags & FLAG_ITALIC) or bool(ITALIC_FONT_HINT.search(main_font))
    main_bold = bool(main_flags & FLAG_BOLD) or bool(BOLD_FONT_HINT.search(main_font))
    if italic and not main_italic:
        return (EM_START, EM_END)
    if bold and not main_bold:
        return (STRONG_START, STRONG_END)
    if italic or bold or main_italic or main_bold:
        return None
    ratio = span.get("size", 0) / main_size
    if OCR_EMPHASIS_SIZE_RATIO[0] <= ratio <= OCR_EMPHASIS_SIZE_RATIO[1]:
        return (EM_START, EM_END)
    return None


def _is_trailing_note_number(span: dict, span_text: str, before: List[tuple], line: dict) -> bool:
    """A bare number closing a line, straight after the end of a sentence
    and set in a face of its own, is a note reference — OCR can report it
    at full size, so size alone does not find it."""
    if not re.fullmatch(r"\s*\d{1,3}\s*", span_text) or not before:
        return False
    spans = [sp for sp in line.get("spans", [])
             if any(c.get("c", " ").strip() for c in sp.get("chars", []))]
    if not spans or spans[-1] is not span:
        return False
    prev = spans[-2] if len(spans) > 1 else None
    if prev is None or prev.get("font") == span.get("font"):
        return False
    return bool(re.search(r"[.!?][\"'”’)]?\s*$", before[-1][0]))


def _wrap_mark(text: str, mark: tuple) -> str:
    core = text.strip()
    if not core or not any(c.isalpha() for c in core):
        return text
    lead = text[: len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()):]
    return f"{lead}{mark[0]}{core}{mark[1]}{trail}"
INDENT_JUMP_RATIO = 1.1      # line x0 must jump this many font-sizes to count as indent
SUPERSCRIPT_FLAG = 1
SUPERSCRIPT_SIZE_RATIO = 0.78  # a span this much smaller than body text, if it's
                                # a bare 1-3 digit number, is almost certainly an
                                # inline footnote reference marker, not real prose


def _looks_like_footnote_marker_span(span_text: str, span_size: float, flags: int, body_size: float) -> bool:
    t = span_text.strip()
    if not t or not t.isdigit() or len(t) > 3:
        return False
    if flags & SUPERSCRIPT_FLAG:
        return True
    if body_size and span_size <= body_size * SUPERSCRIPT_SIZE_RATIO:
        return True
    return False


def _same_visual_line(a, b) -> bool:
    """Do these two line boxes sit on the same printed line?"""
    overlap = min(a[3], b[3]) - max(a[1], b[1])
    shortest = min(a[3] - a[1], b[3] - b[1])
    return shortest > 0 and overlap / shortest >= 0.6


def _same_baseline(a: dict, b: dict) -> bool:
    """Do two extracted lines sit on one baseline? Where the spans carry no
    origin there is nothing to compare, and the boxes have to decide."""
    sa, sb = a.get("spans") or [], b.get("spans") or []
    if not sa or not sb or "origin" not in sa[0] or "origin" not in sb[0]:
        return True
    size = max(sa[0].get("size", 0) or 0, sb[0].get("size", 0) or 0, 1.0)
    return abs(sa[0]["origin"][1] - sb[0]["origin"][1]) <= max(2.0, 0.4 * size)


def _merge_baseline_fragments(lines: List[dict], body_size: float) -> List[dict]:
    """Rejoin one printed line that PyMuPDF handed back in several pieces.

    Justified text is set by stretching the spaces, and where a stretched
    gap gets wide enough PyMuPDF ends the "line" and starts another at the
    same baseline. Measured on a real page: lines 0 and 1 both report
    y0=145.93, and line 1 starts at x0=139.1 while line 0 ends at x1=141.5
    — one sentence, two records.

    Nothing downstream expects that. Every fragment after the first starts
    far to the right of the block's left margin, so the indent test reads
    it as a fresh indented paragraph and breaks the text there; since the
    break lands wherever the gap happened to stretch, it lands in front of
    whatever word follows — which is why a book about Newton appeared to
    start a new paragraph at every "Newton". The same bogus x0 values also
    outvote the real margin, so indent and justification detection were
    being decided on geometry that describes nothing on the page.

    Only fragments inside one block are considered, and only when they are
    horizontally contiguous, so a genuine second column — which PyMuPDF
    reports as its own block anyway — is not pulled in.
    """
    usable = [ln for ln in lines if ln.get("bbox")]
    if len(usable) < 2:
        return lines
    usable.sort(key=lambda ln: (ln["bbox"][1], ln["bbox"][0]))
    max_gap = max(body_size, 6.0)

    groups: List[dict] = []
    for ln in usable:
        bbox = ln["bbox"]
        for group in groups:
            # A fragment picks up where the one before it stopped. One that
            # starts back at the margin is the next line, however much the
            # boxes overlap: a scan reported boxes 150pt tall on a contents
            # page, and every entry from "Adım 1" to "Adım 10" became one line.
            if (_same_visual_line(group["bbox"], bbox)
                    and bbox[0] - group["bbox"][2] <= max_gap
                    and _same_baseline(group["lines"][0], ln)):
                group["lines"].append(ln)
                gb = group["bbox"]
                group["bbox"] = [
                    min(gb[0], bbox[0]), min(gb[1], bbox[1]),
                    max(gb[2], bbox[2]), max(gb[3], bbox[3]),
                ]
                break
        else:
            groups.append({"bbox": list(bbox), "lines": [ln]})

    if len(groups) == len(usable):
        return lines  # nothing was fragmented; hand back the original list

    merged: List[dict] = []
    for group in groups:
        if len(group["lines"]) == 1:
            merged.append(group["lines"][0])
            continue
        group["lines"].sort(key=lambda ln: ln["bbox"][0])
        merged.append({
            "bbox": group["bbox"],
            "spans": [s for ln in group["lines"] for s in ln.get("spans", [])],
        })
    merged.sort(key=lambda ln: (ln["bbox"][1], ln["bbox"][0]))
    return merged


PIECE_TOUCH_EM = 0.12


def _join_line_pieces(pieces: List[tuple]) -> str:
    """Join the text runs of one printed line, with a space only where the
    page has one.

    An OCR'd book can split a word into runs — its italic "y" was
    recognised as a separate run that overlaps the letters before it, so
    "duyarlı" came back as "du" + "yarlı". Pieces whose ink touches are one
    word; a space goes in only across a real gap, and never next to a
    space the text already carries.
    """
    out = ""
    prev_x1 = None
    for text, x0, x1, size in pieces:
        if out and not out[-1].isspace() and not text[:1].isspace():
            if prev_x1 is None or x0 - prev_x1 > size * PIECE_TOUCH_EM:
                out += " "
        out += text
        prev_x1 = x1
    return out


def _extract_page_blocks(page: fitz.Page, page_num: int, body_size: float) -> List[RawBlock]:
    d = page.get_text("rawdict")
    ph, pw = page.rect.height, page.rect.width
    space_profile = _space_profile(page.parent)
    out: List[RawBlock] = []
    for block in d.get("blocks", []):
        if block.get("type") != 0:
            continue
        lines = block.get("lines", [])
        if not lines:
            continue
        # Before anything reads a line's geometry, make each record be one
        # real printed line — see _merge_baseline_fragments.
        lines = _merge_baseline_fragments(lines, body_size)

        # First pass: reconstruct every line's text plus its left/right edge.
        line_records: List[dict] = []
        size_char_weights: Counter = Counter()
        bold_votes = 0
        italic_votes = 0
        muted_votes = 0
        span_count = 0
        font_names = []

        for line in lines:
            span_texts = []
            line_weights: Counter = Counter()
            for span in line.get("spans", []):
                n = sum(1 for c in span.get("chars", []) if c.get("c", " ").strip())
                line_weights[(span.get("font", "") or "", round(span.get("size", 0), 1), span.get("flags", 0))] += n
            main_font, main_size, main_flags = (
                line_weights.most_common(1)[0][0] if line_weights else ("", 0.0, 0)
            )
            ocr_line = bool(OCR_FONT_NAME_HINT.search(main_font or ""))
            for span in line.get("spans", []):
                chars = span.get("chars", [])
                span_size = span.get("size", 10)
                usual_em = space_profile["fonts"].get(span.get("font", "")) or space_profile["global"]
                span_text = _reconstruct_chars(chars, span_size, usual_em)
                if not span_text.strip():
                    continue
                # Weighted by character count, not one vote per span — a
                # 3-character decorative bullet run ("• • •") sitting in
                # the same block as a 20-character heading must not pull
                # the block's "size" down to a body-text-ish average; what
                # matters is the size of the text that's actually THERE.
                size_char_weights[round(span_size, 1)] += len(span_text.strip())
                span_count += 1
                font = span.get("font", "") or ""
                font_names.append(font)
                flags = span.get("flags", 0)
                if (flags & FLAG_BOLD) or BOLD_FONT_HINT.search(font):
                    bold_votes += 1
                if (flags & FLAG_ITALIC) or ITALIC_FONT_HINT.search(font):
                    italic_votes += 1
                if MUTED_FONT_HINT.search(font):
                    muted_votes += 1
                if _looks_like_footnote_marker_span(span_text, span_size, flags, body_size) or (
                    _is_trailing_note_number(span, span_text, span_texts, line)
                ):
                    span_text = f"{SUP_START}{span_text.strip()}{SUP_END}"
                else:
                    mark = _span_emphasis(span, main_font, main_size, main_flags)
                    if mark:
                        span_text = _wrap_mark(span_text, mark)
                inked = [c for c in chars if c.get("c", " ").strip()]
                span_texts.append((
                    span_text,
                    inked[0]["bbox"][0] if inked else span["bbox"][0],
                    inked[-1]["bbox"][2] if inked else span["bbox"][2],
                    span_size,
                ))

            if not span_texts:
                continue
            line_text = _join_line_pieces(span_texts).strip()
            if ocr_line:
                # a page edge or a table rule read as a vertical bar
                line_text = OCR_EDGE_BAR.sub("", line_text).strip()
                line_text = OCR_BRACKETED_REF.sub(lambda m: f"{SUP_START}{m.group(1) or m.group(2)}{SUP_END}", line_text)
            if not line_text:
                continue
            bbox = line.get("bbox", [0, 0, 0, 0])
            line_records.append({"x0": bbox[0], "x1": bbox[2], "y0": bbox[1], "y1": bbox[3], "text": line_text})

        if not line_records:
            continue

        # Second pass: decide, for each line after the first, whether it
        # starts a new paragraph. Two independent signals, either one is
        # enough on its own — but BOTH require a genuine geometric
        # consensus across the block (at least 3 lines AND a real
        # majority), or they're disabled entirely. A 2-line block (a
        # 2-line heading, a short label) has no meaningful "margin" at
        # all — treating a 50/50 split as a "majority" was exactly what
        # caused short headings to get shattered into one paragraph per
        # line.
        #
        #  (a) Indent jump — this line starts noticeably further right than
        #      the block's common left margin (a classic first-line indent).
        #
        #  (b) Justified shortfall — the *previous* line ends noticeably
        #      short of the block's common right margin (a deliberately
        #      short last line, not just outstretched to the column width
        #      like every other line in a justified paragraph), AND that
        #      previous line's text actually ends at a *sentence* boundary
        #      (only '.', '!', '?' — NOT ':' or ';', which are far too
        #      common mid-paragraph in enumerative academic prose), AND
        #      this line starts with a capital letter.
        x0s = [round(r["x0"]) for r in line_records]
        x1s = [round(r["x1"]) for r in line_records]
        indent_threshold = max(body_size * INDENT_JUMP_RATIO, 8.0)
        shortfall_threshold = max(body_size * 2.2, 14.0)
        MIN_CONSENSUS_LINES = 3

        body_left = None
        if len(x0s) >= MIN_CONSENSUS_LINES:
            candidate, count = Counter(x0s).most_common(1)[0]
            if count >= MIN_CONSENSUS_LINES and count / len(x0s) >= 0.5:
                body_left = candidate

        body_right = None
        if len(x1s) >= MIN_CONSENSUS_LINES:
            candidate, count = Counter(x1s).most_common(1)[0]
            if count >= MIN_CONSENSUS_LINES and count / len(x1s) >= 0.5:
                body_right = candidate

        parts: List[str] = [line_records[0]["text"]]
        for i in range(1, len(line_records)):
            prev, cur = line_records[i - 1], line_records[i]

            # A genuine new paragraph (however it's signaled) starts with a
            # capital letter — it's the start of a new sentence. A line
            # starting lowercase is essentially always a wrapped
            # continuation, most commonly right after a hyphenated
            # line-break ("gö-" / "türmekte"). Requiring this up front
            # stops minor x0 jitter near hyphenation points from being
            # misread as an indent and leaking a stray "-" into the text.
            starts_upper = _strip_marks(cur["text"])[:1].isupper()

            indent_jump = (
                starts_upper
                and body_left is not None
                and (cur["x0"] - body_left) > indent_threshold
            )

            justified_shortfall = (
                starts_upper
                and body_right is not None
                and (body_right - prev["x1"]) > shortfall_threshold
                and _looks_paragraph_complete(prev["text"])
            )

            is_new_paragraph = indent_jump or justified_shortfall
            parts.append(PARA_BREAK if is_new_paragraph else "\n")
            parts.append(cur["text"])

        raw_text = "".join(parts)
        if not raw_text.strip():
            continue

        # Safety net: a real paragraph block has very few true
        # paragraph-starts relative to its line count. If detection somehow
        # flagged an implausibly large share of lines (irregular
        # justification, hanging punctuation, OCR jitter...), trust none of
        # it rather than shattering the block into fragments.
        jump_count = raw_text.count(PARA_BREAK)
        line_count = raw_text.count("\n") + jump_count + 1
        if line_count > 2 and jump_count / line_count > 0.34:
            raw_text = raw_text.replace(PARA_BREAK, "\n")

        dominant_size = size_char_weights.most_common(1)[0][0] if size_char_weights else 0.0
        out.append(
            RawBlock(
                text=raw_text,
                size=round(dominant_size, 1),
                bbox=tuple(block["bbox"]),
                page_num=page_num,
                page_width=pw,
                page_height=ph,
                bold=(span_count > 0 and bold_votes / span_count > 0.5),
                italic=(span_count > 0 and italic_votes / span_count > 0.5),
                muted=(span_count > 0 and muted_votes / span_count > 0.4),
                font_name=font_names[0] if font_names else "",
                line_boxes=[(r["x0"], r["y0"], r["x1"], r["y1"]) for r in line_records],
            )
        )
    return _reading_order(out)


def _toc_line_records(doc: fitz.Document, pages: Iterable[int]) -> List[dict]:
    """The contents pages as plain printed lines, for toc_structure."""
    space_profile = _space_profile(doc)
    records: List[dict] = []
    for page_num in sorted(pages):
        page = doc[page_num]
        for block in page.get_text("rawdict").get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in _merge_baseline_fragments(block.get("lines", []), 10.0):
                text = ""
                spans = line.get("spans", [])
                for span in spans:
                    usual_em = space_profile["fonts"].get(span.get("font", "")) or space_profile["global"]
                    text += _reconstruct_chars(span.get("chars", []), span.get("size", 10), usual_em)
                text = clean_text(text)
                if not text:
                    continue
                # the span carrying the words, not a run of leader dots
                main = max(
                    spans,
                    key=lambda s: sum(1 for c in s.get("chars", []) if c.get("c", "").isalnum()),
                ) if spans else {}
                x0, y0, x1, y1 = line["bbox"]
                # A scan can report boxes several lines tall (40pt for 7pt
                # type), so every entry overlaps its neighbours and numbers
                # pair with the wrong titles. The baseline is still true.
                size = main.get("size", 0.0) or 0.0
                origin = main.get("origin")
                if size and origin and (y1 - y0) > 2.5 * size:
                    y0, y1 = origin[1] - size, origin[1]
                records.append({
                    "text": text, "x0": x0, "y0": y0, "x1": x1, "y1": y1,
                    "font": main.get("font", ""), "size": main.get("size", 0.0),
                    "page": page_num,
                })
    return records


FOLIO_BAND_RATIO = 0.12
_LEADING_NUMBER = re.compile(r"^\s*(\d{1,4})(?:\s|$)")
_TRAILING_NUMBER = re.compile(r"(?:^|\s)(\d{1,4})\s*$")


def _detect_folios(page_blocks: Dict[int, List[RawBlock]]) -> Dict[int, int]:
    """The page number printed on each page, where one can be read.

    A folio sits in the top or bottom margin, alone or at the outer end of
    the running head ("46 Newton'ın Principia'sı…"). Only the number is
    taken; the offset between these and PDF indices is settled by majority
    in toc_structure.printed_page_offset, so a stray note number or figure
    number in the margin cannot move it.
    """
    folios: Dict[int, int] = {}
    for page_num, blocks in page_blocks.items():
        found: List[int] = []
        for b in blocks:
            band = b.page_height * FOLIO_BAND_RATIO
            if not (b.bbox[1] < band or b.bbox[3] > b.page_height - band):
                continue
            text = CONTROL_CHARS_RE.sub(" ", b.text).strip()
            if len(text) > 90:
                continue
            m = _LEADING_NUMBER.match(text) or _TRAILING_NUMBER.search(text)
            if m:
                found.append(int(m.group(1)))
        if len(found) == 1:
            folios[page_num] = found[0]
    return folios


# ---------------------------------------------------------------------------
# Structure from the book's printed contents page
# ---------------------------------------------------------------------------
TOC_MIN_ENTRIES = 3
# The bookmarks are preferred to the printed contents page while they list at
# least this share of its entries.
OUTLINE_PREFERRED_SHARE = 0.7
# How far past its bookmarked page a chapter's first text may begin (a
# chapter opening on drawn or photographed pages).
ANCHOR_SEARCH_PAGES = 6
TOC_MIN_MATCHED_SHARE = 0.6
TOC_MAX_LATE_START_SHARE = 0.25
TOC_UNNUMBERED_REACH = 12
TOC_TITLE_MIN_SIZE_RATIO = 1.05
TOC_POSITIONAL_SIZE_RATIO = 1.15
TOC_POSITIONAL_TOP_SHARE = 0.45


@dataclass
class TocPlan:
    """What the printed contents page says about this book, resolved
    against the pages it points at.

    `roles` maps id(RawBlock) to what that block is: the title of entry k,
    a continuation line of that title, its byline, or a section label. The
    conversion loop starts chapters exactly at "title" blocks and nowhere
    else, so type size stops being the thing that decides structure.
    """
    active: bool = False
    entries: List[dict] = field(default_factory=list)
    roles: Dict[int, dict] = field(default_factory=dict)
    unmatched: List[str] = field(default_factory=list)
    source: str = "printed_toc"     # or "outline"
    sequential: bool = False        # entries found in order, page numbers unusable


def _block_plain(block: RawBlock) -> str:
    return _sanitize_plain_text(block.text)


def _strip_squashed_prefix(sq: str, prefix: str) -> Optional[str]:
    """Remove a (possibly misread) `prefix` from the start of `sq`."""
    if not prefix or len(sq) < max(2, len(prefix) - 3):
        return None
    if sq.startswith(prefix):
        return sq[len(prefix):]
    if len(prefix) < 4:
        return None
    best_k, best_r = None, 0.0
    for k in range(max(1, len(prefix) - 3), min(len(sq), len(prefix) + 3) + 1):
        r = SequenceMatcher(None, sq[:k], prefix).ratio()
        if r > best_r:
            best_k, best_r = k, r
    if best_r >= 0.78:
        return sq[best_k:]
    return None


def _squashed_match(block_sq: str, title_sq: str) -> Optional[int]:
    """Squashed characters of the title this block prints, or None."""
    if not block_sq or not title_sq:
        return None
    if len(title_sq) < 3 or len(block_sq) < 3:
        return len(title_sq) if block_sq == title_sq else None
    if block_sq == title_sq:
        return len(title_sq)
    if title_sq.startswith(block_sq) and len(block_sq) >= min(8, len(title_sq)):
        return len(block_sq)
    if block_sq.startswith(title_sq):
        return len(title_sq)
    n = min(len(block_sq), len(title_sq))
    if n >= 6 and SequenceMatcher(None, block_sq[:n], title_sq[:n]).ratio() >= 0.8:
        if len(block_sq) <= len(title_sq) + max(3, len(title_sq) // 4):
            return n
    return None


def _split_printed_prefix(text: str, prefix_sq: str) -> (str, str):
    """Split `text` where its squashed form has consumed a (possibly
    misread) squashed prefix: ("[Sunuş Yerine]", "Boris Hessen'in …")."""
    sq = squash(text)
    rest = _strip_squashed_prefix(sq, prefix_sq)
    if rest is None:
        return "", text
    return cut_title(text, len(sq) - len(rest))


def _toc_tree_html(plan: "TocPlan") -> List[str]:
    """The contents page as the book prints it: section labels over their
    entries, entries indented by depth, page numbers on the right."""
    out: List[str] = []
    shown: List[str] = []
    for k, e in enumerate(plan.entries):
        path = e["path"]
        depth = 0
        while depth < len(path) and depth < len(shown) and path[depth] == shown[depth]:
            depth += 1
        for d in range(depth, len(path)):
            out.append(
                f'<p class="toc-section-label toc-level-{d}">{html.escape(path[d])}</p>'
            )
        shown = list(path)
        title = e["title"] + (f", {e['byline']}" if e.get("byline") else "")
        page = f'<span class="toc-page">{e["printed_page"]}</span>' if e.get("printed_page") else ""
        out.append(
            f'<p class="toc-entry toc-level-{len(path)}" data-toc-entry="{k}">'
            f'<span class="toc-title">{html.escape(title)}</span>{page}</p>'
        )
    return out


def _link_toc_entries(toc_chapter: Optional["Chapter"], plan: "TocPlan",
                      existing: Optional[Set[str]] = None) -> None:
    """Make each contents entry a link to the chapter it names — one that is
    still in the book: a chapter that came out empty and was dropped would
    leave a link to a file the EPUB does not have."""
    if toc_chapter is None:
        return
    targets = {str(k): e.get("chapter_id") for k, e in enumerate(plan.entries)}

    def link(m: "re.Match") -> str:
        cid = targets.get(m.group(2))
        if not cid or (existing is not None and cid not in existing):
            return m.group(0)
        return (f'{m.group(1)}<span class="toc-title"><a href="{cid}.xhtml">'
                f'{m.group(3)}</a></span>')

    pattern = re.compile(
        r'(<p class="toc-entry[^"]*" data-toc-entry="(\d+)">)<span class="toc-title">(.*?)</span>'
    )
    toc_chapter.paragraphs = [pattern.sub(link, p) for p in toc_chapter.paragraphs]


def _looks_clean_label(text: str) -> bool:
    return not re.search(r"[•;|]|[^\w\s.:\-\[\]()'’]{2,}", text)


# a scanner's misread numeral ("vn." for "VII.") counts when "Bölüm" follows
_CHAPTER_NUM = (r"(?:[IVXLCDMivxlcdmıİl]{1,6}|\d{1,3}"
                r"|[^\W\d_]{1,4}(?=\.\s*(?:bölüm|bolum|kısım|kisim|chapter|part)\b))")
_CHAPTER_WORD = r"(?:bölüm|bolum|kısım|kisim|ayrım|kitap|chapter|part)"
# The label a chapter's own page prints over its title ("1. Bölüm",
# "Bölüm 3", "Chapter IV") where the contents page printed only "1." or
# nothing: it is the chapter's label, not the start of its title.
CHAPTER_LABEL_PREFIX = re.compile(
    rf"^\s*(?:{_CHAPTER_NUM}\s*[.)]?\s*{_CHAPTER_WORD}|{_CHAPTER_WORD}\s+{_CHAPTER_NUM})\b\s*[.:)\-–—]?\s*",
    re.IGNORECASE,
)


# Metadata a PDF tool wrote rather than the publisher: a file name, a
# word processor's own label, a placeholder.
JUNK_METADATA_TITLE = re.compile(
    r"^(untitled|microsoft word|adobe|document\d*|kitap\d*|book\d*)\b|\.(pdf|docx?|indd|qxd|tiff?)\b|^[\w-]+_[\w-]+$",
    re.IGNORECASE,
)
TITLE_SMALL_WORDS = {"ve", "ile", "veya", "ya", "da", "de", "ki", "mi", "için", "gibi",
                     "and", "or", "of", "the", "a", "an", "in", "on", "to", "for"}
TITLE_PAGE_MAX_WORDS = 60
TITLE_PAGE_SEARCH = 12
TRANSLATOR_LINE = re.compile(r"\b(türkçe|çevir|translat|hazırlay|editör|editor|derley|yayına haz)",
                             re.IGNORECASE)
HONORIFIC = re.compile(r"^(dr|prof|doç|av|op)\.?\s+", re.IGNORECASE)


def _name_like(text: str) -> bool:
    return bool(text) and _reads_as_name(HONORIFIC.sub("", " ".join(text.split())))


# Turkish plural, genitive and ablative endings: "Planları", "Savaşının",
# "Yeniden". A title is made of such words; a person's name almost never.
TITLE_WORD_ENDING = re.compile(r"^\w{4,}(lar|ler|ları|leri|nın|nin|nun|nün|dan|den|tan|ten)$", re.IGNORECASE)
CREDENTIAL = re.compile(r",?\s*\b(ph\.?\s?d|m\.?\s?d|msc|ma)\b\.?", re.IGNORECASE)


def _author_line(text: str) -> Optional[str]:
    """ "Jeffrey E. Young, Ph.D. • Janet S. Klosko, Ph.D." -> "Jeffrey E. Young & Janet S. Klosko";
    None unless every part reads as a person's name."""
    t = CREDENTIAL.sub("", " ".join(text.split()))
    parts = [x.strip(" ,.") for x in re.split(r"\s*[•·&;]\s*|\s+(?:ve|and|ile)\s+", t) if x.strip(" ,.")]
    if not 1 <= len(parts) <= 3:
        return None
    names = []
    for part in parts:
        bare = HONORIFIC.sub("", part)
        words = bare.split()
        if not (2 <= len(words) <= 4 and all(w[:1].isupper() for w in words) and any(c.islower() for c in bare)):
            return None
        if any("'" in w or "’" in w or TITLE_WORD_ENDING.search(w) for w in words):
            return None
        names.append(part)
    return " & ".join(names)


def _folded(text: str) -> str:
    t = unicodedata.normalize("NFKD", (text or "").casefold().replace("ı", "i"))
    return re.sub(r"[^a-z0-9]+", "", "".join(c for c in t if not unicodedata.combining(c)))


def turkish_title_case(text: str) -> str:
    """ "MÜŞTEREK MEKAN" -> "Müşterek Mekan", Turkish i rules kept."""
    if any(c.islower() for c in text):
        return text
    low = text.replace("I", "ı").replace("İ", "i").lower()
    words = low.split(" ")
    return " ".join(
        w if k and w in TITLE_SMALL_WORDS else w[:1].replace("i", "İ").replace("ı", "I").upper() + w[1:]
        for k, w in enumerate(words))


def _infer_title_and_author(page_blocks: Dict[int, List["RawBlock"]], body_size: float,
                            running: Optional["RunningElements"], skip: Set[int],
                            front_texts: Optional[List[str]] = None) -> "tuple[Optional[str], Optional[str]]":
    """The book's title and author as its title page prints them, for a PDF
    whose metadata says nothing. The title page is an early page of few
    words; its title is its largest line, trusted most when the running
    heads repeat it; its author is the line that reads as a person's name."""
    front = [p for p in sorted(page_blocks)[:TITLE_PAGE_SEARCH] if p not in skip]

    def plain(b: "RawBlock") -> str:
        return " ".join(_block_plain(b).split())

    # how often each line recurs across the front pages: an author's name is
    # printed on the cover, the title page and the imprint, a title's second
    # line only where the title is
    page_text = [_folded(t) for t in front_texts] if front_texts else \
        [_folded(" ".join(plain(b) for b in page_blocks[p])) for p in front]

    def pages_naming(text: str) -> int:
        key = _folded(text)
        return sum(1 for t in page_text if key and key in t)
    best = None
    for p in front:
        blocks = sorted((b for b in page_blocks[p] if plain(b)), key=lambda b: b.bbox[1])
        if not blocks or sum(len(plain(b).split()) for b in blocks) > TITLE_PAGE_MAX_WORDS:
            continue
        top = max(blocks, key=lambda b: b.size)
        if top.size < body_size * 1.2:
            continue
        # the title set over several lines in the same type
        k = blocks.index(top)
        lo = hi = k
        while lo > 0 and blocks[lo - 1].size >= 0.85 * top.size and not _author_line(plain(blocks[lo - 1])):
            lo -= 1
        while (hi + 1 < len(blocks) and blocks[hi + 1].size >= 0.85 * top.size
               and not _author_line(plain(blocks[hi + 1]))):
            hi += 1
        title_blocks = blocks[lo:hi + 1]
        title = re.sub(r"[*†]+$", "", " ".join(plain(b) for b in title_blocks)).strip()
        if len(title) < 3 or garbage_share(title) > 0.3:
            continue
        repeated = bool(running and running.is_running(top))
        names = []
        under_role = False
        for b in blocks:
            if b in title_blocks:
                under_role = False
                continue
            if TRANSLATOR_LINE.search(plain(b)):
                under_role = True
                continue
            name = _author_line(plain(b))
            # the names under "Çevirenler:" / "Editörler:" are not the author's
            if under_role:
                if name:
                    continue
                under_role = False
            if name and pages_naming(name.split(" & ")[0]) >= 2:
                names.append(name)
        score = (repeated, bool(names), top.size)
        if best is None or score > best[0]:
            best = (score, title, names[0] if names else None)
    if best is None:
        return None, None
    _, title, author = best
    return turkish_title_case(title), author


RUNNING_TITLE_SPLIT = re.compile(r"\s+[-–—|:]\s+")
RUNNING_TITLE_SHARE = 0.4        # printed on at least this share of the book's first pages
RUNNING_TITLE_PAGES = 40


def _title_from_running_head(page_blocks: Dict[int, List["RawBlock"]]) -> "tuple[Optional[str], Optional[str]]":
    """Title and author from a running head that prints both — "David Burns -
    Birlikte İyi Hissetmek 12" over every page. A PDF made from a word
    processor sets its title page in the body size, and the title page then
    has no largest line to read the title by; its running head says it
    plainly. The side that reads as a person's name is the author; where
    both do (a title in capitalised words reads as a name too), the left
    one, as "Author - Title" is how running heads and file names put it."""
    pages = sorted(page_blocks)[:RUNNING_TITLE_PAGES]
    counts: Counter = Counter()
    for p in pages:
        seen = set()
        for b in page_blocks[p]:
            band = b.page_height * FOLIO_BAND_RATIO
            if not (b.bbox[1] < band or b.bbox[3] > b.page_height - band):
                continue
            text = re.sub(r"^\s*\d+\s+|\s+\d+\s*$", "", " ".join(_block_plain(b).split()))
            if text and text not in seen:
                seen.add(text)
                counts[text] += 1
    for text, n in counts.most_common(5):
        if n < max(3, RUNNING_TITLE_SHARE * len(pages)):
            break
        parts = RUNNING_TITLE_SPLIT.split(text, maxsplit=1)
        if len(parts) != 2:
            continue
        left, right = (" ".join(x.split()) for x in parts)
        if _name_like(left):
            return right, left
        if _name_like(right):
            return left, right
    return None, None


def _respell_from_book(title: str, word_counts: Counter) -> str:
    """A title word the book never spells that way takes the book's own
    spelling: Turkish title case turns "PRINCIPIA" into "Prıncıpıa", and
    the text says "Principia"."""
    def fold(w: str) -> str:
        return w.replace("İ", "i").replace("I", "i").replace("ı", "i").lower()

    spelled: Dict[str, Counter] = {}
    for w, n in word_counts.items():
        if len(w) >= 4 and w[:1].isupper():
            spelled.setdefault(fold(w), Counter())[w] += n

    def fix(m: "re.Match") -> str:
        w = m.group(0)
        forms = spelled.get(fold(w)) if len(w) >= 4 else None
        if not forms:
            return w
        best, n = forms.most_common(1)[0]
        own = word_counts.get(w, 0)
        # the book's spelling where the title's is unattested, or far rarer
        # ("Prıncıpıa" twice, "Principia" 36 times)
        return best if best != w and (own == 0 or (n >= 5 and n >= 5 * own)) else w

    return re.sub(r"[^\W\d_]+", fix, title)


def _tidy_author(author: str, word_counts: Counter, front_texts: Optional[List[str]] = None) -> str:
    """An author as a cover prints it in running text: a title page's
    capitals ("STAVROS STAVRIDES ") set in title case, and a name Turkish
    casing would misspell ("Stavrıdes") spelled as the book does. A single
    word the book's front pages never print ("Atom", "mac") is the name of
    the computer or the tool that made the PDF, not of its author."""
    author = " ".join((author or "").split())
    if author and author != "Unknown" and len(HONORIFIC.sub("", author).split()) == 1 and front_texts is not None:
        if _folded(author) not in _folded(" ".join(front_texts)):
            return "Unknown"
    if author and author.isupper():
        author = turkish_title_case(author)
    return _respell_from_book(author, word_counts) if author else "Unknown"


def _choose_title_author(meta_title: str, meta_author: str,
                         inferred_title: Optional[str], inferred_author: Optional[str]) -> "tuple[str, str]":
    """Metadata where it is sound, the title page where it is not."""
    title, author = meta_title.strip(), meta_author.strip()
    # a publisher's tool that put each in the other's field, as the title
    # page shows
    if title and author and (
            (inferred_title and _folded(inferred_title) == _folded(author))
            or (inferred_author and _folded(inferred_author) == _folded(title))):
        title, author = author, title
    weak_title = (not title or JUNK_METADATA_TITLE.search(title) or title == title.lower()
                  or (inferred_title and _folded(inferred_title) == _folded(title)))
    if weak_title and inferred_title:
        title = inferred_title
    if (not author or not _name_like(author)) and inferred_author:
        author = inferred_author
    # a shop's catalogue number left on the title, a space before its colon
    title = re.sub(r"\s*[\(\[]\s*(?:ISBN[:\s]*)?[\d-]{10,17}\s*[\)\]]\s*$", "", title)
    title = re.sub(r"\s+([:;,])", r"\1", title).strip()
    # "Burkeman, Oliver" is how a catalogue sorts a name, not how a cover prints it
    m = re.fullmatch(r"([^\W\d_][\w'’-]+),\s*([^\W\d_][\w.'’ -]+)", author)
    if m and _name_like(f"{m.group(2)} {m.group(1)}"):
        author = f"{m.group(2)} {m.group(1)}"
    return title or "Untitled Book", author or "Unknown"


def _tidy_label(text: str) -> str:
    """ "2 . BÖLÜM" / "2.BÖLÜM" -> "2. BÖLÜM"; "[Sunuş Yerine" -> closed;
    a scanner's roman numeral set right ("iV. Bölüm" -> "IV. Bölüm")."""
    t = re.sub(r"\s+([.,:;])", r"\1", text.strip())
    t = re.sub(r"^([IVXLCDMivxlcdmıİl]{1,6})(?=\s*[.)]?(?:\s|$))", lambda m: tidy_number(m.group(1)), t)
    t = re.sub(r"(\d)\.(?=[^\W\d_])", r"\1. ", t)
    if t.startswith("[") and "]" not in t:
        t += "]"
    return t


def _column_edges(blocks: List[RawBlock], body_size: float) -> Optional[tuple]:
    """Left and right edge of a page's text column, from its body lines."""
    body = [
        b for b in blocks
        if abs(b.size - body_size) <= body_size * 0.15 and (b.bbox[2] - b.bbox[0]) > b.page_width * 0.4
    ]
    if not body:
        return None
    return min(b.bbox[0] for b in body), max(b.bbox[2] for b in body)


def _alignment(block: RawBlock, edges: tuple) -> str:
    left, right = edges
    width = right - left
    x0, x1 = block.bbox[0], block.bbox[2]
    if abs(x1 - right) <= width * 0.04 and x0 - left > width * 0.2:
        return "right"
    if abs((x0 + x1) / 2 - (left + right) / 2) <= width * 0.06 and x0 - left > width * 0.08:
        return "center"
    return "left"


def _scale(size: float, body_size: float) -> str:
    ratio = size / body_size if body_size else 1.0
    if ratio >= 1.5:
        return "large"
    if ratio >= 1.12:
        return "medium"
    return "small"


def _measure_opener(
    label_block: Optional[RawBlock],
    title_blocks: List[RawBlock],
    byline_block: Optional[RawBlock],
    page_body: List[RawBlock],
    body_size: float,
    fallback_edges: Optional[tuple],
) -> dict:
    """How the book sets a chapter's opening: where the label and title sit,
    how big they are against the body, and how much white space the page
    leaves before the text starts.

    Nothing here names a book: "right" means flush with this page's own
    text column, "large" means large against this book's own body size.
    """
    edges = _column_edges(page_body, body_size) or fallback_edges
    title = title_blocks[0]
    opener = {
        "title_align": _alignment(title, edges) if edges else "center",
        "title_scale": _scale(max(b.size for b in title_blocks), body_size),
        "label_align": None,
        "label_scale": None,
        # A section that starts below the previous one's text, on the same
        # page, rather than on a page of its own.
        "inline": any(
            b.bbox[3] <= title.bbox[1] and abs(b.size - body_size) <= body_size * 0.2
            and (b.bbox[2] - b.bbox[0]) > b.page_width * 0.4
            for b in page_body
        ),
        "drop": 0,
    }
    pitch = body_size * 1.5

    def gap_class(gap: float) -> int:
        return 3 if gap > pitch * 6 else 2 if gap > pitch * 2 else 1

    opener["label_gap"] = 0
    if label_block is not None and edges:
        opener["label_align"] = _alignment(label_block, edges)
        opener["label_scale"] = _scale(label_block.size, body_size)
        if label_block is not title and label_block.page_num == title.page_num:
            opener["label_gap"] = gap_class(title.bbox[1] - label_block.bbox[3])
    last = byline_block or title_blocks[-1]
    below = [
        b for b in page_body
        if b.bbox[1] > last.bbox[3] and abs(b.size - body_size) <= body_size * 0.2
    ]
    if below:
        opener["drop"] = gap_class(min(b.bbox[1] for b in below) - last.bbox[3])
    return opener


def _plan_from_printed_toc(
    doc: fitz.Document,
    toc_pages: Set[int],
    page_blocks: Dict[int, List[RawBlock]],
    body_blocks_of,
    body_size: float,
) -> TocPlan:
    plan = TocPlan()
    if not toc_pages:
        return plan
    first = min(toc_pages)
    entries = parse_printed_toc(_toc_line_records(doc, toc_pages), doc[first].rect.width)
    numbered = [e for e in entries if e.printed_page is not None and not e.is_label]
    if len(numbered) < TOC_MIN_ENTRIES:
        return plan
    offset = printed_page_offset(_detect_folios(page_blocks))
    # A book re-set from another edition prints the old edition's contents
    # page and no folios of its own: the numbers lead nowhere, but the
    # entries are still the book's headings, in order. Each is then looked
    # for after the one before it, and only a block no longer than the
    # entry itself can be it — a sentence that mentions a title is not one.
    sequential = offset is None
    plan.sequential = sequential
    cursor = 0

    vocab = build_vocabulary([b.text for blocks in page_blocks.values() for b in blocks])
    # A non-label entry with entries nested under it only names a group.
    is_parent = [
        (not e.is_label) and any(
            tuple(o.path[: len(e.path) + 1]) == tuple(e.path + [e.title]) for o in entries[k + 1:]
        )
        for k, e in enumerate(entries)
    ]

    used: Set[int] = set()
    found_labels: Dict[str, str] = {}
    min_page = max(toc_pages) + 1

    def container_display(name: str) -> str:
        # How the label is printed on the section's own page is the better
        # spelling ("1. BÖLÜM" where the contents page reads "l.BÖLÜM") —
        # unless the scanner made a mess of that one instead.
        printed = found_labels.get(name)
        if printed and _looks_clean_label(printed) and (
            squash(printed) == squash(name)
            or SequenceMatcher(None, squash(printed), squash(name)).ratio() >= 0.8
        ):
            return _tidy_label(printed)
        return _tidy_label(vote_title(name, printed, vocab))

    def free_blocks(p: int) -> List[RawBlock]:
        return sorted(
            (b for b in body_blocks_of(p) if id(b) not in used),
            key=lambda b: b.bbox[1],
        )

    for k, entry in enumerate(entries):
        if entry.is_label or is_parent[k]:
            continue
        # An entry whose number the scanner misread ("2ı", "2S") is still
        # the next heading after the one before it: it is looked for a few
        # pages on from there, and is no loss to the plan if not found.
        unnumbered = entry.printed_page is None
        head, author = split_author(entry.title)
        if sequential or unnumbered:
            target = None
            start = max(cursor, min_page)
            pages = [p for p in sorted(page_blocks)
                     if p >= start and (not unnumbered or p <= start + TOC_UNNUMBERED_REACH)]
        else:
            target = entry.printed_page - offset
            pages = [p for p in (target, target + 1, target - 1) if p in page_blocks and p >= min_page]
        title_sq = squash(entry.title)
        head_sq = squash(head)
        hit = None
        for p in pages:
            blocks = free_blocks(p)
            for bi, b in enumerate(blocks):
                sq = squash(_block_plain(b))
                stripped: List[str] = []
                for c in entry.path:
                    rem = _strip_squashed_prefix(sq, squash(c))
                    if rem is not None:
                        sq = rem
                        stripped.append(c)
                printed_label = None
                unlabelled = sq
                lab = CHAPTER_LABEL_PREFIX.match(_block_plain(b))
                if lab:
                    rem = _strip_squashed_prefix(sq, squash(lab.group(0)))
                    if rem:
                        sq, printed_label = rem, lab.group(0).strip(" .:)-–—")
                if not sq:
                    continue
                short_enough = len(sq) <= len(title_sq) * 1.3 + 4
                heading_like = b.size >= body_size * TOC_TITLE_MIN_SIZE_RATIO
                if not (short_enough or heading_like) or (target is None and not short_enough):
                    continue
                n = _squashed_match(sq, title_sq)
                if n is None and head_sq != title_sq:
                    n = _squashed_match(sq, head_sq)
                if n is None and printed_label:
                    # the entry itself begins with the label ("Chapter 3 Getting…")
                    sq, printed_label = unlabelled, None
                    n = _squashed_match(sq, title_sq)
                if n is not None:
                    hit = (p, blocks, bi, n, stripped, printed_label)
                    break
            if hit:
                break
        if hit is None and target is not None and target in page_blocks and target >= min_page:
            # A heading the scanner mangled beyond matching ("KAPAl11Ş") is
            # still where the contents page says it is: the first large,
            # short line in the top part of that page.
            blocks = free_blocks(target)
            for bi, b in enumerate(blocks):
                if b.bbox[1] > b.page_height * TOC_POSITIONAL_TOP_SHARE:
                    break
                text = _block_plain(b)
                if (b.size >= body_size * TOC_POSITIONAL_SIZE_RATIO and len(text) <= 80
                        and squash(text)):
                    hit = (target, blocks, bi, len(title_sq), [], None)
                    break
        if hit is None:
            if not unnumbered:
                plan.unmatched.append(entry.title)
            continue

        p, blocks, bi, n, stripped, printed_label = hit
        cursor = p
        title_block = blocks[bi]
        used.add(id(title_block))
        index = len(plan.entries)
        plan.roles[id(title_block)] = {"role": "title", "entry": index}
        page_title = _block_plain(title_block)
        # A label can share the title's block ("[Sunuş Yerine] Boris
        # Hessen'in Newton'ı"): peel it off, and keep how it was printed.
        for c in stripped:
            label_text, page_title = _split_printed_prefix(page_title, squash(c))
            if label_text:
                found_labels.setdefault(c, label_text)
        chapter_label = None
        if printed_label:
            chapter_label, page_title = _split_printed_prefix(page_title, squash(printed_label))
        if chapter_label and entry.number:
            # the contents page's numeral, set right, over the page's misreading ("111.")
            chapter_label = re.sub(r"^\s*\S+?(?=\s*[.)]?\s)", tidy_number(entry.number).rstrip(".)"),
                                   chapter_label, count=1)

        # a title set over several lines
        consumed = n
        j = bi + 1
        while consumed < len(title_sq) and j < len(blocks):
            nxt = blocks[j]
            nsq = squash(_block_plain(nxt))
            m = _squashed_match(nsq, title_sq[consumed:]) if nsq else None
            if m is None or nxt.bbox[1] - blocks[j - 1].bbox[3] > body_size * 3:
                break
            used.add(id(nxt))
            plan.roles[id(nxt)] = {"role": "title_cont", "entry": index}
            page_title += " " + _block_plain(nxt)
            consumed += m
            j += 1

        # what the page printed of the entry is the title; what is left of
        # the entry after it is the author ("… NEWTON'I Paul Blackledge")
        toc_head = head
        # Turkish capitalises every word of a heading, so "İşgal Edilen
        # Meydanlar, Hareket Halindeki Toplumlar" reads as a title and an
        # author. Where the page sets that tail inside the title itself, it
        # is the title's second half.
        printed_title = " ".join(_block_plain(b) for b in blocks[bi:j])
        if author and re.search(r",\s*" + re.escape(author.split()[0]), printed_title):
            toc_head, author = entry.title, None
        if author is None and consumed < len(title_sq):
            cut_head, rest = cut_title(entry.title, consumed)
            # what is left over is an author only if it reads like a name
            if (rest and len(rest.split()) <= 4 and len(squash(rest)) >= 4
                    and any(c.islower() for c in rest)):
                toc_head, author = cut_head, rest
        title_blocks = blocks[bi:j]
        byline = None
        byline_block = None
        if author and j < len(blocks):
            nxt = blocks[j]
            nsq = squash(_block_plain(nxt))
            if (nsq and _squashed_match(nsq, squash(author)) is not None
                    and nxt.bbox[1] - blocks[j - 1].bbox[3] < body_size * 4):
                used.add(id(nxt))
                plan.roles[id(nxt)] = {"role": "byline", "entry": index}
                byline = vote_title(author, _block_plain(nxt), vocab)
                byline_block = nxt
        if byline is None and author:
            byline = vote_title(author, None, vocab)

        # section labels printed above the title (same page or just before)
        label_block = title_block if stripped else None
        # A part's two-line name is looked for line by line, and the
        # chapter's own number as it reads set right ("il." is "II.").
        wanted = [part for c in entry.path for part in c.split(PART_JOIN)]
        if entry.number:
            wanted.append(tidy_number(entry.number))
        for c in wanted:
            if c in found_labels:
                continue
            c_sq = squash(c)
            for lp in (p, p - 1, p - 2):
                if lp not in page_blocks or lp < min_page:
                    continue
                for b in body_blocks_of(lp):
                    if id(b) in used or (lp == p and b.bbox[1] >= title_block.bbox[1]):
                        continue
                    bsq = squash(_block_plain(b))
                    own_label = (entry.number and c == tidy_number(entry.number)
                                 and CHAPTER_LABEL_PREFIX.fullmatch(_block_plain(b).strip() + " ") is not None)
                    if own_label or bsq and len(bsq) <= len(c_sq) + 3 and (
                        bsq == c_sq or SequenceMatcher(None, bsq, c_sq).ratio() >= 0.75
                    ):
                        used.add(id(b))
                        plan.roles[id(b)] = {"role": "label", "entry": index}
                        found_labels[c] = _block_plain(b)
                        if lp == p:
                            label_block = b
                        break
                if c in found_labels:
                    break

        path = [container_display(c) for c in entry.path]
        first_of_group = not any(e["path"] == path for e in plan.entries)
        # An opening page often carries no body text of its own, so the
        # text column is read off the nearest page that does.
        fallback_edges = None
        for q in (p + 1, p - 1, p + 2, p - 2, p + 3, p - 3):
            if q in page_blocks:
                fallback_edges = _column_edges(body_blocks_of(q), body_size)
                if fallback_edges:
                    break
        opener = _measure_opener(
            label_block if first_of_group else None,
            title_blocks,
            byline_block,
            body_blocks_of(p),
            body_size,
            fallback_edges,
        )
        plan.entries.append({
            "title": vote_title(toc_head, page_title, vocab),
            "byline": byline,
            "eyebrow": (_tidy_label(chapter_label) if chapter_label
                        else _tidy_label(found_labels.get(tidy_number(entry.number)) or tidy_number(entry.number))
                        if entry.number else path[-1] if path and first_of_group else None),
            "path": path,
            "page": p,
            "printed_page": entry.printed_page,
            "chapter_id": None,
            "opener": opener,
        })

    total = len(plan.entries) + len(plan.unmatched)
    plan.active = total >= TOC_MIN_ENTRIES and len(plan.entries) / total >= TOC_MIN_MATCHED_SHARE
    # A list whose first chapter opens deep into the book is the back half of
    # a contents page whose front half was not read; taken as the book's
    # structure it would fold everything before it into the front matter.
    if plan.entries:
        body_pages = max(1, doc.page_count - min_page)
        if min(e["page"] for e in plan.entries) - min_page > TOC_MAX_LATE_START_SHARE * body_pages:
            plan.active = False
    if not plan.active:
        plan.roles.clear()
    return plan


def _plan_from_outline(
    doc: fitz.Document,
    toc_pages: Set[int],
    page_blocks: Dict[int, List[RawBlock]],
    body_blocks_of,
    body_size: float,
) -> TocPlan:
    """The book's structure from its PDF bookmarks, resolved against the
    pages they point at — the same plan the printed contents page makes, so
    the conversion loop treats both alike.

    Each chapter bookmark is matched to the block that prints its title on
    its page (or the page either side). When the page's title cannot be
    matched — the scanner garbled a display face — the chapter still starts
    where the bookmark says, at the first block of that page. The title
    always comes from the bookmark: it is the one spelled right.
    """
    plan = TocPlan(source="outline")
    items = outline_reading_order(doc.get_toc() or [], doc.page_count, (doc.metadata or {}).get("title"))
    if not items:
        return plan
    used: Set[int] = set()

    def free_blocks(p: int) -> List[RawBlock]:
        return sorted((b for b in body_blocks_of(p) if id(b) not in used), key=lambda b: b.bbox[1])

    def find_title(page: int, title: str):
        for variant in title_variants(title):
            vsq = squash(variant)
            if len(vsq) < 2:
                continue
            for p in (page, page + 1, page - 1):
                if p not in page_blocks or p in toc_pages:
                    continue
                blocks = free_blocks(p)
                for bi, b in enumerate(blocks):
                    sq = squash(_block_plain(b))
                    if not sq:
                        continue
                    short_enough = len(sq) <= len(vsq) * 1.3 + 4
                    heading_like = b.size >= body_size * TOC_TITLE_MIN_SIZE_RATIO
                    if not (short_enough or heading_like):
                        continue
                    n = _squashed_match(sq, vsq)
                    if n is not None:
                        return p, blocks, bi, n, vsq, variant
        return None

    chapter_pages = sorted({it.page for it in items if it.kind == "chapter"})

    def pages_until_next(page: int) -> List[int]:
        """The pages a chapter can start on before the next one begins — a
        chapter that opens on a drawn title page starts its text later."""
        later = [q for q in chapter_pages if q > page]
        stop = min(later[0] if later else page + ANCHOR_SEARCH_PAGES, page + ANCHOR_SEARCH_PAGES)
        return list(range(page, max(stop, page + 1)))

    for item in items:
        if item.page in toc_pages:
            continue
        hit = find_title(item.page, item.title)
        if item.kind == "subheading":
            if hit:
                p, blocks, bi, n, vsq, _variant = hit
                used.add(id(blocks[bi]))
                plan.roles[id(blocks[bi])] = {"role": "subheading", "text": item.title}
            continue

        index = len(plan.entries)
        title = item.title
        byline = None
        opener = None
        eyebrow = item.label or (item.path[-1] if item.path and item.first_in_part else None)
        if hit:
            p, blocks, bi, n, vsq, variant = hit
            title_block = blocks[bi]
            used.add(id(title_block))
            plan.roles[id(title_block)] = {"role": "title", "entry": index}
            # a title set over several lines
            consumed, j = n, bi + 1
            while consumed < len(vsq) and j < len(blocks):
                nxt = blocks[j]
                nsq = squash(_block_plain(nxt))
                m = _squashed_match(nsq, vsq[consumed:]) if nsq else None
                if m is None or nxt.bbox[1] - blocks[j - 1].bbox[3] > body_size * 3:
                    break
                used.add(id(nxt))
                plan.roles[id(nxt)] = {"role": "title_cont", "entry": index}
                consumed += m
                j += 1
            title_blocks = blocks[bi:j]
            # The page may set the number on its own line above the name
            # ("BİR" / "Dogmacılık ve …"): that line is the label.
            label_block = None
            if bi > 0 and variant != item.title:
                above = blocks[bi - 1]
                asq = squash(_block_plain(above))
                near = (title_block.bbox[1] - above.bbox[3] < body_size * 4
                        or above.bbox[1] < above.page_height * TOC_POSITIONAL_TOP_SHARE)
                if asq and len(asq) <= 16 and squash(item.title).startswith(asq) and near:
                    used.add(id(above))
                    plan.roles[id(above)] = {"role": "label", "entry": index}
                    label_block = above
                    eyebrow = eyebrow or _block_plain(above)
            if item.label and label_block is None:
                lsq = squash(item.label)
                for lp in (p, p - 1):
                    for b in free_blocks(lp) if lp in page_blocks else []:
                        if lp == p and b.bbox[1] >= title_block.bbox[1]:
                            continue
                        bsq = squash(_block_plain(b))
                        if bsq and len(bsq) <= len(lsq) + 3 and (
                            bsq == lsq or SequenceMatcher(None, bsq, lsq).ratio() >= 0.75
                        ):
                            used.add(id(b))
                            plan.roles[id(b)] = {"role": "label", "entry": index}
                            label_block = b if lp == p else None
                            break
            # "Önsöz, N. Lenin": the author only when the page prints the name
            # under the title; otherwise the comma belongs to the title.
            head, author = split_author(item.title)
            byline_block = None
            if author and j < len(blocks):
                nxt = blocks[j]
                if (squash(_block_plain(nxt)) and _squashed_match(squash(_block_plain(nxt)), squash(author)) is not None
                        and nxt.bbox[1] - blocks[j - 1].bbox[3] < body_size * 4):
                    used.add(id(nxt))
                    plan.roles[id(nxt)] = {"role": "byline", "entry": index}
                    title, byline, byline_block = head, author, nxt
            elif author and _squashed_match(squash(_block_plain(title_block)), squash(head)) is not None \
                    and len(squash(_block_plain(title_block))) <= len(squash(head)) + 2:
                title, byline = head, author
            fallback_edges = None
            for q in (p + 1, p - 1, p + 2, p - 2):
                if q in page_blocks:
                    fallback_edges = _column_edges(body_blocks_of(q), body_size)
                    if fallback_edges:
                        break
            opener = _measure_opener(label_block, title_blocks, byline_block,
                                     body_blocks_of(p), body_size, fallback_edges)
        else:
            # The chapter starts where the bookmark says, at the first block
            # of that page (or of the next page that has text).
            anchor = None
            for p in pages_until_next(item.page):
                if p in page_blocks and p not in toc_pages:
                    blocks = free_blocks(p)
                    if blocks:
                        anchor = blocks[0]
                        break
            if anchor is None:
                plan.unmatched.append(item.title)
                continue
            used.add(id(anchor))
            plan.roles[id(anchor)] = {"role": "anchor", "entry": index}
        if eyebrow and squash(eyebrow) == squash(title):
            eyebrow = None
        plan.entries.append({
            "title": title,
            "byline": byline,
            "eyebrow": eyebrow,
            "path": list(item.path),
            "page": p,
            "printed_page": None,
            "chapter_id": None,
            "opener": opener,
        })

    plan.active = len(plan.entries) >= 2
    if not plan.active:
        plan.roles.clear()
    return plan


# ---------------------------------------------------------------------------
# The book's own typography
# ---------------------------------------------------------------------------
STYLE_BODY_SIZE_TOLERANCE = 0.06
STYLE_BODY_FONT_MIN_SHARE = 0.10
QUOTE_MIN_INDENT_EMS = 1.8
ATTRIBUTION_MAX_CHARS = 80
SPACED_MIN_GAP_SHARE = 0.02


def _build_style_profile(page_blocks: Dict[int, List[RawBlock]], body_size: float) -> dict:
    """Learn how this book sets its text, from the book.

    Which fonts carry the running text (an OCR'd book can have two), where
    the text column sits on left- and right-hand pages, the line pitch, and
    whether a new paragraph is marked by extra space or by an indent. None
    of it is assumed: italic and bold flags are absent on scanned books, so
    a quotation is recognised as "not the body font, set inside the
    column", and a paragraph break as "a gap the book does not leave
    between lines of one paragraph".
    """
    font_chars: Counter = Counter()
    for blocks in page_blocks.values():
        for b in blocks:
            if abs(b.size - body_size) <= body_size * STYLE_BODY_SIZE_TOLERANCE:
                font_chars[b.font_name] += len(b.text.strip())
    total = sum(font_chars.values()) or 1
    body_fonts = {f for f, n in font_chars.items() if n / total >= STYLE_BODY_FONT_MIN_SHARE}

    lefts: Dict[int, List[float]] = {0: [], 1: []}
    rights: Dict[int, List[float]] = {0: [], 1: []}
    diffs: List[float] = []
    starts: List[tuple] = []  # (gap, x0, parity)
    for page_num, blocks in page_blocks.items():
        edges = _column_edges(blocks, body_size)
        if edges:
            lefts[page_num % 2].append(edges[0])
            rights[page_num % 2].append(edges[1])
        lines = sorted(
            (lb for b in blocks
             if b.font_name in body_fonts and abs(b.size - body_size) <= body_size * 0.1
             for lb in b.line_boxes),
            key=lambda lb: lb[1],
        )
        for prev, cur in zip(lines, lines[1:]):
            d = cur[1] - prev[1]
            if body_size * 0.8 <= d <= body_size * 3.5:
                diffs.append(d)
                starts.append((d, cur[0], page_num % 2))

    def median(xs: List[float]) -> Optional[float]:
        xs = sorted(xs)
        return xs[len(xs) // 2] if xs else None

    edges_by_parity = {}
    for parity in (0, 1):
        left = median(lefts[parity]) or median(lefts[1 - parity])
        right = median(rights[parity]) or median(rights[1 - parity])
        edges_by_parity[parity] = (left, right) if left is not None and right is not None else None

    tight = [d for d in diffs if d <= body_size * 1.9]
    pitch = (Counter(round(d * 2) / 2 for d in tight).most_common(1)[0][0]
             if tight else body_size * 1.45)
    gaps = [(d, x0, par) for d, x0, par in starts if pitch * 1.45 <= d <= pitch * 2.6]
    indented = 0
    for d, x0, par in gaps:
        edges = edges_by_parity.get(par)
        if edges and x0 > edges[0] + body_size * 0.8:
            indented += 1
    spaced = (
        bool(diffs)
        and len(gaps) / len(diffs) >= SPACED_MIN_GAP_SHARE
        and (not gaps or indented / len(gaps) < 0.3)
    )
    return {
        "body_fonts": body_fonts,
        "edges": edges_by_parity,
        "pitch": pitch,
        "spaced": spaced,
    }


def _style_edges(style: dict, block: RawBlock) -> Optional[tuple]:
    return (style.get("edges") or {}).get(block.page_num % 2)


def _is_quote_block(block: RawBlock, style: dict, body_size: float) -> bool:
    """A quotation set inside the column in a face that is not the body's."""
    edges = _style_edges(style, block)
    if not edges or not block.line_boxes:
        return False
    if block.font_name in style["body_fonts"] and block.size >= body_size * 0.97:
        return False
    if not (body_size * 0.8 <= block.size <= body_size * 1.1):
        return False
    text = TRAILING_NOTE_NUMBER.sub("", _sanitize_plain_text(
        re.sub(re.escape(SUP_START) + r"\d{1,3}" + re.escape(SUP_END), "", block.text)).rstrip())
    # One short line with no sentence end is a run-in heading or a list
    # caption set in the quotation face, not a quotation.
    if len(block.line_boxes) == 1 and (len(text) < 12 or len(text) < 40 and text[-1:] not in ".!?…\"”'’:;"):
        return False
    indent = body_size * QUOTE_MIN_INDENT_EMS
    return all(lb[0] >= edges[0] + indent for lb in block.line_boxes)


def _is_attribution(block: RawBlock, style: dict, body_size: float) -> bool:
    """A short line set flush right under a quotation — its source."""
    edges = _style_edges(style, block)
    if not edges or len(block.line_boxes) != 1:
        return False
    text = _sanitize_plain_text(block.text)
    if not text or len(text) > ATTRIBUTION_MAX_CHARS:
        return False
    left, right = edges
    width = right - left
    flush_right = block.bbox[2] >= right - width * 0.05 and block.bbox[0] >= left + width * 0.35
    distinct = block.size <= body_size * 0.9 or block.font_name not in style["body_fonts"]
    return flush_right and distinct


PLATE_NUMBER = re.compile(r"^\s*(\d{1,3})\s*$")
PLATE_COLUMN_GAP_RATIO = 0.20


def _plate_parts(blocks: List[RawBlock], body_size: float) -> dict:
    """Sort the text of a plate page into its title and its captions.

    A plate sets pictures, a line naming the spread, and one caption per
    picture, each opened by the picture's number and set in its own column.
    Read as ordinary text the columns interleave line by line and every
    number turns into a note reference. Here the columns are found from
    where their lines start, each keeps its own number, and they are
    returned in reading order to be stacked one under another — the one
    arrangement a reflowing reader cannot break.
    """
    title: List[str] = []
    texts: List[RawBlock] = []
    numbers: List[tuple] = []  # (x, y, number) of each printed picture number
    for b in blocks:
        text = _sanitize_plain_text(clean_text(b.text))
        if not text:
            continue
        tokens = text.split()
        if all(PLATE_NUMBER.match(t) for t in tokens):
            numbers.append((b.bbox[0], b.bbox[1], b.bbox[2], tokens))
            continue
        letters = [c for c in text if c.isalpha()]
        if (len(b.line_boxes) <= 1 and len(letters) >= 4
                and sum(c.isupper() for c in letters) / len(letters) > 0.8):
            title.append(re.sub(r"\s+", " ", text))
        else:
            texts.append(b)

    columns: List[List[RawBlock]] = []
    if texts:
        width = texts[0].page_width
        for b in sorted(texts, key=lambda b: b.bbox[0]):
            if columns and b.bbox[0] - columns[-1][0].bbox[0] < width * PLATE_COLUMN_GAP_RATIO:
                columns[-1].append(b)
            else:
                columns.append([b])
    for col in columns:
        col.sort(key=lambda b: (b.bbox[1], b.bbox[0]))

    # A number belongs to the caption that starts just under it, in line
    # with it. Several numbers that came back as one row ("5 6") are laid
    # over the columns that row spans, left to right; numbers printed on
    # the pictures, or a folio, have no caption under them and drop out.
    tolerance = body_size * 1.6
    placed: List[tuple] = []
    for x0, y0, x1, tokens in numbers:
        placed.append((x0, y0, tokens[0]))
        spanned = [c[0].bbox[0] for c in columns if x0 + tolerance < c[0].bbox[0] <= x1 + tolerance]
        for x, tok in zip(spanned, tokens[1:]):
            placed.append((x, y0, tok))

    captions = []
    for col in columns:
        left, top = col[0].bbox[0], col[0].bbox[1]
        candidates = [
            (top - y, n) for x, y, n in placed
            if abs(x - left) <= tolerance and 0 <= top - y <= body_size * 3
        ]
        number = min(candidates)[1] if candidates else None
        paras: List[str] = []
        for b in col:
            text = _strip_marks(clean_text(b.text).replace(SUP_START, "").replace(SUP_END, ""))
            text = text.replace(PARA_BREAK, " ").strip()
            lead = re.match(r"^(\d{1,3})\s+(?=\D)", text)
            if lead and not paras and number in (None, lead.group(1)):
                number, text = lead.group(1), text[lead.end():]
            if paras and not _looks_paragraph_complete(paras[-1]):
                paras[-1] = _join_continuation(paras[-1], text, False)
            else:
                paras.append(text)
        if paras:
            captions.append({"number": number, "paragraphs": paras})
    return {"title": " ".join(title), "captions": captions}


def _plate_html(image_ids: List[str], parts: dict) -> str:
    imgs = "".join(
        f'<div class="plate-image"><img src="images/{i}.png" alt="Görsel"/></div>' for i in image_ids
    )
    title = f'<p class="plate-title">{html.escape(parts["title"])}</p>' if parts["title"] else ""
    caps = ""
    for cap in parts["captions"]:
        num = f'<p class="plate-num">{html.escape(cap["number"])}</p>' if cap["number"] else ""
        body = "".join(f"<p>{html.escape(_sanitize_plain_text(p))}</p>" for p in cap["paragraphs"])
        caps += f'<div class="plate-caption">{num}{body}</div>'
    return f'<figure class="plate">{imgs}<figcaption>{title}{caps}</figcaption></figure>'


def _follows_quotation(chapter, open_para: Optional[dict], block: RawBlock) -> bool:
    """A source line belongs under a quotation on the same page; a flush-right
    line anywhere else is a running head or a folio that got through."""
    if open_para is None:
        return False
    return (open_para.get("chapter") is chapter and open_para.get("kind") == "quote"
            and open_para.get("page") == block.page_num)


def _reading_order(blocks: List[RawBlock]) -> List[RawBlock]:
    """Put a single-column page's blocks in the order they are printed.

    PyMuPDF returns blocks in content-stream order, which is whatever order
    the producer drew them in. On an OCR'd book the opening page of a section
    drew the title and author *before* the "ÖN SÖZ" / "GİRİŞ" label printed
    above them, so the title was read first, landed at the end of the
    previous section, and the section itself never got its name.

    Sorting top to bottom is only safe when nothing sits side by side, so a
    page with two blocks sharing a band of height but not a band of width —
    columns, a marginal note, a caption beside a figure — is left exactly as
    the stream gave it.
    """
    if len(blocks) < 2:
        return blocks
    for i, a in enumerate(blocks):
        for b in blocks[i + 1:]:
            v_overlap = min(a.bbox[3], b.bbox[3]) - max(a.bbox[1], b.bbox[1])
            shortest = min(a.bbox[3] - a.bbox[1], b.bbox[3] - b.bbox[1])
            h_apart = a.bbox[2] <= b.bbox[0] or b.bbox[2] <= a.bbox[0]
            if shortest > 0 and v_overlap / shortest >= 0.5 and h_apart:
                return blocks
    return sorted(blocks, key=lambda b: b.bbox[1])


# ---------------------------------------------------------------------------
# Step 3: classification helpers
# ---------------------------------------------------------------------------
def _is_header_or_footer(
    block: RawBlock, header_ratio: Optional[float] = None, footer_ratio: Optional[float] = None
) -> bool:
    """Pure geometry: does this block sit inside the top/bottom margin band?

    This answers "where is it", NOT "should it be deleted". Deleting on
    position alone is what silently removed real body text, footnote tails
    and ten section headings from a book whose trim size happens to run its
    text close to the edge — see _detect_running_elements().
    """
    y0, y1 = block.bbox[1], block.bbox[3]
    hr = header_ratio if header_ratio is not None else HEADER_MARGIN_RATIO
    fr = footer_ratio if footer_ratio is not None else FOOTER_MARGIN_RATIO
    header_threshold = max(block.page_height * hr, HEADER_MARGIN_FLOOR_PT)
    footer_threshold = max(block.page_height * fr, FOOTER_MARGIN_FLOOR_PT)
    return y0 < header_threshold or y1 > block.page_height - footer_threshold


# How far in from the edge a block can sit and still be *considered* as a
# running head or foot. This is deliberately much more generous than the
# crop band above, and it is safe to be generous precisely because being a
# candidate deletes nothing: a candidate is only ever removed if the
# document repeats it on three or more pages.
#
# Keeping the two bands the same is what let running heads through. The
# crop band is a fraction of page height, so on a compact trim it is tiny —
# 0.045 of a 552.76pt page is 24.87pt — while that book prints its running
# head at y=36.6. The head was therefore never even looked at, never
# counted as repeating, and never dropped; it then either glued itself into
# the middle of a sentence across the page break, or, once line
# reconstruction was fixed, read as a clean short line and got promoted to
# a chapter title of its own.
RUNNING_SCAN_MARGIN_RATIO = 0.12
# Unmarked text below which a chapter ahead of the book's first real one is
# read as title/imprint debris and folded into the front matter.
FRONT_MATTER_STRAY_PROSE_CHARS = 60
RUNNING_SCAN_MARGIN_FLOOR_PT = 40.0


def _is_in_running_scan_band(block: "RawBlock") -> bool:
    """Only the TOP band is widened, deliberately.

    The foot of an academic page is where the notes live, and
    _running_signature() collapses digit runs so that a folio matches
    itself across pages — which also makes "12 Aynı eser, s. 45." and
    "15 Aynı eser, s. 78." collapse to one signature. Reaching further up
    from the bottom therefore starts counting repeated short citations as
    furniture and deleting real notes: measured at 4468 lost characters on
    Hessen and eight lost footnotes on Tenin. The head has no such
    population living next to it, so the extra reach is free there and
    dangerous here.
    """
    top = max(block.page_height * RUNNING_SCAN_MARGIN_RATIO, RUNNING_SCAN_MARGIN_FLOOR_PT)
    bottom = max(block.page_height * FOOTER_MARGIN_RATIO, FOOTER_MARGIN_FLOOR_PT)
    return block.bbox[1] < top or block.bbox[3] > block.page_height - bottom


# A running head/foot is defined by recurring, not by sitting near the edge.
# Three pages is deliberately a low bar: the signature has to match exactly
# after normalisation, so a real sentence essentially never reaches it, while
# a per-chapter running head in a short chapter still does.
RUNNING_ELEMENT_MIN_PAGES = 3
RUNNING_ELEMENT_MAX_WORDS = 14
_DIGIT_RUN_RE = re.compile(r"\d+")
_NON_WORD_RE = re.compile(r"[^\w#]+", re.UNICODE)


def _running_signature(text: str) -> str:
    """Normalised identity of a margin-band block, for repetition counting.

    Digit runs collapse to '#' so that a folio ("18") and a running head
    carrying one ("18  TENİN GÖZLERİ") look the same on every page they
    appear on — without that, every page's header is unique and nothing is
    ever recognised as running.
    """
    t = _sanitize_plain_text(text).lower()
    t = _DIGIT_RUN_RE.sub("#", t)
    t = _NON_WORD_RE.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


# OCR reads the same running foot a little differently on every page —
# "10 | V.İ. Lenin", "Vv. i. Lenin | 11", "V.i. Lenin | 13" — so no exact
# signature ever repeats and the foot was run into the paragraph crossing
# the page ("…gelişir) 18 | V.i. Lenin Karl Marks fiilen…"). On OCR text the
# letters alone are compared, and near-equal readings count as one. The
# looser match must also cover a good share of the book's pages: a short
# citation repeated in the notes ("Kapital, Birinci Cilt, s. 781") recurs
# on a handful of pages, a running foot on most of them.
OCR_RUNNING_SIMILARITY = 0.85
OCR_RUNNING_MIN_LETTERS = 6
OCR_RUNNING_MIN_PAGE_SHARE = 0.3


def _is_in_ocr_running_band(block: "RawBlock") -> bool:
    """Both edges as wide as the head band. The foot band is kept narrow to
    spare the notes (see _is_in_running_scan_band), but the page-share rule
    already does that here, and a scan's foot can sit well clear of the
    edge: one book's ended 45pt up a 595pt page, 0.4pt outside the band."""
    reach = max(block.page_height * RUNNING_SCAN_MARGIN_RATIO, RUNNING_SCAN_MARGIN_FLOOR_PT)
    return block.bbox[1] < reach or block.bbox[3] > block.page_height - reach


def _loose_running_key(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", _sanitize_plain_text(text).casefold())
    return "".join(c for c in decomposed if c.isalpha())


def _cluster_loose_keys(occurrences: Dict[str, Set[int]], min_pages: int) -> Set[str]:
    """Keys whose near-equal readings, taken together, recur on min_pages."""
    clusters: List[tuple] = []  # (representative, member keys, pages)
    for key in sorted(occurrences, key=lambda k: -len(occurrences[k])):
        for rep_key, members, pages in clusters:
            if SequenceMatcher(None, key, rep_key, autojunk=False).ratio() >= OCR_RUNNING_SIMILARITY:
                members.add(key)
                pages |= occurrences[key]
                break
        else:
            clusters.append((key, {key}, set(occurrences[key])))
    return {k for _, members, pages in clusters if len(pages) >= min_pages for k in members}


@dataclass
class RunningElements:
    """The set of margin-band texts this document actually repeats."""
    signatures: Set[str] = field(default_factory=set)
    pages_scanned: int = 0
    candidates_seen: int = 0
    ocr_keys: Set[str] = field(default_factory=set)

    def is_ocr_running(self, block: "RawBlock") -> bool:
        return (bool(self.ocr_keys) and _is_in_ocr_running_band(block)
                and OCR_FONT_NAME_HINT.search(block.font_name or "") is not None
                and _loose_running_key(block.text) in self.ocr_keys)

    def is_running(self, block: "RawBlock") -> bool:
        sig = _running_signature(block.text)
        if sig in self.signatures:
            return True
        # A watermark the extractor ran together with a stray letter of the
        # page ("telegram ornekkanal n") is still the watermark.
        return any(
            len(known) >= RUNNING_PREFIX_MIN_CHARS and sig.startswith(known)
            and len(sig) - len(known) <= RUNNING_PREFIX_SLACK
            for known in self.signatures
        )


RUNNING_PREFIX_MIN_CHARS = 8
RUNNING_PREFIX_SLACK = 3
# Lines a publisher or a download site prints about the book, not in it: an
# edition note, a citation request, an ISBN, a watermark handle. Set large
# on a title page they read as headings and opened chapters called "Bu kitap
# ilk defa: 1974 yılında…" in fourteen books of the library survey.
IMPRINT_LINE = re.compile(
    r"\b(ilk defa|ilk bask[ıi]|yay[ıi]nlanm[ıi]şt[ıi]r|yay[ıi]n[ıi]d[ıi]r|dijital yay[ıi]n\w*|indir - oku|"
    r"kaynak g[öo]sterilmesi|al[ıi]nt[ıi]larda|isbn|sertifika no|bask[ıi] ve cilt|"
    r"t[üu]m haklar[ıi]|all rights reserved|telegram)\b|@\w{3,}|www\.|https?://",
    re.IGNORECASE,
)


def _detect_running_elements(
    page_blocks: Dict[int, List["RawBlock"]],
    header_ratio: Optional[float] = None,
    footer_ratio: Optional[float] = None,
) -> RunningElements:
    """Find the running heads, running feet and folios of THIS document.

    Cropping by position alone assumes the margin band contains nothing but
    furniture. On a compact trim that assumption is simply false: measured on
    one 318x505pt book, the bands held 248 lines and 778 words of real
    content — body prose, the last line of most footnotes, and ten section
    headings — and not one single repeated string. Every heading that began
    at the top of its page was deleted; every heading that began mid-page
    survived. Position was the only variable.

    So position is used to decide what to *look at*, and repetition decides
    what to remove. A page number, a book title and a chapter head recur by
    definition; a sentence does not.

    The cost of being wrong is deliberately asymmetric. Failing to recognise
    a running head leaves one visible, editable stray line. Deleting by
    position removes content silently, with no warning and no trace.
    """
    occurrences: Dict[str, Set[int]] = {}
    ocr_occurrences: Dict[str, Set[int]] = {}
    candidates = 0
    for page_num, blocks in page_blocks.items():
        for block in blocks:
            # The generous band, not the crop band — see
            # RUNNING_SCAN_MARGIN_RATIO. Repetition is what removes a block;
            # position only decides what gets counted.
            if (OCR_FONT_NAME_HINT.search(block.font_name or "") and _is_in_ocr_running_band(block)
                    and len(block.text.split()) <= RUNNING_ELEMENT_MAX_WORDS):
                loose = _loose_running_key(block.text)
                if len(loose) >= OCR_RUNNING_MIN_LETTERS:
                    ocr_occurrences.setdefault(loose, set()).add(page_num)
            if not _is_in_running_scan_band(block):
                continue
            candidates += 1
            signature = _running_signature(block.text)
            if not signature or len(signature.split()) > RUNNING_ELEMENT_MAX_WORDS:
                continue
            occurrences.setdefault(signature, set()).add(page_num)

    ocr_pages = [p for p, blocks in page_blocks.items()
                 if any(OCR_FONT_NAME_HINT.search(b.font_name or "") for b in blocks)]
    return RunningElements(
        signatures={sig for sig, pages in occurrences.items()
                    if len(pages) >= RUNNING_ELEMENT_MIN_PAGES},
        pages_scanned=len(page_blocks),
        candidates_seen=candidates,
        ocr_keys=_cluster_loose_keys(ocr_occurrences, max(
            RUNNING_ELEMENT_MIN_PAGES,
            round(OCR_RUNNING_MIN_PAGE_SHARE * len(ocr_pages)),
        )) if ocr_occurrences else set(),
    )


# Running-element detection is a whole-document question, but the PDF
# Editor asks it one page at a time — every page turn would otherwise
# re-parse the entire book. The answer only depends on the file and the
# mask ratios, so it is memoised on exactly those. Keyed on mtime so an
# edited file is never answered from a stale entry; capped so a long
# session over many books cannot grow without bound.
_RUNNING_CACHE: "Dict[tuple, RunningElements]" = {}
_RUNNING_CACHE_MAX = 4


def _running_elements_for_document(
    doc: fitz.Page, pdf_path: str, body_size: float,
    header_ratio: Optional[float], footer_ratio: Optional[float],
) -> RunningElements:
    try:
        stamp = os.path.getmtime(pdf_path)
    except OSError:
        stamp = None
    key = (pdf_path, stamp, header_ratio, footer_ratio, round(body_size, 2))
    cached = _RUNNING_CACHE.get(key)
    if cached is not None:
        return cached

    running = _detect_running_elements(
        {i: _extract_page_blocks(doc[i], i, body_size) for i in range(doc.page_count)},
        header_ratio,
        footer_ratio,
    )
    if len(_RUNNING_CACHE) >= _RUNNING_CACHE_MAX:
        _RUNNING_CACHE.pop(next(iter(_RUNNING_CACHE)))
    _RUNNING_CACHE[key] = running
    return running


def _should_drop_as_furniture(
    block: RawBlock,
    running: Optional[RunningElements],
    header_ratio: Optional[float] = None,
    footer_ratio: Optional[float] = None,
) -> bool:
    """Should this block be discarded before anything else looks at it?

    When header_ratio/footer_ratio are supplied the person has dragged the
    mask lines by hand in the PDF Editor and is saying, explicitly, "delete
    what is inside this band". That stays a pure positional crop — it is a
    direct instruction, not a guess, and it is the behaviour the editor's
    live preview shows.

    With no override we are guessing, and a guess must not delete content
    silently: the block has to be both in the band AND something the
    document repeats.
    """
    manual_override = header_ratio is not None or footer_ratio is not None
    if manual_override and _is_header_or_footer(block, header_ratio, footer_ratio):
        return True
    # A head or foot the document repeats is furniture wherever it sits. It
    # is checked over the wider scan band rather than the crop band, because
    # a compact trim can print its running head outside a crop band that is
    # a fraction of page height — and a dragged mask line says "delete
    # inside this", never "keep the furniture just outside it".
    return running is not None and (
        (_is_in_running_scan_band(block) and running.is_running(block))
        or running.is_ocr_running(block)
    )


# Genuine authored text never contains a raw control character, other than
# the three sentinels this same extraction step inserts and plain
# whitespace. When one survives into a block's text it means the glyph
# didn't come from a font mapping to real characters at all — confirmed on
# a back cover's ISBN barcode, whose own "number strip" font decoded to
# '111 11 \x18\x19 111\n\x1a \x1bll lllH 11 11' and was large enough to be
# read as a chapter heading, with a footnote-zone block right below it that
# decoded to the barcode's human-readable digits and got filed as a note.
#
# This is deliberately used to gate *structural promotion* (heading,
# footnote) only, never to drop a block from the ordinary paragraph stream:
# a page can carry real prose that a font-encoding fault has partly
# corrupted (confirmed on a dazai author-bio block, mostly legible text
# with a handful of stray control bytes from the same class of fault), and
# that block still belongs in the book — a garbled paragraph is a tolerated,
# visible cosmetic defect (PROJECT_CONTEXT bug #6), silently deleting real
# text to avoid looking at it is not. A block made *entirely* of glyph
# noise has nothing to lose either way; one that merely contains some does.
_TEXT_SENTINELS = {SUP_START, SUP_END, PARA_BREAK, "\t", "\n", "\r", *INLINE_MARKS}


def _looks_like_glyph_noise(text: str) -> bool:
    return any(
        unicodedata.category(c) == "Cc" and c not in _TEXT_SENTINELS
        for c in text
    )


def _block_center_in_region(block: RawBlock, regions: List[List[float]]) -> bool:
    """Used by the PDF Editor's 'Hariç Tut' bounding-box action — a block
    is considered excluded if its center point falls inside any of the
    given [x0,y0,x1,y1] PDF-point rectangles for this page. Using the
    center (not full overlap) keeps this predictable for the person
    drawing the box: draw around the text you want gone, and anything
    whose midpoint lands inside it disappears — no partial-overlap edge
    cases to reason about."""
    cx = (block.bbox[0] + block.bbox[2]) / 2
    cy = (block.bbox[1] + block.bbox[3]) / 2
    for region in regions:
        x0, y0, x1, y1 = region
        if x0 <= cx <= x1 and y0 <= cy <= y1:
            return True
    return False


def _is_footnote_zone(block: RawBlock, body_size: float) -> bool:
    zone_start = block.page_height * (1 - FOOTNOTE_ZONE_RATIO)
    in_bottom_zone = block.bbox[1] >= zone_start
    is_small = block.size <= (body_size - FOOTNOTE_SIZE_DELTA)
    return in_bottom_zone and is_small


# A book sets its notes in one size. "Small type low on the page" also
# catches what a book sets smaller than its prose for other reasons: an
# indented quotation running to the foot of a page (Müşterek Mekan sets its
# notes at 7.4pt, its block quotations at 8.4pt, its prose at 10pt) was read
# as a note, lifted out of the text and given a running number, and the
# word it broke across the page ("İni-/siyatifi") was left in halves. A
# block that opens with no note marker and is set clearly larger than the
# book's marked notes is the text's, not a note.
NOTE_SIZE_MARGIN = 0.6
NOTE_SIZE_MIN_SAMPLES = 3


def _book_note_size(page_blocks: "Dict[int, List[RawBlock]]", body_size: float,
                    prose_pages: Set[int]) -> Optional[float]:
    """The largest size the book sets a marked footnote in (the blocks low on
    a prose page that open with a note marker); None when it marks too few.
    The largest, not a typical size: a scan reports one note at 5.5pt and the
    next at 7.3pt (Bütün Yazılar), and a note whose number the scan lost is no
    larger than the marked ones — only text the book sets above every one of
    its notes is kept out of them."""
    sizes = [
        b.size
        for p, blocks in page_blocks.items() if p in prose_pages
        for b in blocks
        if _is_footnote_zone(b, body_size) and _split_note_marker(clean_text(b.text))[0]
    ]
    if len(sizes) < NOTE_SIZE_MIN_SAMPLES:
        return None
    return max(sizes)


# A scan's text layer can report the same type at a different size from
# page to page: one ClearScan book sets most pages at 10.8pt and some at
# 8.2pt, on the same 13.2pt line pitch. Every rule that compares a block to
# the body size then reads those pages as notes or captions. What the eye
# sees is the pitch, so a page whose lines keep the book's pitch while its
# reported size strays has its sizes set back to the body size. A page
# really set small — a notes page — sets its lines closer, and is left alone.
PAGE_SCALE_MIN_PITCH_SAMPLES = 10
PAGE_SCALE_PITCH_TOLERANCE = 0.07
PAGE_SCALE_SIZE_TOLERANCE = 0.1


def _page_pitch_and_size(blocks: List["RawBlock"]) -> "tuple[Optional[float], Optional[float], int]":
    """The page's main type size (by characters) and the line pitch of the
    lines set in it — measured across blocks, since a scan's layer can make
    every line a block of its own."""
    weights: Counter = Counter()
    for b in blocks:
        weights[round(b.size, 1)] += len(b.text)
    if not weights:
        return None, None, 0
    size = weights.most_common(1)[0][0]
    tops = sorted({round(lb[1], 1) for b in blocks if round(b.size, 1) == size for lb in b.line_boxes})
    pitches = sorted(t2 - t1 for t1, t2 in zip(tops, tops[1:]) if 0.5 * size < t2 - t1 < 3 * size)
    if not pitches:
        return None, size, 0
    return pitches[len(pitches) // 2], size, len(pitches)


def _normalize_page_scales(page_blocks: Dict[int, List["RawBlock"]], body_size: float) -> int:
    """Returns how many pages were set back to the body size."""
    rescaled = 0
    measured = {p: _page_pitch_and_size(bl) for p, bl in page_blocks.items()}
    at_body = sorted(g for g, sz, n in measured.values()
                     if g and n >= PAGE_SCALE_MIN_PITCH_SAMPLES
                     and abs(sz - body_size) <= PAGE_SCALE_SIZE_TOLERANCE * body_size)
    if len(at_body) < 5:
        return 0
    body_pitch = at_body[len(at_body) // 2]
    for p, (pitch, size, n) in measured.items():
        if (pitch and size and n >= PAGE_SCALE_MIN_PITCH_SAMPLES
                and abs(size - body_size) > PAGE_SCALE_SIZE_TOLERANCE * body_size
                and abs(pitch - body_pitch) <= PAGE_SCALE_PITCH_TOLERANCE * body_pitch):
            rescaled += 1
            factor = body_size / size
            # A line the layer sized a little apart ("10.9" among "8.2") but
            # set on a box as tall as the text's is text; only a line set
            # visibly taller keeps its difference.
            heights = sorted(lb[3] - lb[1] for b in page_blocks[p] if round(b.size, 1) == size
                             for lb in b.line_boxes)
            text_height = heights[len(heights) // 2] if heights else None
            for b in page_blocks[p]:
                if text_height and b.line_boxes and all(
                        abs((lb[3] - lb[1]) - text_height) <= 0.15 * text_height for lb in b.line_boxes):
                    b.size = body_size
                else:
                    b.size = round(b.size * factor, 2)
    return rescaled


# A book can set its section headings smaller than its text, or in another
# face at the same size: "Bir Meşruiyet Krizi mi?" in 7.8pt over 10.8pt
# prose. Type size alone never finds them. What does is that a book uses
# one style for them, again and again: a short single line, starting with
# a capital and not ending a sentence, with the text resuming right under
# it. A style that does that on three pages or more is the book's
# sub-heading style.
SUBHEADING_MIN_PAGES = 3
SUBHEADING_MAX_WORDS = 10
SUBHEADING_SIZE_DIFF = 0.08


def _subheading_key(block: "RawBlock") -> tuple:
    return (round(block.size, 1), block.font_name or "")


def _could_be_subheading(block: "RawBlock", nxt: Optional["RawBlock"], body_size: float) -> bool:
    text = " ".join(_block_plain(block).split())
    if not text or len(block.line_boxes) > 1 or not 1 <= len(text.split()) <= SUBHEADING_MAX_WORDS:
        return False
    if not text[0].isupper() or text[-1] in ".,;:" or garbage_share(text) > 0.2:
        return False
    if sum(1 for c in text if c.isalpha()) < 4:
        return False
    if abs(block.size - body_size) < SUBHEADING_SIZE_DIFF * body_size and not (block.bold or block.italic):
        return False
    if block.size < 0.6 * body_size:
        return False
    if nxt is None:
        return False
    # the text resumes right under it, in the book's body type, with a new
    # paragraph: a line the next one continues in lower case is that
    # paragraph's first line, set apart only by the scan
    following = _strip_marks(_block_plain(nxt)).lstrip(" \"'“‘«(")
    return (abs(nxt.size - body_size) <= SUBHEADING_SIZE_DIFF * body_size
            and len(_block_plain(nxt)) >= 80
            and (following[:1].isupper() or following[:1].isdigit())
            and 0 <= nxt.bbox[1] - block.bbox[3] <= 3 * body_size)


def _repeated_head_key(block: "RawBlock") -> str:
    # words only: the folio a scanner glued on comes back as "1 ı ı ı", "j l33"
    return _folded(" ".join(re.findall(r"[^\W\d_]{3,}", _block_plain(block))))


def _subheading_styles(page_blocks: Dict[int, List["RawBlock"]], body_size: float,
                       body_blocks_of) -> "tuple[Set[tuple], Set[str]]":
    """The book's sub-heading styles, and the lines that only look like
    sub-headings because they are running heads the furniture pass missed
    (a scanner's page number glued on: "Sınıflı Toplum ve Devlet [ 21")."""
    found: List[tuple] = []
    for p in page_blocks:
        blocks = sorted(body_blocks_of(p), key=lambda b: b.bbox[1])
        for i, b in enumerate(blocks):
            if _could_be_subheading(b, blocks[i + 1] if i + 1 < len(blocks) else None, body_size):
                found.append((p, b))
    head_pages: Dict[str, Set[int]] = {}
    for p, b in found:
        if _is_in_running_scan_band(b):
            head_pages.setdefault(_repeated_head_key(b), set()).add(p)
    running_like = {k for k, ps in head_pages.items() if len(ps) >= 2}
    pages: Dict[tuple, Set[int]] = {}
    for p, b in found:
        if _repeated_head_key(b) not in running_like:
            pages.setdefault(_subheading_key(b), set()).add(p)
    return {k for k, ps in pages.items() if len(ps) >= SUBHEADING_MIN_PAGES}, running_like


PROSE_PAGE_MIN_SIZE_RATIO = 0.85
PROSE_PAGE_MIN_LINE_WIDTH = 0.5
PROSE_PAGE_MIN_WIDE_LINES = 4


def _body_text_volume(blocks: List["RawBlock"], body_size: float) -> int:
    """How many characters this page sets at body size or larger."""
    return sum(
        len(block.text.strip())
        for block in blocks
        if block.size > body_size - FOOTNOTE_SIZE_DELTA
    )


def _pages_that_set_prose(
    page_blocks: "Dict[int, List[RawBlock]]", body_size: float
) -> Set[int]:
    """The pages that set at least one line of the book's running prose.

    Two decisions hang off this, and they are the same decision asked twice.

    *Can small print at the foot of this page be a footnote?* "Small type
    low on the page" is the whole of the footnote test, and on a text page
    it is a good one. What it cannot see is that a footnote is an
    *annotation*: it exists because some sentence on the page called for it.
    A page that sets no prose called for nothing, so whatever is small and
    low on it is the page's own content - a plate's caption, a copyright
    notice, an imprint, a column of captions printed as the page's subject
    rather than as its margin.

    *Is this page part of the reading flow?* A plate spread interrupts a
    sentence in the printed book too, and the reader steps over it without
    losing the thread. The converter has to do the same or the sentence
    arrives in two halves.

    That is not a rare corner. A figure spread is exactly this page: two
    columns of captions in the bottom half and no prose anywhere, and every
    caption on it was being filed as a footnote - unreachable, since no
    sentence links to it, and gone from the flow where the reader would have
    read it beside the picture.

    The bar is deliberately one line of prose, not a share of what a full
    page sets. The tempting version - "at least a fifth of a typical text
    page" - reads like the safer measurement and is the worse one, because
    the volumes do not separate the way that phrasing assumes. Measured
    across the corpus they run 0, 2, 5, 45, 94, 249, 273, 319 ... with no
    gap anywhere: a plate page and a chapter's closing page differ by two
    orders of magnitude, but the pages in between are real prose pages that
    happen to be short. A share-of-typical cut lands among them and takes
    the last page of a chapter with it - and the last page of a chapter is
    where footnotes actually live. So the question to ask is not "is this
    page busy?" but "did this page set any prose at all?", which is the
    only part of it a footnote needs to be true.

    Blocks on a page this rejects are not dropped - they are emitted as
    their own paragraphs, which is where a caption belonged in the first
    place, and they are held apart from whatever paragraph was open when
    the page arrived.
    """
    volumes = {
        page_num: _body_text_volume(blocks, body_size)
        for page_num, blocks in page_blocks.items()
    }
    prose = {
        page_num
        for page_num, volume in volumes.items()
        if volume >= MIN_CHARS_FOR_TEXT_BEARING_PAGE
    }
    # A scan can be printed at different scales from page to page, so a
    # page's running text may sit below the book's body size while still
    # being running text: full-width lines, page after page. Measured on one
    # book: body 10.1pt overall, 8.8pt on a sixth of its pages, all of them
    # read as caption pages and none of their sentences joined.
    for page_num, blocks in page_blocks.items():
        if page_num in prose:
            continue
        wide = [
            b for b in blocks
            if b.size >= body_size * PROSE_PAGE_MIN_SIZE_RATIO
            and (b.bbox[2] - b.bbox[0]) >= b.page_width * PROSE_PAGE_MIN_LINE_WIDTH
        ]
        lines = sum(max(1, len(b.line_boxes)) for b in wide)
        if lines >= PROSE_PAGE_MIN_WIDE_LINES:
            prose.add(page_num)
    if not prose:
        # No page in this document sets even a line at body size, so the
        # size reference itself is what is wrong, not the book. Gating on a
        # broken measurement would switch footnote detection off for the
        # whole book and route every page through the caption path; leave
        # the older rules alone, which are no worse here than they ever
        # were.
        return set(page_blocks)
    return prose


def _matches_eyebrow(text: str) -> bool:
    t = text.strip()
    return bool(
        ORDINAL_SECTION_LABEL.match(t)
        or NUMERIC_SECTION_LABEL.match(t)
        or ORDINAL_NUMERIC_SECTION_LABEL.match(t)
        or BRACKET_EYEBROW.match(t)
    )


CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _sanitize_plain_text(text: str) -> str:
    """Strip control characters — including our own PARA_BREAK/SUP sentinels
    if one leaks through — and collapse the resulting whitespace. Anything
    that becomes an XML <title> or attribute (chapter titles, eyebrows)
    MUST go through this, or a stray control character crashes the EPUB
    export with 'All strings must be XML compatible'."""
    if not text:
        return text
    cleaned = CONTROL_CHARS_RE.sub(" ", _strip_marks(text))
    cleaned = fix_broken_bracket_glyphs(cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


# --- note markers ----------------------------------------------------------
# A note's printed marker is usually set as a raised digit, so extraction has
# already wrapped it in the SUP_START/SUP_END sentinels by the time the note
# line is read back. A pattern that only knows about a bare digit fails on
# exactly the notes that are best marked up: it matches "1 Stephen F. Cohen,
# Bukharin..." but not the same line with its 1 wrapped in sentinels. Those
# notes then fell back to a running counter, so the stored marker no longer
# equalled the digit printed in the body and the reference could never be
# linked. Both forms have to be accepted, and the sentinels are stripped off
# the marker so it stays comparable with the body's data-fnmark.
_SUP_O, _SUP_C = re.escape(SUP_START), re.escape(SUP_END)
# Translator's and editor's notes are often marked with bullets ("•",
# "••") as well as stars; a scanner reads the same mark as "*" in the text
# and "•" under the line, so the two are one mark (normalised to stars).
_MARKER_CORE = r"(?:\d{1,3}|\*{1,3}|•{1,3}|[†‡§¶])"
_WRAPPED_MARKER = r"(?:" + _SUP_O + r"\s*(" + _MARKER_CORE + r")\s*" + _SUP_C + r"|(" + _MARKER_CORE + r"))"

BARE_MARKER_LINE = re.compile(r"^\s*" + _WRAPPED_MARKER + r"\s*[\.\)]?\s*$")
# OCR reads a lone note number 1 as a letter ("ı", "l", "I").
OCR_NOTE_ONE = re.compile(r"^\s*[ılI]\s+(?=[A-ZÇĞİÖŞÜ\"'])")
# The same bracketed number opening its note: "[8] 4 Mayıs" read as
# "8! 4 Mayıs", "[7] Yi Ho" as "'1 Yi Ho". At least one bracket survives.
OCR_BRACKETED_NOTE_START = re.compile(
    r"^\s*(?:[\[{(!|'’](\d{1,3})[\]})!|]?|(\d{1,3})[\]})!|])\s+(?=\S)")
NOTE_SYMBOL_START = re.compile(r"^\s*(?:[*•†‡§]|\d{1,3}[\s.)])")
TRAILING_NOTE_NUMBER = re.compile(r"(?<=[^\d\s])\s+(\d{1,3})$")
# A note number whose 1 a scanner read as a letter: "ı4 Navarinou Park…" is
# note 14, "1l Halk…" note 11. Only with a digit in it, so "Il" or "lI" as
# words never count.
OCR_LETTER_ONE_MARKER = re.compile(r"^\s*((?:[ılI]\d{1,2})|(?:\d[ılI]\d?))\s+(?=\S)")
LEADING_MARKER = re.compile(r"^\s*" + _WRAPPED_MARKER + r"\s*[\.\)]?[\s" + re.escape(PARA_BREAK) + r"]+")


def _match_marker(match: "Optional[re.Match]") -> Optional[str]:
    """The marker text out of either alternative of _WRAPPED_MARKER."""
    if match is None:
        return None
    return match.group(1) or match.group(2)


def _split_note_marker(text: str) -> "tuple[Optional[str], str]":
    """Peel a note's printed marker off the front of its own text.

    Returns (marker, remaining_text). The marker is returned without its
    sentinels so it compares equal to the body's data-fnmark; the remaining
    text no longer repeats the marker, which is what the builder renders in
    its own <span class="footnote-marker">.
    """
    m = LEADING_MARKER.match(text)
    marker = _match_marker(m)
    if marker is None:
        m = OCR_BRACKETED_NOTE_START.match(text)
        marker = _match_marker(m)
    if marker is None:
        m = OCR_LETTER_ONE_MARKER.match(text)
        if m:
            marker = m.group(1).translate(str.maketrans("ılI", "111"))
    if marker is None:
        return None, text
    return marker.replace("•", "*"), text[m.end():]


def _clean_footnote_text(text: str) -> str:
    """Note text never passes through _finalize_html_text, so the extraction
    sentinels survive in it. Dropping SUP_START/SUP_END keeps the digits of
    any *inner* reference ("LW 21, s. 57") readable instead of leaving them
    floating between two blanks once the builder squashes control characters,
    and PARA_BREAK inside a note is a line-indent artefact, not a paragraph.
    """
    if not text:
        return text
    text = _strip_marks(text.replace(SUP_START, "").replace(SUP_END, ""))
    text = text.replace(PARA_BREAK, " ")
    return re.sub(r"[ 	]{2,}", " ", text).strip()


_GARBLED_DIGIT_LETTER_RE = re.compile(r"[A-Za-zÇĞİÖŞÜçğıöşü]\d|\d[A-Za-zÇĞİÖŞÜçğıöşü]")
_GARBLED_DOUBLE_DOT_RE = re.compile(r"(?<!\.)\.\.(?!\.)")


def _looks_garbled(text: str) -> bool:
    """Detects heading text that likely came from a glyph whose PDF font
    has a broken/missing ToUnicode mapping — some display/decorative
    heading fonts in badly-converted PDFs map their glyphs to the wrong
    Unicode codepoints entirely. This is a property of the PDF file
    itself (confirmed: it reproduces identically in pdftotext, completely
    independent of our own extraction code), so it can't be repaired by
    cleaning the text — only detected, and where possible corrected
    against a cleanly-encoded copy of the same title elsewhere in the
    document (see _apply_toc_title_corrections)."""
    if not text:
        return False
    digit_count = sum(1 for c in text if c.isdigit())
    if digit_count >= 2 and _GARBLED_DIGIT_LETTER_RE.search(text):
        return True
    if _GARBLED_DOUBLE_DOT_RE.search(text):
        return True
    return False


def _apply_toc_title_corrections(chapters: List["Chapter"], toc_entry_titles: List[str], warnings: List[dict]) -> None:
    """Best-effort: replace a garbled or badly-truncated chapter title with
    the corresponding entry from the İçindekiler page, matched by position
    (both should list real chapters in the same reading order). A title is
    only replaced if it looks clearly garbled OR is implausibly shorter
    than what the TOC has for the same position (e.g. "il" where the TOC
    says "İkinci Hatırat" — the same font-encoding corruption can drop
    characters entirely rather than substituting garbage ones, which the
    digit/dot pattern alone won't catch). A chapter whose own heading
    extracted cleanly and isn't a suspicious truncation keeps it, since
    that's often more precise than the TOC's shorter version (e.g.
    eyebrow-merged multi-line titles)."""
    real_chapters = [c for c in chapters if c.kind == "chapter" and not c.is_split_continuation]
    for chapter, toc_title in zip(real_chapters, toc_entry_titles):
        if not toc_title or _looks_garbled(toc_title):
            continue
        suspiciously_truncated = len(chapter.title) <= 4 and len(toc_title) >= 2 * len(chapter.title) + 3
        if _looks_garbled(chapter.title) or suspiciously_truncated:
            chapter.title = toc_title

    for chapter in real_chapters:
        if _looks_garbled(chapter.title):
            # Tolerated by policy (PROJECT_CONTEXT bug #6) — the PDF's own
            # font encoding is broken and cannot be repaired here, so this
            # stays informational rather than a warning to act on.
            _add_warning(
                warnings,
                f"'{chapter.title}' başlığı PDF'teki bozuk bir font kodlamasından kaynaklanıyor olabilir "
                "— lütfen Live Editor'de elle kontrol edin.",
                SEVERITY_INFO,
            )


def _sync_split_continuation_titles(chapters: List["Chapter"]) -> None:
    """A chapter split by _split_chapter_if_needed() inherits its parent's
    title at split time — during parsing, before the TOC-based
    title-correction pass runs at the very end. If the parent's title gets
    corrected afterward, the continuation is left holding the old
    (sometimes empty/garbled) one, which even renders as a bare literal
    "Untitled" fallback in the exported EPUB. This propagates every
    chapter's current title forward onto any continuation that follows it,
    so they always match."""
    last_title = None
    for chapter in chapters:
        if chapter.is_split_continuation and last_title:
            chapter.title = last_title
        else:
            last_title = chapter.title


_TAG_RE = re.compile(r"<[^>]+>")
_LEADING_SENTINEL_RE = re.compile(r"^[\x02\x03]+")
MAX_WARNINGS_PER_CHECK = 8

# Ranks every warning this pipeline can raise against the project's own
# stated priority: content loss and wrong chapter boundaries outrank broken
# paragraph flow, which outranks a titling/footnote drift signal, which
# outranks a tolerated cosmetic note. A flat, undifferentiated warning list
# reads the same whether the book lost a chapter or just has an uncertain
# language guess — this is what lets the person tell those apart at a
# glance instead of reading every line to find out which ones matter.
SEVERITY_CRITICAL = "critical"  # content loss, or a structural defect
SEVERITY_WARNING = "warning"    # a real defect that isn't content loss
SEVERITY_INFO = "info"          # tolerated, cosmetic-tier


def _add_warning(warnings: List[dict], message: str, severity: str) -> None:
    warnings.append({"message": message, "severity": severity})


def _add_chapter_warning(
    warnings: List[dict], chapter_warnings: List[dict], chapter_id: str, message: str, severity: str
) -> None:
    _add_warning(warnings, message, severity)
    chapter_warnings.append({"chapter_id": chapter_id, "message": message, "severity": severity})


def _plain_text(paragraph_html: str) -> str:
    return _TAG_RE.sub("", paragraph_html).strip()


def _run_publish_readiness_checks(
    chapters: List["Chapter"], toc_entry_titles: List[str], warnings: List[dict], chapter_warnings: List[dict]
) -> None:
    """Automated post-conversion QA pass, run on every conversion. Each
    check here exists because we've hit that exact failure mode before:
    - TOC/chapter-count mismatch is exactly the off-by-one drift that made
      a whole chapter's content end up under the wrong title.
    - Duplicate titles are the visible symptom of that same drift.
    - Empty/"Untitled" titles are the split-continuation title-inheritance
      bug (fixed, but this catches it — or anything like it — for good).
    - Unjoined hyphens are a real KDP problem (Amazon has delisted books
      over exactly this), and our own hyphen-join logic isn't infallible.
    - Orphan lowercase-starting paragraphs are a lightweight stand-in for
      Distributed Proofreaders' separate "smooth reading" pass — a full
      three-stage pipeline rewrite is a bigger, riskier change we're
      deliberately not rushing into; this heuristic gets most of the
      value without it.
    None of this blocks the conversion — it only adds visible warnings the
    person can act on. Every check tied to one specific chapter also adds
    an entry to chapter_warnings (chapter_id + message) so the UI can make
    the warning clickable — jump straight to the chapter it's about,
    rather than a plain-text list the person has to search themselves.
    """
    real_chapters = [c for c in chapters if c.kind == "chapter" and not c.is_split_continuation]

    if toc_entry_titles and len(real_chapters) != len(toc_entry_titles):
        # Not tied to one chapter — stays a plain warning. A count mismatch
        # is exactly the signal for a wrong chapter boundary somewhere.
        _add_warning(
            warnings,
            f"İçindekiler {len(toc_entry_titles)} bölüm listeliyor ama {len(real_chapters)} bölüm "
            "oluşturuldu — bir yerde başlık eşleştirmesi kaymış olabilir, bölüm listesini gözden geçirin.",
            SEVERITY_CRITICAL,
        )

    empty_title_count = 0
    for chapter in chapters:
        if chapter.kind == "chapter" and (not chapter.title or chapter.title.strip() in ("", "Untitled")):
            empty_title_count += 1
            if empty_title_count <= MAX_WARNINGS_PER_CHECK:
                _add_chapter_warning(
                    warnings, chapter_warnings, chapter.id,
                    f"'{chapter.id}' bölümünün başlığı boş kalmış — Live Editor'de düzeltin.",
                    SEVERITY_WARNING,
                )

    seen_titles: dict = {}
    for chapter in real_chapters:
        key = chapter.title.strip().lower()
        if key:
            seen_titles.setdefault(key, []).append(chapter)
    dup_count = 0
    for key, group in seen_titles.items():
        if len(group) > 1:
            dup_count += 1
            if dup_count <= MAX_WARNINGS_PER_CHECK:
                msg = (
                    f"'{group[0].title}' başlığı {len(group)} farklı bölümde kullanılmış — "
                    "İçindekiler eşleştirmesi kaymış olabilir, içerikleri kontrol edin."
                )
                _add_warning(warnings, msg, SEVERITY_WARNING)
                for chapter in group:
                    chapter_warnings.append({"chapter_id": chapter.id, "message": msg, "severity": SEVERITY_WARNING})

    short_count = 0
    for chapter in real_chapters:
        total_len = sum(len(_plain_text(p)) for p in chapter.paragraphs)
        if total_len < 200:
            short_count += 1
            if short_count <= MAX_WARNINGS_PER_CHECK:
                _add_chapter_warning(
                    warnings, chapter_warnings, chapter.id,
                    f"'{chapter.title}' bölümü çok kısa görünüyor ({total_len} karakter) — "
                    "içerik kaybı olabilir, kontrol edin.",
                    SEVERITY_CRITICAL,
                )

    hyphen_count = 0
    orphan_count = 0
    for chapter in chapters:
        for p_html in chapter.paragraphs:
            plain = _plain_text(p_html)
            if not plain:
                continue
            if HYPHEN_BREAK_RE.search(plain):
                hyphen_count += 1
                if hyphen_count <= MAX_WARNINGS_PER_CHECK:
                    _add_chapter_warning(
                        warnings, chapter_warnings, chapter.id,
                        f"'{chapter.title}' bölümünde birleştirilmemiş bir tire kalmış: \"...{plain[-30:]}\"",
                        SEVERITY_WARNING,
                    )
            # A page that sets no prose was never part of the reading
            # flow, so nothing on it can have failed to join the paragraph
            # above: an index runs "elektrik 47, 100" and a caption runs
            # "detay, Neues Palais" because that is how they are printed.
            # Firing here would put four warnings on a correct index and
            # teach the person to scroll past the list.
            if PAGE_ASIDE_CLASS in p_html or "index-entry" in p_html:
                continue
            cleaned = _LEADING_SENTINEL_RE.sub("", plain)
            if cleaned and cleaned[0].islower():
                orphan_count += 1
                if orphan_count <= MAX_WARNINGS_PER_CHECK:
                    _add_chapter_warning(
                        warnings, chapter_warnings, chapter.id,
                        f"'{chapter.title}' bölümünde küçük harfle başlayan bir paragraf var — "
                        f"önceki paragrafla birleşmemiş bir cümle parçası olabilir: \"{cleaned[:40]}…\"",
                        SEVERITY_WARNING,
                    )

    if hyphen_count > MAX_WARNINGS_PER_CHECK:
        _add_warning(
            warnings, f"...ve {hyphen_count - MAX_WARNINGS_PER_CHECK} birleştirilmemiş tire daha.", SEVERITY_WARNING
        )
    if orphan_count > MAX_WARNINGS_PER_CHECK:
        _add_warning(
            warnings, f"...ve {orphan_count - MAX_WARNINGS_PER_CHECK} şüpheli paragraf daha.", SEVERITY_WARNING
        )


# Turkish attaches the possessive to how a number is *spoken*, so "%7'si"
# but "%21'i" — the suffix follows the last vowel of the last word said
# ("yedi", "bir"), and a number ending in a vowel takes a buffer -s-.
# Writing "%7'i" in a Turkish product's warning list looks like a bug in
# the warning, which is the last thing a warning can afford to look like.
_TR_PERCENT_SUFFIX_ONES = {1: "i", 2: "si", 3: "ü", 4: "ü", 5: "i",
                           6: "sı", 7: "si", 8: "i", 9: "u"}
_TR_PERCENT_SUFFIX_TENS = {0: "ı", 1: "u", 2: "si", 3: "u", 4: "ı", 5: "si",
                           6: "ı", 7: "i", 8: "i", 9: "ı", 10: "ü"}


def _tr_percent(value: float) -> str:
    """'%43'ü' — a percentage with the possessive suffix Turkish expects."""
    n = int(round(value))
    ones = n % 10
    suffix = _TR_PERCENT_SUFFIX_ONES[ones] if ones else _TR_PERCENT_SUFFIX_TENS[min(n // 10, 10)]
    return f"%{n}'{suffix}"


# ---------------------------------------------------------------------------
# Document-level content accounting
# ---------------------------------------------------------------------------
# Every check above is per-chapter: it can tell you a chapter looks short,
# and it says nothing at all when the whole book comes out empty. That is
# the failure that actually happened — a default-settings run produced a
# valid 17.7 MB EPUB with zero text and zero warnings, and a margin crop
# deleted 778 words and 10 headings, also silently. Both are invisible from
# inside the output: the chapters that survive look perfectly well-formed.
# Seeing it needs the one thing the rest of the pipeline never consults
# again once extraction is done — the PDF's own text layer, counted whole.
#
# A ratio is exactly the kind of single number PROJECT_CONTEXT §18 warns
# against deciding structure on, so it decides nothing here: it changes no
# output, only what the person is told. The two accountings below are
# deliberately independent — words that vanished, and pages marked as
# image that were not blank — so a settings mistake that hides from one
# still shows up in the other.
CONTENT_ACCOUNTING_MIN_SOURCE_WORDS = 200  # below this a ratio is noise, not signal
CONTENT_ACCOUNTING_PAGE_MIN_WORDS = 20     # a page holding fewer is a plate or a divider
# Measured on the corpus: a healthy conversion lands at 0.958-0.964 on all
# three books, the ~4 % being running heads, page numbers and skipped index
# pages. Crop ratios dragged to 0.10 drop hessen to 0.51 and dazai to 0.18.
CONTENT_ACCOUNTING_LOW_RATIO = 0.85
CONTENT_ACCOUNTING_SEVERE_RATIO = 0.50


def _run_content_accounting(
    doc,
    chapters: List["Chapter"],
    excluded_pages: Set[int],
    image_pages: Set[int],
    warnings: List[dict],
) -> None:
    """Count the PDF's text layer against the text that actually shipped."""
    source_words = 0
    text_page_count = 0
    marked_image_with_text = 0
    for page_num in range(doc.page_count):
        if page_num in excluded_pages:
            continue
        words = len(doc[page_num].get_text("text").split())
        source_words += words
        if words >= CONTENT_ACCOUNTING_PAGE_MIN_WORDS:
            text_page_count += 1
            if page_num in image_pages:
                marked_image_with_text += 1

    if marked_image_with_text:
        _add_warning(
            warnings,
            f"{marked_image_with_text} sayfa Görsel olarak işaretli ve üzerinde yazı var — "
            "bu sayfalar olduğu gibi resim olarak gösterilecek, yazıları ayrıca metne "
            "alınmayacak. Metin olarak da istiyorsanız sayfayı Metin yapın.",
            # Showing a marked page as printed is exactly what "Görsel" asks
            # for, so this is a reminder, not a defect.
            SEVERITY_INFO,
        )

    # A genuinely scanned book has no text layer to account against, and
    # saying "you lost 100 %" of nothing would be the loudest warning in
    # the list on the one book where it means least.
    if source_words < CONTENT_ACCOUNTING_MIN_SOURCE_WORDS:
        return

    kept_words = 0
    for chapter in chapters:
        for paragraph in chapter.paragraphs:
            kept_words += len(_TAG_RE.sub(" ", paragraph).split())
        for footnote in chapter.footnotes:
            kept_words += len(footnote.text.split())

    if kept_words == 0:
        _add_warning(
            warnings,
            f"PDF'in metin katmanında {source_words} kelime var ama EPUB'a hiç metin girmedi — "
            f"{text_page_count} metinli sayfanın tamamı görsel/hariç olarak işaretlenmiş ya da "
            "kırpma oranları sayfayı baştan sona siliyor olabilir.",
            SEVERITY_CRITICAL,
        )
        return

    ratio = kept_words / source_words
    if ratio < CONTENT_ACCOUNTING_SEVERE_RATIO:
        _add_warning(
            warnings,
            f"Kaynak metnin yalnızca {_tr_percent(ratio * 100)} EPUB'a girdi "
            f"({kept_words}/{source_words} kelime) — üstbilgi/altbilgi kırpma oranlarını, "
            "hariç tutulan bölgeleri ve görsel işaretli sayfaları kontrol edin.",
            SEVERITY_CRITICAL,
        )
    elif ratio < CONTENT_ACCOUNTING_LOW_RATIO:
        _add_warning(
            warnings,
            f"Kaynak metnin {_tr_percent((1 - ratio) * 100)} EPUB'a girmedi "
            f"({kept_words}/{source_words} kelime) — kırpma ayarlarını gözden geçirin.",
            SEVERITY_WARNING,
        )


# A title's note marker, left behind as a stray mark: the asterisk a book
# prints after a chapter title comes back as a lone star, dagger or closing
# quote (OCR reads "Düşünmek*" as "Düşünmek”"). It is a reference, not part
# of the title, and only counts as stray when nothing opened it.
_TITLE_NOTE_MARK_RE = re.compile(r"[\s]*[*†‡”“\"']+$")


def _ocr_text_reads_as_words(text: str) -> bool:
    """Does an OCR'd line read as words, or as recognition noise?

    A scanner's software returns something for every mark on the page, so
    the decorated masthead of a journal comes back as "aa My0ODoĞAAKAŞTIRMA
    ARLKİM," — which then opens a chapter, because it is short and set
    large. Real words are upper case, lower case or capitalised; a token
    that switches case inside itself, or mixes digits in among letters, is
    the scanner guessing at a shape.
    """
    tokens = [t for t in re.findall(r"[^\s]+", text) if sum(c.isalpha() for c in t) >= 2]
    if not tokens:
        return False
    noise = 0
    for token in tokens:
        letters = "".join(c for c in token if c.isalpha())
        written_as_a_word = (
            letters == letters.lower()
            or letters == letters.upper()
            or letters == letters[0].upper() + letters[1:].lower()
        )
        digit_among_letters = any(c.isdigit() for c in token)
        if not written_as_a_word or digit_among_letters:
            noise += 1
    return noise / len(tokens) <= OCR_HEADING_NOISE_MAX_SHARE


# On a page read by OCR the type size is guessed from the height of each
# recognised glyph box, so a line of capitals or a line of noise from an
# illustration measures "large" as easily as a title does. A read line has
# to look like a title as well as be set large.
OCR_HEADING_SIZE_RATIO = 1.3
OCR_HEADING_MAX_WORDS = 12


def _ocr_line_can_be_heading(block: "RawBlock", text: str, body_size: float) -> bool:
    if not _ocr_text_reads_as_words(text):
        return False
    words = text.split()
    if len(words) > OCR_HEADING_MAX_WORDS or "|" in text or re.search(r"(\.\s*){4,}", text):
        return False
    first = next((c for c in text if c.isalnum()), "")
    if first.islower():
        return False  # the rest of a sentence, not a title
    if len(words) > 6 and re.search(r"[.!?]\s+\S", text):
        return False  # one sentence ends and another begins: prose
    if garbage_share(text) > 0.2 or sum(1 for w in words if len(w) >= 3) == 0:
        return False
    # labels ("BİRİNCİ BÖLÜM") are recognised by their words, not their size
    return block.size >= body_size * OCR_HEADING_SIZE_RATIO or _matches_eyebrow(text) or bool(HEADING_KEYWORDS.match(text))


def _strip_title_note_mark(text: str) -> str:
    stripped = _TITLE_NOTE_MARK_RE.sub("", text)
    if stripped == text or not stripped:
        return text
    opener = sum(text.count(c) for c in "\"“”'")
    return text if opener > 1 else stripped


HEADING_MIN_ALNUM_SHARE = 0.5
HEADING_MAX_FOREIGN_SHARE = 0.3
HEADING_LOWERCASE_MAX_WORDS = 5


def _heading_is_noise(text: str) -> bool:
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return True
    if sum(1 for c in chars if c.isalnum()) < HEADING_MIN_ALNUM_SHARE * len(chars):
        return True
    letters = [c for c in chars if c.isalpha()]
    # Latin through Latin Extended-A carries Turkish and the western
    # languages; "ǸǹǺȜ" past it is a broken font's private alphabet.
    foreign = sum(1 for c in letters if ord(c) > 0x17F)
    return bool(letters) and foreign > HEADING_MAX_FOREIGN_SHARE * len(letters)


def _is_heading(block: RawBlock, body_size: float) -> Optional[str]:
    if _looks_like_glyph_noise(block.text):
        return None
    text = _strip_title_note_mark(_sanitize_plain_text(block.text))
    if not text or len(text) > 140:
        return None
    if IMPRINT_LINE.search(text):
        return None
    # A section break ("* * *", "❖") is often set large, and so read as the
    # title of a chapter that is really the next scene of the same one.
    if is_symbol_line(text):
        return None
    # A broken text layer sets its noise large as readily as its titles —
    # form rules read as ":::ı:::_::::r", a row of icons as "® @ ©" — and a
    # line a scanner enlarged is a sentence picked up mid-way ("giriş ve
    # çıkıştaki depresyon ağırlığı…"). None of it names a chapter. A title
    # the scanner misread a letter of ("ÖNSÖZ: 5TEVEN HOLL") still does, so
    # what is measured is the noise itself: marks where letters should be,
    # and letters from no alphabet the book is set in.
    if _heading_is_noise(text):
        return None
    if sum(1 for c in text if c.isalpha()) < 2 and not text.strip().isdigit():
        return None
    if text[:1].islower() and len(text.split()) >= HEADING_LOWERCASE_MAX_WORDS:
        return None
    # On a page read by OCR, "short and set large" is also true of every
    # decorated line the scanner could not read. Such a line is kept as
    # text, but it does not get to start a chapter.
    if OCR_FONT_NAME_HINT.search(block.font_name or "") and not _ocr_line_can_be_heading(block, text, body_size):
        return None
    # A section label is a heading whatever its size, because it is often
    # set smaller than the title it sits above — and smaller than the
    # body too, where the label is tracked small caps.
    if _matches_eyebrow(text):
        return text
    if HEADING_KEYWORDS.match(text):
        return text
    is_large = block.size >= (body_size + HEADING_SIZE_DELTA)
    is_short = len(text.split()) <= 12
    if is_large and is_short:
        return text
    if block.bold and is_short and block.size >= body_size + 0.8 and len(text) < 90:
        return text
    return None


# A title that wraps onto a second physical line looks like exactly one
# thing: the same type, on the same page, one line's worth of white space
# below the line it continues. A title page stacks series, title, author
# and translator in *different* sizes with real space between them, and a
# heading four pages later continues nothing at all. "The previous block
# was also heading-sized" cannot tell any of those apart, which is how
# whole title pages ended up concatenated into one chapter title.
WRAPPED_TITLE_MAX_SIZE_DELTA = 0.6      # pt; real continuations measured 0.0
WRAPPED_TITLE_MAX_GAP_RATIO = 0.9       # x the type size; real ones measured 0.29
WRAPPED_TITLE_MIN_GAP_RATIO = -0.6      # line boxes may overlap a little
WRAPPED_TITLE_MAX_LINES = 4
WRAPPED_TITLE_MAX_CHARS = 160


def _continues_wrapped_title(block: RawBlock, prev: Optional[dict], title: str, added: str, lines: int) -> bool:
    """Is this heading-sized block the next line of the title we just read?"""
    if prev is None or lines >= WRAPPED_TITLE_MAX_LINES:
        return False
    if block.page_num != prev["page"]:
        return False
    if abs(block.size - prev["size"]) > WRAPPED_TITLE_MAX_SIZE_DELTA:
        return False
    size = max(block.size, prev["size"], 1.0)
    gap = block.bbox[1] - prev["y1"]
    if not (WRAPPED_TITLE_MIN_GAP_RATIO * size <= gap <= WRAPPED_TITLE_MAX_GAP_RATIO * size):
        return False
    return len(title) + 1 + len(added) <= WRAPPED_TITLE_MAX_CHARS


# A part divider that opens a part runs straight into the part: either into
# a real title, which takes the label as its eyebrow through the ordinary
# heading path, or into the first line of the opening paragraph. The same
# divider caught in an undetected contents list is followed by that list —
# a page-number column and other entries' titles, short lines set in the
# fine type the list is printed in. So a stranded label becomes a chapter
# only when what arrives under it is a full line of body text. Neither
# measurement separates the two alone: the contents list in tenin is set
# at 0.91x body size, and the real part dividers in hessen at 0.83x.
EYEBROW_PROMOTION_MIN_SIZE_RATIO = 0.95  # x body; the real opener measured 0.98
EYEBROW_PROMOTION_MIN_CHARS = 40         # real opener 61 chars, list entries 1-14


# When more than this share of a book's body text is "centered and narrow",
# that is how the book sets its body, not its quotations: one ABBYY-made book
# of the library had every line of its text boxed as a quotation.
ACADEMIC_QUOTE_MAX_BOOK_SHARE = 0.25


def _set_off_quotes_are_distinct(page_blocks: Dict[int, List[RawBlock]], prose_pages: Set[int],
                                 body_size: float) -> bool:
    total = flagged = 0
    for page_num in prose_pages:
        for block in page_blocks.get(page_num, []):
            if abs(block.size - body_size) > body_size * 0.2:
                continue
            n = len(block.text.strip())
            total += n
            if _is_academic_blockquote(block):
                flagged += n
    return not total or flagged / total <= ACADEMIC_QUOTE_MAX_BOOK_SHARE


def _is_academic_blockquote(block: RawBlock) -> bool:
    x0, x1 = block.bbox[0], block.bbox[2]
    block_center = (x0 + x1) / 2
    page_center = block.page_width / 2
    block_width = x1 - x0
    narrow_enough = block_width <= block.page_width * BLOCKQUOTE_MAX_WIDTH_RATIO
    centered = abs(block_center - page_center) <= block.page_width * BLOCKQUOTE_CENTER_TOLERANCE
    short_enough = len(block.text) < 500
    return narrow_enough and centered and short_enough


def _is_centered(block: RawBlock) -> bool:
    x0, x1 = block.bbox[0], block.bbox[2]
    block_center = (x0 + x1) / 2
    page_center = block.page_width / 2
    block_width = x1 - x0
    return (
        abs(block_center - page_center) <= block.page_width * CENTER_TEXT_TOLERANCE
        and block_width <= block.page_width * CENTER_TEXT_MAX_WIDTH_RATIO
    )


def _is_index_page(page_text: str) -> bool:
    return is_mostly_punctuation_or_digits(page_text, INDEX_PAGE_DIGIT_RATIO)


# --- a printed index ------------------------------------------------------------
# A line of an index: a term, then the pages it is on —
#   "Agamben, Giorgio, 33, 36, 102-3"   "ağ oluşturma, 49-50"   "ABD ordusu 39-40"
# Read as running text, an index came out as one blob per page in the last
# chapter, its page numbers taken for note references.
INDEX_LOCATORS = r"\d{1,4}(?:\s*[-–]\s*\d{1,4})?(?:\s*[,;]\s*\d{1,4}(?:\s*[-–]\s*\d{1,4})?)*"
INDEX_ENTRY_LINE = re.compile(r"^\D{2,}?[\s,.:]+" + INDEX_LOCATORS + r"\s*\.?$")
INDEX_LOCATOR_TAIL = re.compile(r"(?<![\w.-])" + INDEX_LOCATORS + r"\s*\.?\s*$")
INDEX_LOCATOR = re.compile(r"(?<!\d)(\d{1,4})((?:\s*[-–]\s*\d{1,4})?)")
# an entry that stops on one of these goes on in the next line: "Ayrıca bkz." / "Atina"
INDEX_OPEN_END = re.compile(r"\b(?:bkz|bakınız|ayrıca|see|also|ve|and|ile)\.?$", re.I)
# a scanner splits off a number's first digit ("1 12" for 112, "1 54" for 154);
# in an index numbers are kept apart by commas, but "122 127" are two numbers
INDEX_SPLIT_NUMBER = re.compile(r"(?<!\d)(\d) (?=\d{1,3}\b)")
INDEX_MIN_LINES = 8
INDEX_MIN_LINES_LAST = 3     # the page that ends an index already found
INDEX_ENTRY_SHARE = 0.45
INDEX_FROM = 0.6            # an index stands at the back of the book
INDEX_TITLES = {
    "dizin", "indeks", "index", "genel dizin", "ad dizini", "adlar dizini", "kisi dizini",
    "kisiler dizini", "kavram dizini", "kavramlar dizini", "terim dizini", "terimler dizini",
    "ozel adlar dizini", "konu dizini",
}
# the one-word titles, spelled the usual way whatever case the page sets them in
INDEX_TITLE_WORDS = {"dizin": "Dizin", "indeks": "İndeks", "index": "Index"}


def _index_title_key(text: str) -> str:
    t = text.replace("İ", "i").replace("I", "ı").lower().replace("ı", "i")
    t = t.translate(str.maketrans("çğöşüâîû", "cgosuaiu"))
    return " ".join(re.sub(r"[^a-z]+", " ", t).split())


def _is_index_title(text: str) -> bool:
    """ "DİZİN", "İSİM DİZİNİ", "Kavramlar Dizini", "Name Index" … """
    key = _index_title_key(text)
    return key in INDEX_TITLES or (len(key.split()) <= 4 and key.endswith((" dizini", " index")))


def _index_lines(body_blocks: List[RawBlock], folio: Optional[int] = None) -> List[tuple]:
    """A page's printed lines as (x0, column, text) in reading order, down the
    left column and then the right. An index is a list, so its lines are read
    one by one, not joined into paragraphs. They come from the page's body
    blocks, whose lines are already rebuilt from the glyphs (no space a PDF
    invented inside "Thomas") and cleared of running heads; the page's own
    number (`folio`) left in its margin is dropped too — and only that: a
    line of page numbers carried over to the top of the page is an entry's."""
    lines = []
    for b in body_blocks:
        texts = re.split(r"[\n\x04]", b.text)
        boxes = b.line_boxes if len(b.line_boxes) == len(texts) else [b.bbox] * len(texts)
        mid = b.page_width / 2
        band = b.page_height * FOLIO_BAND_RATIO
        for raw, (x0, y0, x1, y1) in zip(texts, boxes):
            raw = raw.replace(SUP_START, "").replace(SUP_END, "")   # an index has no note references
            text = clean_text(raw).strip()
            if not text:
                continue
            if folio is not None and text == str(folio) and (y0 < band or y1 > b.page_height - band):
                continue
            # cleaning deletes a soft hyphen; at the line's end it says the
            # word goes on in the next line ("tahri-" / "fat")
            if raw.rstrip().endswith(chr(0xAD)) and not text.endswith("-"):
                text += "-"
            lines.append((0 if x0 < mid - 5 else 1, y0, x0, text))
    lines.sort()
    return [(x0, column, text) for column, _, x0, text in lines]


def _index_pages(doc: "fitz.Document", page_blocks: Dict[int, List[RawBlock]],
                 body_blocks_of, toc_pages) -> Set[int]:
    """The pages of the book's printed index: in its back part, most of their
    lines a term followed by page numbers, one run of pages — and the page
    before that run when it opens with the index's title."""
    total = doc.page_count

    def reads_as_index(p: int, min_lines: int) -> bool:
        # cheap first: an index page is full of numbers
        if len(re.findall(r"\b\d{1,4}\b", " ".join(b.text for b in page_blocks[p]))) < min_lines:
            return False
        lines = [t for _, _, t in _index_lines(body_blocks_of(p)) if len(t) > 3]
        entries = sum(1 for t in lines if INDEX_ENTRY_LINE.match(t))
        return len(lines) >= min_lines and entries >= INDEX_ENTRY_SHARE * len(lines)

    found = [p for p in sorted(page_blocks)
             if p >= INDEX_FROM * total and p not in toc_pages and reads_as_index(p, INDEX_MIN_LINES)]
    if not found:
        return set()
    runs, run = [], [found[0]]
    for p in found[1:]:
        if p - run[-1] <= 2:
            run.append(p)
        else:
            runs.append(run)
            run = [p]
    runs.append(run)
    best = max(runs, key=len)
    pages = set(range(best[0], best[-1] + 1)) & set(page_blocks)
    # the index's last page is often a short one
    after = best[-1] + 1
    while after in page_blocks and reads_as_index(after, INDEX_MIN_LINES_LAST):
        pages.add(after)
        after += 1
    before = best[0] - 1
    if before in page_blocks and any(_is_index_title(t)
                                     for _, _, t in _index_lines(body_blocks_of(before))[:3]):
        pages.add(before)
    return pages


def _index_entries(lines: List[tuple], body_size: float, carry: Optional[list] = None) -> List[list]:
    """One index page's entries as [kind, text]: "letter" (A, B …), "entry",
    or "sub" (set in under the entry above). A line that carries on the one
    before — the rest of its page numbers, or of a long term — is joined to
    it, across the page break too (`carry` is the last entry of the page
    before)."""
    left: Dict[int, float] = {}
    for x0, column, _ in lines:
        left[column] = min(left.get(column, x0), x0)
    entries: List[list] = []
    last = carry
    for x0, column, text in lines:
        if _is_index_title(text):
            continue
        if len(text) == 1 and text.isalpha():
            # a scanner reads the big letter in either case
            entries.append(["letter", {"i": "İ", "ı": "I"}.get(text, text.upper())])
            last = None
            continue
        indented = x0 > left[column] + 0.6 * body_size
        tail = last[1].rstrip() if last is not None else ""
        if last is not None and (
                text[:1].isdigit()
                or tail.endswith((",", ";", "-", "–", "("))
                or INDEX_OPEN_END.search(tail)
                or (indented and not INDEX_LOCATOR_TAIL.search(tail) and not tail.endswith(":"))):
            if tail.endswith(("-", "–")) and text[:1].isdigit():
                last[1] = tail + text                   # "49-" / "50"
            elif tail.endswith("-") and text[:1].islower():
                last[1] = tail[:-1] + text              # a word broken at the line end
            else:
                last[1] = tail + " " + text
            continue
        last = ["sub" if indented else "entry", text]
        entries.append(last)
    return entries


def _index_entry_html(kind: str, text: str) -> str:
    """An index entry, its page numbers linked to the printed pages
    ("#page-N"; the builder points each at the chapter that holds the page,
    or drops the link where the book does not mark that page)."""
    if kind == "letter":
        return f'<p class="index-letter">{_finalize_html_text(text)}</p>'
    body = _finalize_html_text(INDEX_SPLIT_NUMBER.sub(r"\1", text))
    tail = INDEX_LOCATOR_TAIL.search(body)
    if tail:
        body = body[:tail.start()] + INDEX_LOCATOR.sub(
            lambda m: f'<a href="#page-{int(m.group(1))}">{m.group(0)}</a>', body[tail.start():])
    return f'<p class="{"index-entry index-sub" if kind == "sub" else "index-entry"}">{body}</p>'


# a leader dot left in front of the number (".40") still leaves a number
BARE_PAGE_NUMBER_LINE = re.compile(r"[.\s]*\d[\d ]*")


def _bare_page_number(line: str) -> Optional[int]:
    """The integer on a line that holds nothing but one, or None.

    Spaces are tolerated inside the digits because OCR routinely splits a
    two-digit number ("31" -> "3 1"); joining them back recovers the real
    value, and a line of digits is not a sentence either way.
    """
    stripped = line.strip()
    if not stripped or not BARE_PAGE_NUMBER_LINE.fullmatch(stripped):
        return None
    return int(stripped.replace(" ", "").lstrip("."))


def _toc_page_number_column(lines: List[str]) -> bool:
    """Is this a contents page that sets its page numbers in their own
    column instead of after a dot leader?

    `looks_like_toc_line()` needs the number on the title's line, which is
    how a dot-leader contents page reads. Plenty of books instead put the
    titles down one column and the numbers down another; extraction then
    yields either every title followed by every number, or title and number
    alternating, and in neither case does a single line carry both. Such a
    page scores zero on the line test, so it is parsed as body text — which
    turns its entries into spurious chapters duplicating the real ones, and
    dumps the number column into the book as a run of loose digits.

    What identifies it is the column itself: bare-number lines that are
    *ascending*. A contents page numbers its entries in reading order and
    never goes back. That single condition is what separates it
    from the pages that otherwise look similar — an endnote page's markers
    restart at 1 under a running page number, and a body page's footnote
    markers repeat — and it does not depend on the language, the layout or
    the words on the page.
    """
    real_lines = [ln for ln in lines if ln.strip()]
    if len(real_lines) < TOC_PAGE_MIN_LINES:
        return False
    numbers = [n for n in (_bare_page_number(ln) for ln in real_lines) if n is not None]
    if len(numbers) < TOC_NUMBER_COLUMN_MIN_ENTRIES:
        return False
    if len(numbers) / len(real_lines) < TOC_NUMBER_COLUMN_LINE_RATIO:
        return False
    # Two entries can start on one page ("I. … 24", "II. … 24"), so the
    # column never goes down rather than always going up.
    return all(a <= b for a, b in zip(numbers, numbers[1:])) and numbers[-1] > numbers[0]


def _is_toc_page(lines: List[str]) -> bool:
    real_lines = [ln for ln in lines if ln.strip()]
    if len(real_lines) < TOC_PAGE_MIN_LINES:
        return False
    hits = sum(1 for ln in real_lines if looks_like_toc_line(ln))
    if (hits / len(real_lines)) >= TOC_PAGE_LINE_RATIO:
        return True
    return _toc_page_number_column(real_lines)


# ---------------------------------------------------------------------------
# Step 4: HTML assembly helpers
# ---------------------------------------------------------------------------
CAPTION_LIKE_MAX_CHARS = 90


SAFE_ORNAMENT_CHARS = set("*\u2022\u2726\u2727\u2756\u25CF\u00A7~-\u2013\u2014 ❖✦✧☙❧⁂◆◇●○∗")


def _tidy_marks(text: str) -> str:
    """Merge emphasis runs that only a line break or a space separates, and
    drop runs that ended up empty."""
    for start, end in ((EM_START, EM_END), (STRONG_START, STRONG_END)):
        o, c = re.escape(start), re.escape(end)
        # OCR hands back an italic word in pieces, some of them read in the
        # roman face: runs a few stray letters apart are one run, and a run
        # that starts or stops mid-word is carried to the word's edge.
        text = re.sub(c + r"([^\s\x0e-\x11]{1,3})" + o, r"\1", text)
        text = re.sub(c + r"(\w+)", lambda m: m.group(1) + end, text)
        text = re.sub(r"(\w+)" + o, lambda m: start + m.group(1), text)
        text = re.sub(c + r"(\s*)" + o, r"\1", text)
        text = text.replace(start + end, "")
    return text


def _inline_marks_html(escaped: str) -> str:
    """Emphasis sentinels to tags, balanced within this one paragraph: a run
    left open by a paragraph split is closed, a stray close is dropped."""
    out = []
    open_tags: List[str] = []
    tags = {EM_START: ("em", True), EM_END: ("em", False),
            STRONG_START: ("strong", True), STRONG_END: ("strong", False)}
    for ch in escaped:
        if ch not in tags:
            out.append(ch)
            continue
        name, opening = tags[ch]
        if opening:
            if name not in open_tags:
                open_tags.append(name)
                out.append(f"<{name}>")
        elif name in open_tags:
            while open_tags:
                top = open_tags.pop()
                out.append(f"</{top}>")
                if top == name:
                    break
    while open_tags:
        out.append(f"</{open_tags.pop()}>")
    return "".join(out)


def _finalize_html_text(text: str) -> str:
    """
    Escape for HTML, then turn the inline footnote-marker sentinels
    (SUP_START/SUP_END, inserted during extraction around small/superscript
    digit spans) into a real <sup> tag. Doing this *after* html.escape()
    means the sentinel characters — which aren't touched by escaping —
    safely survive every text-cleaning step in between.
    """
    escaped = _inline_marks_html(html.escape(_tidy_marks(text)))
    escaped = re.sub(
        re.escape(SUP_START) + r"(\d{1,3})" + re.escape(SUP_END),
        lambda m: f'<sup class="footnote-ref" data-fnmark="{m.group(1)}">{m.group(1)}</sup>',
        escaped,
    )
    escaped = PAGE_MARK_RE.sub(_pagebreak_html, escaped)
    # Safety net: strip any other stray control character (e.g. an
    # un-split PARA_BREAK sentinel) — these are invalid in XML and would
    # otherwise crash the EPUB export at write time.
    escaped = CONTROL_CHARS_RE.sub(" ", escaped)
    return escaped


def _para_classes(block: RawBlock) -> List[str]:
    classes = []
    if block.muted:
        classes.append("text-muted")
    if block.italic:
        classes.append("text-italic")
    # A full, multi-line justified paragraph column is *itself* naturally
    # centered on a normally-margined page — that's not the same thing as a
    # short centered caption/label. Only treat genuinely short, single-line
    # blocks as ".text-center", or every ordinary paragraph gets wrongly
    # forced into centered/no-indent styling.
    is_single_line = "\n" not in block.text.strip() and PARA_BREAK not in block.text
    is_short = len(block.text.strip()) <= CAPTION_LIKE_MAX_CHARS
    if is_single_line and is_short and _is_centered(block):
        classes.append("text-center")
    return classes


def _para_html(text: str, classes: Optional[List[str]] = None) -> str:
    cls = f' class="{" ".join(classes)}"' if classes else ""
    return f"<p{cls}>{_finalize_html_text(text)}</p>"


def _blockquote_html(text: str) -> str:
    inner = "".join(_para_html(t) for t in text.split(PARA_BREAK) if t.strip())
    return f'<div class="academic-blockquote">{inner}</div>'


def _symbol_html(text: str) -> str:
    stripped = _sanitize_plain_text(text)
    is_safe = bool(stripped) and all((c in SAFE_ORNAMENT_CHARS or c.isspace()) for c in stripped)
    # An ornament glyph pulled from a custom embedded font (common for
    # decorative fleurons in academic press PDFs) usually has no equivalent
    # in an e-reader's built-in font and renders as a broken "tofu" box.
    # Fall back to a plain filled dot rather than shipping a broken glyph —
    # the paragraph/placement stays exactly the same either way.
    display = stripped if is_safe else "●"
    return f'<p class="symbol-line ornamental-divider">{html.escape(display)}</p>'


ROMAN_NUMERAL_ONLY_RE = re.compile(r"^[IVXLCDM]{1,6}\.?$", re.IGNORECASE)


def _split_toc_line(text: str) -> tuple:
    m = re.search(r"(\d{1,4})\s*$", text)
    page_no = m.group(1) if m else ""
    title = strip_dot_leaders(text[: m.start()] if m else text).strip(" .")
    return title, page_no


def _toc_entry_html(text: str) -> str:
    text = _sanitize_plain_text(text)
    title, page_no = _split_toc_line(text)
    if not title:
        return ""
    page_span = f'<span class="toc-page">{html.escape(page_no)}</span>' if page_no else ""
    return f'<p class="toc-entry"><span class="toc-title">{html.escape(title)}</span>{page_span}</p>'


def _toc_label_html(text: str) -> str:
    return f'<p class="toc-section-label">{html.escape(_sanitize_plain_text(text))}</p>'


def _append_toc_entry(text: str, toc_chapter: "Chapter", toc_entry_titles: List[str]) -> bool:
    """Render one contents entry into the İçindekiler chapter and record its
    title for the positional title-repair pass. Returns whether anything was
    emitted, so callers can tell a real entry from a line that cleaned away
    to nothing."""
    entry = _toc_entry_html(text)
    if not entry:
        return False
    toc_chapter.paragraphs.append(entry)
    entry_title, _ = _split_toc_line(_sanitize_plain_text(text))
    if entry_title:
        toc_entry_titles.append(entry_title)
    return True


def _consume_number_column_toc_line(
    cleaned: str, toc_chapter: "Chapter", toc_entry_titles: List[str]
) -> None:
    """Fold one line of a number-column contents page into the entry list.

    The page numbers live in their own column (`_toc_page_number_column()`),
    so they arrive as lines of their own — either all together after the
    titles or alternating with them. Either way they are print page numbers
    for an edition the EPUB does not reproduce, and nothing downstream can
    pair them back to a title without the geometry that extraction has
    already flattened away, so they are dropped rather than emitted as loose
    digits in the middle of the book.

    What remains is one title per line, except where a title wrapped. A
    wrapped fragment is recognisable without geometry: it continues in lower
    case ("Yeni Bir Görme ve Du" / "yusal Denge"), because a contents entry
    starts with a capital. Those rejoin the entry above instead of becoming
    entries of their own.
    """
    if _bare_page_number(cleaned) is not None:
        return
    if _matches_eyebrow(cleaned):
        # a section label ("1.BÖLÜM") heads the entries that follow rather
        # than being one of them, so it stays off the positional title list
        toc_chapter.paragraphs.append(_toc_label_html(cleaned))
        return
    if (
        _is_lowercase_continuation(cleaned)
        and toc_chapter.paragraphs
        and 'class="toc-entry"' in toc_chapter.paragraphs[-1]
        and toc_entry_titles
    ):
        previous = toc_chapter.paragraphs.pop()
        toc_entry_titles.pop()
        merged = f"{_toc_entry_plain_text(previous)} {cleaned}".strip()
        _append_toc_entry(merged, toc_chapter, toc_entry_titles)
        return
    _append_toc_entry(cleaned, toc_chapter, toc_entry_titles)


def _toc_entry_plain_text(entry_html: str) -> str:
    return html.unescape(_TAG_RE.sub(" ", entry_html)).strip()


def _is_lowercase_continuation(text: str) -> bool:
    """Does this line continue the one above rather than start something?

    The whole first word has to be lower case, not just its first letter.
    Testing the letter alone reads an OCR'd "1.BÖLÜM" — whose leading digit
    comes back as a lowercase "l" — as the tail of the previous title and
    swallows the section label into it.
    """
    first_token = text.strip().split(" ")[0] if text.strip() else ""
    if not any(c.isalpha() for c in first_token):
        return False
    return not any(c.isupper() for c in first_token)


_PAGEBREAK_HTML_RE = re.compile(r'<span epub:type="pagebreak"[^>]*></span>')


def _sized(p_html: str) -> int:
    """A paragraph's size for splitting a chapter: its HTML without the page
    marks, which are invisible. Counted, they moved the split points, and a
    paragraph open across a split is cut in two."""
    if "pagebreak" not in p_html:
        return len(p_html)
    return len(_PAGEBREAK_HTML_RE.sub("", p_html))


def _split_chapter_if_needed(chapter: Chapter, chapters: List[Chapter], next_index: List[int]) -> Chapter:
    if chapter.char_count <= MAX_CHAPTER_CHARS:
        return chapter
    running = 0
    split_para_idx = None
    for idx, p_html in enumerate(chapter.paragraphs):
        running += _sized(p_html)
        if running >= MAX_CHAPTER_CHARS:
            split_para_idx = idx
            break
    if split_para_idx is None:
        return chapter
    overflow_paragraphs = chapter.paragraphs[split_para_idx + 1:]
    chapter.paragraphs = chapter.paragraphs[: split_para_idx + 1]
    chapter.char_count = sum(_sized(p) for p in chapter.paragraphs)

    continuation = Chapter(
        id=f"ch_{next_index[0]:04d}",
        index=next_index[0],
        title=chapter.title,
        kind=chapter.kind,
        is_split_continuation=True,
    )
    continuation.paragraphs = overflow_paragraphs
    continuation.char_count = sum(_sized(p) for p in overflow_paragraphs)
    next_index[0] += 1
    chapters.append(continuation)
    return continuation


# ---------------------------------------------------------------------------
# Step 5: link in-text footnote markers to their endnote (post-process)
# ---------------------------------------------------------------------------
def _marker_id_part(marker: str) -> str:
    """The marker as it may appear in an XML id: stars are spelled out
    ("*" -> "star", "**" -> "star2") and anything else unsafe becomes "_".
    The id is also the href target, so it has to survive the builder's
    sanitising unchanged — "fn_ch_0007_*" was rewritten there and every
    link to a star note pointed nowhere."""
    if marker and set(marker) == {"*"}:
        return "star" if len(marker) == 1 else f"star{len(marker)}"
    return re.sub(r"[^A-Za-z0-9_.-]", "_", marker or "")


def _unique_footnote_id(chapter: Chapter, marker: str, taken: Optional[Set[str]] = None) -> str:
    """A footnote id that no other note in this chapter already uses.

    The id is built from the note's printed marker, and markers are not
    reliably unique within a chapter: letter-tracked digits get read as
    "1 6" so the marker parser takes "1", and a chapter that gathers notes
    from several pages can legitimately restart numbering. Two <aside>s
    with the same id is invalid XHTML that fails silently — every back-link
    lands on the first one and the reader never finds out.
    """
    base = f"fn_{chapter.id}_{_marker_id_part(marker)}"
    existing = taken if taken is not None else {fn.id for fn in chapter.footnotes}
    if base not in existing:
        return base
    n = 2
    while f"{base}_{n}" in existing:
        n += 1
    return f"{base}_{n}"


# Markup and character references are not prose, and the bare-digit fallback
# below has no way of telling. An apostrophe escapes to "&#x27;", whose "27"
# sits after a letter and before a semicolon — exactly the shape the fallback
# looks for. Matching it deletes the apostrophe ("1995'te" came out as
# "199527;te") and hangs a footnote reference off a word that never had one.
# Splitting on tags and entities first keeps the search inside real text.
_MARKUP_OR_ENTITY_RE = re.compile(r"(<[^>]*>|&(?:#[0-9]{1,7}|#[xX][0-9A-Fa-f]{1,6}|[A-Za-z][A-Za-z0-9]{1,31});)")


def _sub_outside_markup(pattern: "re.Pattern", replacement: str, html_text: str) -> "tuple[str, int]":
    """Replace the first match that does not fall inside markup.

    The match is still searched for in the whole fragment rather than in the
    text nodes one at a time, because the surrounding characters are part of
    what identifies a marker: a citation digit very often follows a closing
    quote, and that quote is "&quot;" by the time this runs. Cutting the
    fragment at entity boundaries would hide the quote from the pattern's
    lookbehind and lose the reference. Only matches that *overlap* markup are
    rejected.
    """
    blocked = [m.span() for m in _MARKUP_OR_ENTITY_RE.finditer(html_text)]
    for m in pattern.finditer(html_text):
        start, end = m.span()
        if any(start < b_end and b_start < end for b_start, b_end in blocked):
            continue
        return html_text[:start] + replacement + html_text[end:], 1
    return html_text, 0


# A star note run into the note before it on the same page: "… -Ed. ** Cellat".
_STARRED_NOTE_SPLIT = re.compile(r"(?<=[.!?)\]])\s+(\*{1,4})\s+(?=\S)")
# Candidate note references in a paragraph's HTML, in reading order:
#   1. a marker the extractor already raised as superscript,
#   2. a run of stars after a word ("sosyal-demokrasi*", "Komitesi**"),
#   3. digits run onto a word or its punctuation — how OCR reads a raised
#      note number ("tahlildir.5", "iyi3").
_NOTE_REF = re.compile(
    r'(?P<tagged><sup class="footnote-ref" data-fnmark="(?P<tmark>[^"]+)">(?P=tmark)</sup>)'
    r"|(?<=[^\W\d_]|[.,;:!?\"'’”)\]])(?P<stars>\*{1,4})(?=[\s.,;:!?\"'’”)\]]|<|$)"
    r"|(?<=[^\W\d_]|[.,;:!?\"'’”)\]])(?P<digits>\d{1,3})(?=[\s.,;:!?\"'’”)\]]|<|$)"
)
# How many notes ahead of the next unlinked one a reference may point: a
# note whose reference OCR lost is stepped over, not allowed to stall the rest.
NOTE_LINK_WINDOW = 4


def _split_starred_notes(chapter: Chapter) -> None:
    out: List[Footnote] = []
    for fn in chapter.footnotes:
        parts = _STARRED_NOTE_SPLIT.split(fn.text)
        if len(parts) == 1:
            out.append(fn)
            continue
        out.append(Footnote(id=fn.id, marker=fn.marker, text=parts[0].strip()))
        for k in range(1, len(parts) - 1, 2):
            marker, text = parts[k], parts[k + 1].strip()
            taken = {f.id for f in chapter.footnotes} | {f.id for f in out}
            out.append(Footnote(id=_unique_footnote_id(chapter, marker, taken), marker=marker, text=text))
    chapter.footnotes = out


def _footnote_ref_html(fn: Footnote) -> str:
    return (f'<sup class="footnote-ref" id="fnref_{fn.id}">'
            f'<a epub:type="noteref" href="#{fn.id}">{html.escape(fn.marker)}</a></sup>')


def _link_footnote_markers(chapter: Chapter) -> None:
    """Link each note reference in the text to its note.

    References and notes are both read in page order, so they are matched in
    order: each reference takes the next note bearing the same marker. A
    marker is not an identity — a book that numbers its notes per page has
    a "1" on every page, and one that marks them with stars has nothing but
    "*" and "**" — so looking a marker up across the chapter linked one note
    of each and left the rest dangling (2 of 110 in one book of the library).
    """
    if not chapter.footnotes:
        return
    _split_starred_notes(chapter)
    notes = chapter.footnotes
    linked: Set[str] = set()
    pointer = 0

    def take(marker: str) -> Optional[Footnote]:
        nonlocal pointer
        # A starred translator's note is often printed above the numbered
        # notes of its page while its reference comes after theirs: a star
        # looks back a few notes for one still waiting before looking ahead,
        # or a later star's note takes its place.
        if not marker.isdigit():
            for k in range(max(0, pointer - NOTE_LINK_WINDOW), pointer):
                if notes[k].marker == marker and notes[k].id not in linked:
                    return notes[k]
        for k in range(pointer, min(len(notes), pointer + NOTE_LINK_WINDOW)):
            if notes[k].marker == marker and notes[k].id not in linked:
                pointer = k + 1
                return notes[k]
        return None

    def link_html(fn: Footnote) -> str:
        linked.add(fn.id)
        return _footnote_ref_html(fn)

    for idx, para in enumerate(chapter.paragraphs):
        if "<figure" in para:
            continue

        def replace(m: "re.Match") -> str:
            if m.group("tagged"):
                fn = take(m.group("tmark"))
                return link_html(fn) if fn else m.group(0)
            marker = m.group("stars") or m.group("digits")
            # A bare number is only a reference when a note is waiting for
            # exactly that number; otherwise it is a number.
            fn = take(marker)
            return link_html(fn) if fn else m.group(0)

        chapter.paragraphs[idx] = _sub_text_outside_markup(_NOTE_REF, replace, para)

    # Whatever the ordered pass could not place — a reference read out of
    # order, or one further ahead than the window — is looked for the way a
    # lone note always was: the first raised marker for it anywhere in the
    # chapter, else the first bare number in prose. Order is a better guide
    # than a lookup, but losing a link because the order slipped is worse.
    for fn in notes:
        if fn.id in linked:
            continue
        tagged = re.compile(
            r'<sup class="footnote-ref" data-fnmark="' + re.escape(fn.marker) + r'">'
            + re.escape(fn.marker) + r"</sup>"
        )
        if _link_first(chapter, lambda para: tagged.subn(_footnote_ref_html(fn), para, count=1)):
            linked.add(fn.id)
            continue
        if not fn.marker.isdigit():
            continue
        bare = re.compile(r"(?<=[^\s\d>])" + re.escape(fn.marker) + r"(?=[\s.,;:!?\"'’”)]|<|$)")
        if _link_first(chapter, lambda para: _sub_outside_markup(bare, _footnote_ref_html(fn), para)):
            linked.add(fn.id)


def _link_first(chapter: Chapter, sub) -> bool:
    for idx, para in enumerate(chapter.paragraphs):
        if "<figure" in para:
            continue
        new_para, n = sub(para)
        if n:
            chapter.paragraphs[idx] = new_para
            return True
    return False


def _sub_text_outside_markup(pattern: "re.Pattern", repl, html_text: str) -> str:
    """re.sub over an HTML fragment, skipping matches that overlap a tag or a
    character reference — except the raised-marker <sup> the pattern itself
    names, which is matched whole.

    The search runs over the whole fragment so a reference after a closing
    quote ("dedi.&quot;5") still sees the quote; it just may not land inside
    "&#x27;", whose "27;" otherwise reads as note 27 (see _MARKUP_OR_ENTITY_RE).
    """
    blocked = [m.span() for m in _MARKUP_OR_ENTITY_RE.finditer(html_text)]
    out: List[str] = []
    pos = 0
    for m in pattern.finditer(html_text):
        start, end = m.span()
        if not m.groupdict().get("tagged") and any(start < b_end and b_start < end for b_start, b_end in blocked):
            continue
        out.append(html_text[pos:start])
        out.append(repl(m))
        pos = end
    out.append(html_text[pos:])
    return "".join(out)


TERMINAL_PUNCT_CHARS = set(".!?")
CLOSING_WRAP_CHARS = set("\"')\u2019\u201d]")


def _looks_paragraph_complete(text: str) -> bool:
    """Best-effort check for whether a paragraph's text ends at a real
    *sentence* boundary (so the next block should start a new paragraph)
    versus trailing off mid-sentence at a page break, or mid-enumeration at
    a semicolon/colon (so the next block is almost certainly a continuation
    of the same paragraph — academic prose is full of "X; Y; Z." lists and
    "as follows:" colons that are NOT paragraph breaks).

    Only '.', '!', '?' count as sentence-enders — colons and semicolons are
    deliberately excluded. A trailing closing quote/paren/bracket is peeled
    off first so we check the punctuation actually underneath it.
    """
    trimmed = re.sub(re.escape(SUP_START) + r"\d{1,3}" + re.escape(SUP_END) + r"\s*$", "", _strip_marks(text).strip())
    trimmed = trimmed.rstrip()
    while trimmed and trimmed[-1] in CLOSING_WRAP_CHARS:
        trimmed = trimmed[:-1].rstrip()
    if not trimmed:
        return True
    return trimmed[-1] in TERMINAL_PUNCT_CHARS


# A full stop that does not end a sentence: a Turkish ordinal ("20.
# yüzyılda") or a common abbreviation ("bkz. s. 45"). Only a line that goes
# on in lower case confirms it — "…sayısı 2500." may well end one.
NON_TERMINAL_STOP = re.compile(
    r"(?:\b\d{1,4}|\b(?:vs|vb|bkz|bk|krş|karş|s|ss|sf|yy|örn|ör|dr|prof|doç|çev|haz|"
    r"cf|pp|vol|ed|eds|etc|e\.g|i\.e|mr|mrs|ms|jr|st|no))\.$",
    re.IGNORECASE,
)


def _sentence_left_open(prev_text: str, next_text: str) -> bool:
    """Does prev_text stop mid-sentence, as next_text shows?"""
    if not _looks_paragraph_complete(prev_text):
        return True
    return bool(NON_TERMINAL_STOP.search(_strip_marks(prev_text).rstrip())) and _strip_marks(next_text)[:1].islower()


HYPHEN_BREAK_RE = re.compile(r"(?<=[^\W\d_])[-\u00ad](?=[\x0e-\x11]*$)")  # a letter directly followed by a trailing hyphen (ASCII or soft)


def _join_continuation(prev_text: str, next_text: str, hyphen_open: bool = False) -> str:
    """Join two continuation fragments. If the first one breaks off
    mid-word with a hyphen (e.g. "gö-" continuing as "türmekte"), the
    hyphen is a line-wrap artifact, not real punctuation — drop it and
    join with no space, exactly like repair_hyphenation() does within a
    single block.

    `hyphen_open` carries that same fact for a break the text can no
    longer show. A soft hyphen (U+00AD) is invisible by definition, so
    clean_text() deletes it — correctly, it must never be rendered — but
    that happens before this join, and then "kuram­" + "cılarından"
    reads as two complete words and gets joined with a space. The result
    is "kuram cılarından": a corrupted word, produced silently, in a
    book whose typesetter used soft hyphens for every single line break.
    The caller therefore records the evidence while it still exists.
    """
    if hyphen_open or HYPHEN_BREAK_RE.search(prev_text):
        return HYPHEN_BREAK_RE.sub("", prev_text) + next_text
    return f"{prev_text} {next_text}".strip()


# A soft hyphen at the very end of a block, with the word's remainder in the
# *next* block. repair_hyphenation() cannot see these: its pattern needs a
# newline, and a producer that emits one block per visual line never gives it
# one. Measured on an Acrobat ClearScan book: 542 line-final soft hyphens,
# 2 ASCII.
SOFT_HYPHEN_TAIL_RE = re.compile(r"(?<=[^\W\d_])" + "\u00ad" + r"[\x0e-\x11]*\s*$")


# A Kindle cover is 2560px tall; the page is rendered to that height (JPEG,
# so the session that carries it stays light) and capped for huge pages.
COVER_TARGET_HEIGHT = 2560
COVER_MAX_SCALE = 6.0


def _render_cover_image(doc: fitz.Document, page_index: int, matrix_scale: Optional[float] = None) -> Optional[str]:
    import base64

    if page_index < 0 or page_index >= doc.page_count:
        return None
    try:
        page = doc[page_index]
        if matrix_scale is None:
            matrix_scale = min(COVER_MAX_SCALE, max(2.0, COVER_TARGET_HEIGHT / max(page.rect.height, 1)))
        pix = page.get_pixmap(matrix=fitz.Matrix(matrix_scale, matrix_scale), alpha=False)
        return base64.b64encode(pix.tobytes("jpg", jpg_quality=88)).decode("ascii")
    except Exception:  # noqa: BLE001
        return None


def _render_region_image(
    doc: fitz.Document, page_index: int, bbox: List[float], matrix_scale: float = 3.0
) -> Optional[str]:
    """Same idea as _render_cover_image, cropped to one PDF Editor 'Görsel'
    region instead of the whole page — the bbox is in the same PDF-point
    coordinate space _block_center_in_region already uses."""
    import base64

    if page_index < 0 or page_index >= doc.page_count or len(bbox) != 4:
        return None
    try:
        page = doc[page_index]
        x0, x1 = sorted((bbox[0], bbox[2]))
        y0, y1 = sorted((bbox[1], bbox[3]))
        clip = fitz.Rect(x0, y0, x1, y1) & page.rect
        if clip.is_empty:
            return None
        pix = page.get_pixmap(matrix=fitz.Matrix(matrix_scale, matrix_scale), clip=clip)
        return base64.b64encode(pix.tobytes("png")).decode("ascii")
    except Exception:  # noqa: BLE001
        return None


def get_text_in_region(pdf_path: str, page_index: int, bbox: List[float]) -> str:
    """The plain text already sitting under a PDF Editor bounding box,
    before any correction is applied. Used two ways: shown next to an OCR
    candidate as 'here is what extraction currently produces here' so the
    person can judge whether OCR actually improves on it (never silently
    replacing it), and read internally when an OCR region is applied
    during conversion, to size the block it's replacing (see
    convert_pdf_to_chapters)."""
    doc = fitz.open(pdf_path)
    try:
        if page_index < 0 or page_index >= doc.page_count:
            return ""
        body_size = _detect_body_font_size(doc)
        blocks = _extract_page_blocks(doc[page_index], page_index, body_size)
        matched = [b.text for b in blocks if _block_center_in_region(b, [bbox])]
        return _sanitize_plain_text(" ".join(matched))
    finally:
        doc.close()


# ---------------------------------------------------------------------------
# PDF Editor tab (Step 1: page render + dimensions for the mask-lines tool)
# ---------------------------------------------------------------------------
# These operate directly on an uploaded PDF file path — the editor works
# BEFORE conversion, on the raw upload, independent of any conversion
# session. Deliberately standalone functions with no shared state, so they
# can't interfere with the existing conversion pipeline.
def get_page_dimensions(pdf_path: str, index: int) -> Optional[dict]:
    doc = fitz.open(pdf_path)
    try:
        if index < 0 or index >= doc.page_count:
            return None
        page = doc[index]
        return {
            "width_pt": page.rect.width,
            "height_pt": page.rect.height,
            "page_count": doc.page_count,
        }
    finally:
        doc.close()


def render_page_png(pdf_path: str, index: int, dpi: int = 150) -> Optional[bytes]:
    doc = fitz.open(pdf_path)
    try:
        if index < 0 or index >= doc.page_count:
            return None
        page = doc[index]
        scale = dpi / 72.0
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
        return pix.tobytes("png")
    finally:
        doc.close()


def get_page_preview_html(
    pdf_path: str, index: int, header_ratio: Optional[float] = None, footer_ratio: Optional[float] = None
) -> Optional[str]:
    """Approximate live-preview HTML for the PDF Editor's third panel —
    'roughly how will this page read once converted'. Reuses the exact
    same per-block classification (heading, blockquote, paragraph
    classes) the real converter uses, so it can't silently drift out of
    sync with actual conversion behavior. Deliberately does NOT do
    cross-page paragraph continuation, footnote linking, chapter
    boundaries, or TOC detection — those are inherently whole-document,
    stateful operations that don't make sense for one isolated page. This
    is an approximation to sanity-check formatting while editing, not a
    substitute for running the real conversion.
    """
    doc = fitz.open(pdf_path)
    try:
        if index < 0 or index >= doc.page_count:
            return None
        body_size = _detect_body_font_size(doc)
        page = doc[index]
        blocks = _extract_page_blocks(page, index, body_size)
        # Which margin-band blocks are furniture is a whole-document
        # question, so the preview has to ask it of the whole document —
        # otherwise the page shown in the editor and the page that ends up
        # in the EPUB disagree about what gets deleted.
        running = _running_elements_for_document(
            doc, pdf_path, body_size, header_ratio, footer_ratio
        )
        html_parts: List[str] = []
        for block in blocks:
            if _should_drop_as_furniture(block, running, header_ratio, footer_ratio):
                continue
            cleaned_raw = repair_hyphenation(block.text)
            cleaned_raw = clean_text(cleaned_raw)
            if not cleaned_raw:
                continue

            heading_text = _is_heading(block, body_size)
            if heading_text:
                tag = "h1" if not html_parts else "h2"
                html_parts.append(f"<{tag}>{html.escape(_sanitize_plain_text(heading_text))}</{tag}>")
                continue

            if is_symbol_line(cleaned_raw):
                html_parts.append(_symbol_html(cleaned_raw))
                continue

            if _is_academic_blockquote(block):
                html_parts.append(_blockquote_html(cleaned_raw))
                continue

            classes = _para_classes(block)
            for part in cleaned_raw.split(PARA_BREAK):
                part = part.strip()
                if part:
                    html_parts.append(_para_html(part, classes))

        if not html_parts:
            return "<p><em>(Bu sayfada gösterilecek metin bulunamadı — görsel bir sayfa olabilir.)</em></p>"
        return "".join(html_parts)
    finally:
        doc.close()


def scan_pages_for_issues(
    pdf_path: str, header_ratio: Optional[float] = None, footer_ratio: Optional[float] = None
) -> List[dict]:
    """Whole-document scan for the PDF Editor's 'jump to problem' tools —
    thumbnail badges, the 'next problem' navigation button, and the
    auto-scan review queue. Reuses the exact same _is_heading /
    _looks_garbled logic the real converter uses, so a page flagged here
    is guaranteed to be one the converter would also flag — no separate,
    possibly-inconsistent detection rules. Read-only: never touches the
    PDF or any conversion state."""
    doc = fitz.open(pdf_path)
    try:
        body_size = _detect_body_font_size(doc)
        issues: List[dict] = []
        all_blocks = {i: _extract_page_blocks(doc[i], i, body_size) for i in range(doc.page_count)}
        running = _detect_running_elements(all_blocks, header_ratio, footer_ratio)
        for i in range(doc.page_count):
            blocks = all_blocks[i]
            for block in blocks:
                if _should_drop_as_furniture(block, running, header_ratio, footer_ratio):
                    continue
                heading_text = _is_heading(block, body_size)
                if heading_text and _looks_garbled(heading_text):
                    issues.append(
                        {
                            "page_index": i,
                            "kind": "garbled_heading",
                            "detail": heading_text[:80],
                            "bbox": [round(v, 2) for v in block.bbox],
                        }
                    )
                    break  # one flag per page is enough for navigation purposes
        return issues
    finally:
        doc.close()


def get_hyphen_flags(pdf_path: str, index: int) -> Optional[List[dict]]:
    """For one page, find every line-ending word that breaks mid-word with
    a hyphen (e.g. "çarşaf-") — exactly the pattern HYPHEN_BREAK_RE / the
    real conversion engine's cross-block continuation logic treats as "join
    with the next line/page, dropping the hyphen". Purely a read-only
    visual confirmation tool: it doesn't affect conversion, just shows
    which words *will* be rejoined so line-wrap hyphens can be told apart
    from genuine hyphenated compound words or em-dash usage at a glance.

    Uses PyMuPDF's own word tokenizer (page.get_text("words")) rather than
    re-deriving word boundaries from raw characters — it already gives
    clean per-word bounding boxes in the same PDF-point coordinate space
    page-info reports, so no extra unit conversion is needed downstream.
    """
    doc = fitz.open(pdf_path)
    try:
        if index < 0 or index >= doc.page_count:
            return None
        page = doc[index]
        page_height = page.rect.height
        header_threshold = max(page_height * HEADER_MARGIN_RATIO, HEADER_MARGIN_FLOOR_PT)
        footer_threshold = max(page_height * FOOTER_MARGIN_RATIO, FOOTER_MARGIN_FLOOR_PT)
        footer_y = page_height - footer_threshold

        words = page.get_text("words")  # (x0, y0, x1, y1, text, block_no, line_no, word_no)
        if not words:
            return []

        last_word_per_line: dict = {}
        for w in words:
            x0, y0, x1, y1, text, block_no, line_no, word_no = w
            key = (block_no, line_no)
            if key not in last_word_per_line or word_no > last_word_per_line[key][7]:
                last_word_per_line[key] = w

        flags = []
        for w in last_word_per_line.values():
            x0, y0, x1, y1, text, block_no, line_no, word_no = w
            if y0 < header_threshold or y1 > footer_y:
                continue  # inside the cropped header/footer band — not real body text
            if HYPHEN_BREAK_RE.search(text):
                flags.append({"bbox": [round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)], "text": text})
        return flags
    finally:
        doc.close()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def convert_pdf_to_chapters(
    pdf_path: str,
    excluded_pages: Optional[Set[int]] = None,
    cover_page_index: Optional[int] = None,
    image_pages: Optional[Set[int]] = None,
    toc_pages: Optional[Set[int]] = None,
    header_ratio: Optional[float] = None,
    footer_ratio: Optional[float] = None,
    excluded_text_regions: Optional[Dict[int, List[List[float]]]] = None,
    image_regions: Optional[List[dict]] = None,
    ocr_regions: Optional[List[dict]] = None,
    auto_figures: bool = True,
    progress: Optional[Callable[[str, int, int], None]] = None,
) -> ConversionResult:
    """
    progress: told (stage, done, total) as the conversion goes — the
    reader's words for the stage, pages done of the pages to read — so the
    app can show where a long book is. Never consulted for anything.

    header_ratio / footer_ratio: override HEADER_MARGIN_RATIO /
    FOOTER_MARGIN_RATIO for this conversion — this is what makes the PDF
    Editor's mask-line drag tool actually affect the real output, instead
    of being preview-only.

    excluded_text_regions: {page_index: [[x0,y0,x1,y1], ...]} in PDF-point
    coordinates — any block whose center point falls inside one of these
    is skipped entirely during extraction. This is the PDF Editor's
    "Hariç Tut" bounding-box action: a manual escape hatch for stray
    inline content (e.g. a translator's note in an unrecognized format)
    that no automatic footnote/heading heuristic catches, confirmed on a
    real book where "• Çevirmen: ..." text spliced itself into the middle
    of a word because it didn't match any existing footnote pattern.

    image_regions: [{"page_index": int, "bbox": [x0,y0,x1,y1]}, ...] — the
    PDF Editor's "Görsel" bounding-box action. Each becomes a <figure> in
    the reading flow at the point its position implies (not a whole
    separate page/chapter the way a page-level "Görsel" mode is): the
    region is cropped and embedded as its own image, any text block whose
    center falls inside the same bbox is suppressed from the ordinary
    paragraph stream (so it isn't extracted twice, once as picture and
    once as prose), and a short, closely-adjacent block right below the
    image is bound as its caption *only* when the spatial evidence is
    strong — position, alignment and size all agree — otherwise the
    region ships with no caption rather than guessing wrong, and a
    warning says so.

    ocr_regions: [{"page_index": int, "bbox": [...], "text": str,
    "confidence": Optional[int], "source_text": Optional[str]}, ...] — the
    PDF Editor's "OCR" bounding-box action, already approved by the person
    in the editor (the "Onayla" step) before it ever reaches this
    function; there is no unapproved-OCR path here; text-then-approve
    happens entirely upstream. Applying one never touches the source
    PDF (nothing here can — this pipeline is read-only) or discards the
    correction: it works exactly like an excluded-text region for the
    ordinary extraction path (the original, possibly-garbled blocks under
    that bbox are removed from the block stream), except a synthetic block
    carrying the *approved* text is substituted in their place, inheriting
    the original blocks' size so a garbled heading OCR'd back to legible
    text is still detected as a heading rather than falling to body text.
    Reversing an approved OCR is `regionsByPage` bookkeeping in the editor
    (remove the region, reconvert) — the PDF itself was never modified, so
    plain extraction is always one delete away.

    auto_figures: find the figures a page carries alongside its body text and
    embed them the same way a hand-drawn "Görsel" region is embedded. Without
    this every such figure is silently dropped, because block extraction only
    keeps text blocks. A hand-drawn region always wins over a detected one.
    """
    excluded_pages = excluded_pages or set()
    image_pages = image_pages or set()
    toc_pages = toc_pages or set()
    excluded_text_regions = excluded_text_regions or {}
    image_regions_by_page: Dict[int, List[dict]] = {}
    for region in image_regions or []:
        image_regions_by_page.setdefault(region["page_index"], []).append(dict(region))
    ocr_regions_by_page: Dict[int, List[dict]] = {}
    for region in ocr_regions or []:
        ocr_regions_by_page.setdefault(region["page_index"], []).append(dict(region))
    regions_pages_unhandled = set(image_regions_by_page) | set(ocr_regions_by_page)
    doc = fitz.open(pdf_path)
    warnings: List[dict] = []
    body_size = _detect_body_font_size(doc)
    # Whether a full-page raster is the scanner's substrate, and which images
    # are repeated furniture, are both whole-document questions — they have
    # to be settled before any single page is judged.
    auto_figure_profile = _build_auto_figure_profile(
        doc,
        [doc[i].get_text("text") for i in range(doc.page_count)],
        enabled=auto_figures,
    )
    auto_figures_embedded = 0
    auto_figures_uncaptioned = 0

    metadata = doc.metadata or {}
    # the front pages' own text, picture pages included, for the title page
    front_texts = [doc[i].get_text("text") for i in range(min(TITLE_PAGE_SEARCH, doc.page_count))]
    detected_title = (metadata.get("title") or "").strip() or "Untitled Book"
    detected_author = (metadata.get("author") or "").strip() or "Unknown"

    if cover_page_index is None:
        cover_page_index = next(
            (p for p in range(doc.page_count) if p not in excluded_pages), 0
        )
    cover_image_base64 = _render_cover_image(doc, cover_page_index)

    chapters: List[Chapter] = []
    next_index = [0]

    current = Chapter(id="ch_0000", index=0, title="Ön Bilgiler", kind="frontmatter")
    chapters.append(current)
    next_index[0] = 1

    seen_first_heading = False
    pending_eyebrow: Optional[str] = None
    pending_eyebrow_page: Optional[int] = None
    just_started_chapter_countdown = 0
    chapter_is_empty_since_heading = False
    # Geometry of the last heading line read, so the next one can be tested
    # for being its continuation rather than merged on faith.
    wrapped_title_prev: Optional[dict] = None
    wrapped_title_lines = 0
    collecting_notes = False
    note_marker_pending: Optional[str] = None
    footnote_counter = 0
    # The chapter's last note, if it carried its own printed number: an
    # unnumbered small block right after it is that note's next line.
    last_marked_note: Optional[Footnote] = None
    last_note_page: Optional[int] = None
    toc_chapter: Optional[Chapter] = None
    toc_entry_titles: List[str] = []

    # A paragraph is held open (not yet flushed into chapter.paragraphs)
    # until we know whether the *next* block continues it — this is what
    # lets a sentence that's cut off by a PDF page break rejoin its
    # paragraph instead of starting a spurious new, indented one.
    open_para: Optional[dict] = None
    last_aside: Optional[dict] = None  # the page-aside line last emitted

    def close_open_paragraph() -> None:
        nonlocal open_para
        if open_para is None:
            return
        if CLOSE_TRACE is not None:
            # diagnostics only: which line of this function closed a paragraph
            CLOSE_TRACE.append((sys._getframe(1).f_lineno, open_para["text"][-60:]))
        chapter = open_para["chapter"]
        classes = open_para["classes"]
        # "Centered" is judged on the block that opened the paragraph, which
        # can be one short line at the top of a page that the next blocks
        # then continue. The finished paragraph is what gets styled, and a
        # paragraph longer than a caption is running prose, not a centered
        # line — measured: 21 full paragraphs on Dazai were set centered.
        if "text-center" in classes and len(PAGE_MARK_RE.sub("", open_para["text"])) > CAPTION_LIKE_MAX_CHARS:
            classes = [c for c in classes if c != "text-center"]
        if open_para.get("kind") == "academic":
            p_html = _blockquote_html(open_para["text"])
        else:
            p_html = _para_html(open_para["text"], classes)
        chapter.paragraphs.append(p_html)
        chapter.char_count += _sized(p_html)
        # Figures that arrived while this sentence was still running are
        # set after it, the way a reader meets them.
        for held in open_para.get("held", []):
            chapter.paragraphs.append(held)
            chapter.char_count += len(held)
        open_para = None

    def _place_figure(figure_html: str) -> "Chapter":
        """Where a figure goes: after the paragraph it interrupts if that
        paragraph has not finished its sentence, otherwise right here."""
        if open_para is not None and not _looks_paragraph_complete(open_para["text"]):
            open_para.setdefault("held", []).append(figure_html)
            return open_para["chapter"]
        close_open_paragraph()
        current.paragraphs.append(figure_html)
        current.char_count += len(figure_html)
        return current

    def _figure_owner() -> "Chapter":
        if open_para is not None and not _looks_paragraph_complete(open_para["text"]):
            return open_para["chapter"]
        return current

    def _flush_plate(page_num: int, regions: List[dict], blocks: List[RawBlock]) -> None:
        nonlocal chapter_is_empty_since_heading
        owner = _figure_owner()
        ids = []
        for region in regions:
            img_b64 = _render_region_image(
                doc, page_num, region["bbox"],
                matrix_scale=AUTO_FIGURE_RENDER_SCALE if region.get("_auto") else 3.0,
            )
            if not img_b64:
                continue
            image_id = f"{owner.id}_img{len(owner.images) + 1}"
            owner.images.append({"id": image_id, "base64": img_b64})
            ids.append(image_id)
        if not ids:
            return
        _place_figure(_plate_html(ids, _plate_parts(blocks, body_size)))
        chapter_is_empty_since_heading = False

    def _flush_image_region(page_num: int, region: dict) -> None:
        # A figure is a block-level element in its own right, not a
        # continuation of whatever prose was flowing above it.
        nonlocal chapter_is_empty_since_heading, auto_figures_uncaptioned
        owner = _figure_owner()
        is_auto = bool(region.get("_auto"))
        img_b64 = _render_region_image(
            doc,
            page_num,
            region["bbox"],
            matrix_scale=AUTO_FIGURE_RENDER_SCALE if is_auto else 3.0,
        )
        if not img_b64:
            _add_warning(
                warnings,
                f"PDF sayfa {page_num + 1}'deki işaretli görsel bölgesi render edilemedi.",
                SEVERITY_WARNING,
            )
            return
        image_id = f"{owner.id}_img{len(owner.images) + 1}"
        owner.images.append({"id": image_id, "base64": img_b64})
        caption_text = region.get("_caption_text")
        if caption_text:
            caption_html = f"<figcaption>{html.escape(caption_text)}</figcaption>"
        else:
            caption_html = ""
            # Leaving a figure uncaptioned is the safe default when the
            # spatial evidence isn't strong enough to bind one — but it's
            # still worth a nudge to check by hand, not a silent gap.
            # Detected figures are counted and reported once for the book
            # instead: a 300-page illustrated book would otherwise bury every
            # other warning under hundreds of identical notes.
            if is_auto:
                auto_figures_uncaptioned += 1
            else:
                _add_warning(
                    warnings,
                    f"PDF sayfa {page_num + 1}'deki görsel için bir başlık/açıklama otomatik "
                    "eşleştirilemedi — gerekirse Live Editor'de elle ekleyin.",
                    SEVERITY_INFO,
                )
        figure_html = (
            f'<figure class="region-figure"><img src="images/{image_id}.png" alt="Görsel"/>'
            f"{caption_html}</figure>"
        )
        _place_figure(figure_html)
        chapter_is_empty_since_heading = False

    total_pages = doc.page_count

    # Read every text page's blocks up front. Two reasons: whether a
    # margin-band block is furniture or content is a whole-document
    # question (see _detect_running_elements), and doing it here means the
    # blocks are reconstructed once instead of once per pass.
    tell = progress or (lambda stage, done, total: None)
    page_blocks: Dict[int, List[RawBlock]] = {}
    for page_num in range(total_pages):
        if page_num % 10 == 0:
            tell("Sayfalar okunuyor", page_num, total_pages)
        if page_num in excluded_pages or page_num in image_pages:
            continue
        page_blocks[page_num] = _extract_page_blocks(doc[page_num], page_num, body_size)
    tell("Kitabın yapısı çıkarılıyor", 0, 0)
    rescaled_pages = _normalize_page_scales(page_blocks, body_size)
    # A cover or title page shown as a picture (Görsel) still prints the
    # book's title and author: on a scan it is the first thing the page
    # review marks so, and the title went unread ("Untitled Book"). Its text
    # layer is read for the title and author, and for nothing else.
    title_page_blocks = dict(page_blocks)
    for page_num in sorted(image_pages):
        if page_num < TITLE_PAGE_SEARCH and page_num not in excluded_pages:
            title_page_blocks[page_num] = _extract_page_blocks(doc[page_num], page_num, body_size)

    running_elements = _detect_running_elements(page_blocks, header_ratio, footer_ratio)
    prose_pages = _pages_that_set_prose(page_blocks, body_size)
    note_size = _book_note_size(page_blocks, body_size, prose_pages)
    # The printed page each PDF page is, where its margins say: the text a
    # page sets first carries that page's mark, and a Kindle shows and cites
    # the book's own page numbers.
    printed = printed_pages(_detect_folios(page_blocks), total_pages,
                            {p for p, blocks in page_blocks.items() if blocks})
    pages_marked: Set[int] = set()
    style = _build_style_profile(page_blocks, body_size)
    academic_enabled = _set_off_quotes_are_distinct(page_blocks, prose_pages, body_size)

    # When the book prints a contents page that can be read and resolved
    # against its pages, that page decides where chapters start and what
    # they are called; type size alone is only the fallback.
    def body_blocks_of(p: int) -> List[RawBlock]:
        return [
            b for b in page_blocks.get(p, [])
            if not _should_drop_as_furniture(b, running_elements, header_ratio, footer_ratio)
        ]

    subheading_styles, running_like_lines = _subheading_styles(page_blocks, body_size, body_blocks_of)
    toc_plan = _plan_from_printed_toc(doc, toc_pages, page_blocks, body_blocks_of, body_size)
    # The PDF's own bookmarks are the other witness to the book's structure.
    # They are written by whoever made the PDF and spelled right, where the
    # printed contents page has to be read off a page — and on a scan, read
    # wrong ("Why Do You Are The Fear?"). So they win unless the printed page
    # lists clearly more: a contents page can be deeper than the bookmarks.
    outline_plan = _plan_from_outline(doc, toc_pages, page_blocks, body_blocks_of, body_size)
    if outline_plan.active and (
        not toc_plan.active or len(outline_plan.entries) >= OUTLINE_PREFERRED_SHARE * len(toc_plan.entries)
    ):
        toc_plan = outline_plan
    toc_rendered = False
    dropped_furniture = 0
    # A printed index is a list, read line by line into a chapter of its own.
    index_pages = _index_pages(doc, page_blocks, body_blocks_of, set(toc_pages))
    index_chapter: Optional[Chapter] = None
    index_pending: List[list] = []      # [kind, text, page], written out on the index's last page

    for page_num in range(total_pages):
        if page_num % 10 == 0:
            tell("Paragraflar diziliyor", page_num, total_pages)
        if page_num in excluded_pages:
            continue

        if page_num in image_pages:
            # "Görsel" means: show this page exactly as printed, where it is
            # printed, and read nothing off it. A designed title page, a
            # cover or a back cover is the picture; extracting its words
            # put a back-cover blurb at the end of the last chapter and a
            # barcode among the notes. The open paragraph is left open, so a
            # sentence running across the page still reads as one.
            img_b64 = _render_cover_image(doc, page_num, matrix_scale=150 / 72)
            if img_b64:
                chapters.append(Chapter(
                    id=f"ch_{next_index[0]:04d}",
                    index=next_index[0],
                    title=f"Görsel Sayfa {page_num + 1}",
                    kind="image",
                    image_base64=img_b64,
                ))
                next_index[0] += 1
            else:
                _add_warning(
                    warnings,
                    f"Görsel olarak işaretlenen sayfa render edilemedi: PDF sayfa {page_num + 1}",
                    SEVERITY_CRITICAL,
                )
            continue

        page = doc[page_num]
        page_text = page.get_text("text")

        progress = page_num / max(1, total_pages - 1)
        if (
            page_num not in toc_pages
            and page_num not in index_pages
            and open_para is None
            and progress >= INDEX_PAGE_MIN_CHECK_PROGRESS
            and _is_index_page(page_text)
        ):
            _add_warning(
                warnings, f"Skipped probable index/Fihrist page at PDF page {page_num + 1}", SEVERITY_INFO
            )
            continue

        blocks = page_blocks[page_num]
        body_blocks = [
            b for b in blocks
            if not _should_drop_as_furniture(b, running_elements, header_ratio, footer_ratio)
        ]
        dropped_furniture += len(blocks) - len(body_blocks)
        page_lines = [ln for b in body_blocks for ln in re.split(r"[\n\x04]", b.text)]

        if page_num in index_pages:
            close_open_paragraph()
            lines = _index_lines(body_blocks, printed.get(page_num))
            if index_chapter is None:
                # the contents page's entry for the index, if it lists one
                role = next((toc_plan.roles[id(b)] for b in body_blocks
                             if toc_plan.active and id(b) in toc_plan.roles
                             and toc_plan.roles[id(b)]["role"] in ("title", "anchor")), None)
                info = toc_plan.entries[role["entry"]] if role else None
                printed_title = next((t for _, _, t in lines[:3] if _is_index_title(t)), None)
                if info:
                    title = info["title"]
                elif printed_title:
                    title = INDEX_TITLE_WORDS.get(_index_title_key(printed_title)) or turkish_title_case(printed_title)
                else:
                    title = "Dizin"
                _link_footnote_markers(current)
                current = Chapter(id=f"ch_{next_index[0]:04d}", index=next_index[0], title=title)
                chapters.append(current)
                next_index[0] += 1
                if info:
                    current.toc_path = list(info["path"])
                    info["chapter_id"] = current.id
                index_chapter = current
                seen_first_heading = True
                collecting_notes = False
                chapter_is_empty_since_heading = False
            entries = _index_entries(lines, body_size, index_pending[-1] if index_pending else None)
            index_pending.extend(entry + [page_num] for entry in entries)
            if page_num == max(index_pages):
                for kind, text, page in index_pending:
                    if page in printed and page not in pages_marked:
                        marked = _with_page_mark(text, printed[page], continuing=False)
                        if marked is not None:
                            text = marked
                            pages_marked.add(page)
                    p_html = _index_entry_html(kind, text)
                    current.paragraphs.append(p_html)
                    current.char_count += _sized(p_html)
                index_pending = []
            continue

        if page_num in toc_pages or (open_para is None and _is_toc_page(page_lines)):
            close_open_paragraph()
            if toc_chapter is None:
                toc_chapter = Chapter(
                    id=f"ch_{next_index[0]:04d}", index=next_index[0], title="İçindekiler", kind="toc"
                )
                chapters.append(toc_chapter)
                next_index[0] += 1
            if toc_plan.active:
                if not toc_rendered:
                    toc_chapter.paragraphs.extend(_toc_tree_html(toc_plan))
                    toc_rendered = True
                continue
            title_prefix_buffer: List[str] = []
            sticky_label: Optional[str] = None
            # `page_lines` comes from blocks whose lines have already been
            # joined into paragraphs, which is right for prose and wrong for
            # a contents page: the entries are a list, and joining them
            # leaves one line holding every title and another holding every
            # page number. Read the page's own lines back for the
            # number-column form, which is the one that depends on them.
            # The dot-leader form keeps its entry per line either way, so it
            # stays on the blocks and their furniture filtering.
            raw_lines = [ln for ln in page_text.split("\n") if ln.strip()]
            number_column = _toc_page_number_column(raw_lines)
            # An approved OCR correction on a contents page used to be
            # dropped with a warning, because the contents branch never read
            # the region list. Contents pages are exactly where a garbled
            # scan is most likely to be fixed by hand, so the correction is
            # applied here the same way the prose path applies it: whatever
            # sits under the box leaves, the approved text takes its place.
            # The number-column form reads the page's raw lines instead; those
            # come in the same order as PyMuPDF's own line records, so the
            # same substitution is done on the records, with the approved
            # text taking the place of the first line it covers.
            toc_ocr = ocr_regions_by_page.get(page_num) or []
            if toc_ocr and number_column:
                rebuilt: List[str] = []
                pending = list(toc_ocr)
                for blk in doc[page_num].get_text("dict").get("blocks", []):
                    for ln in blk.get("lines", []):
                        text = "".join(s.get("text", "") for s in ln.get("spans", []))
                        if not text.strip():
                            continue
                        lb = ln.get("bbox")
                        hit = next(
                            (r for r in toc_ocr
                             if r["bbox"][0] <= (lb[0] + lb[2]) / 2 <= r["bbox"][2]
                             and r["bbox"][1] <= (lb[1] + lb[3]) / 2 <= r["bbox"][3]),
                            None,
                        )
                        if hit is None:
                            rebuilt.append(text)
                        elif hit in pending:
                            pending.remove(hit)
                            rebuilt.extend(t for t in hit["text"].split("\n") if t.strip())
                # A box over nothing still says what the person wants there.
                for r in pending:
                    rebuilt.extend(t for t in r["text"].split("\n") if t.strip())
                raw_lines = rebuilt
                if not image_regions_by_page.get(page_num):
                    regions_pages_unhandled.discard(page_num)
            if toc_ocr and not number_column:
                toc_blocks = [
                    b for b in body_blocks
                    if not any(_block_center_in_region(b, [r["bbox"]]) for r in toc_ocr)
                ]
                for r in toc_ocr:
                    toc_blocks.append(RawBlock(
                        text=r["text"], size=body_size, bbox=tuple(r["bbox"]),
                        page_num=page_num,
                        page_width=doc[page_num].rect.width,
                        page_height=doc[page_num].rect.height,
                    ))
                toc_blocks.sort(key=lambda b: (b.bbox[1], b.bbox[0]))
                page_lines = [ln for b in toc_blocks for ln in re.split(r"[\n\x04]", b.text)]
                if not image_regions_by_page.get(page_num):
                    regions_pages_unhandled.discard(page_num)
            # On a number-column page no line carries its own page number,
            # so nothing below would ever recognise an entry and every
            # title would sit in title_prefix_buffer until the page ended.
            for ln in (raw_lines if number_column else page_lines):
                cleaned = clean_text(ln)
                if not cleaned or TOC_HEADING.match(cleaned):
                    continue
                if number_column:
                    _consume_number_column_toc_line(
                        cleaned, toc_chapter, toc_entry_titles
                    )
                elif looks_like_toc_line(cleaned):
                    raw_title, _ = _split_toc_line(cleaned)
                    if title_prefix_buffer:
                        full_text = " ".join(title_prefix_buffer + [cleaned])
                        title_prefix_buffer = []
                    elif ROMAN_NUMERAL_ONLY_RE.match(raw_title) and sticky_label:
                        # "Üçüncü Hatırat" (no page number of its own) was
                        # followed by "I ... 62", which consumed it via the
                        # buffer above — but "II ... 89" right after has no
                        # buffer left. sticky_label keeps the parent title
                        # available for every bare-roman-numeral sub-entry
                        # until a real new heading appears.
                        full_text = f"{sticky_label} {cleaned}"
                    else:
                        full_text = cleaned
                        sticky_label = None
                    entry = _toc_entry_html(full_text)
                    if entry:
                        toc_chapter.paragraphs.append(entry)
                        entry_title, _ = _split_toc_line(_sanitize_plain_text(full_text))
                        if entry_title:
                            toc_entry_titles.append(entry_title)
                elif _matches_eyebrow(cleaned):
                    # a genuine section label ("BİRİNCİ BÖLÜM", "[SUNUŞ YERİNE]")
                    # stays on its own line rather than merging into the title
                    if title_prefix_buffer:
                        toc_chapter.paragraphs.append(
                            _toc_entry_html(" ".join(title_prefix_buffer))
                        )
                        title_prefix_buffer = []
                    toc_chapter.paragraphs.append(_toc_label_html(cleaned))
                    sticky_label = None
                elif len(cleaned) < 90:
                    # most likely the first physical line of a title that
                    # wrapped across two lines in the PDF, with the dot
                    # leader + page number only on the next line — buffer it
                    # instead of rendering (and losing) it on its own
                    title_prefix_buffer.append(cleaned)
                    sticky_label = cleaned
            if title_prefix_buffer:
                # The buffer holds real titles, so a page whose last entry
                # never met its page number — the final line of the contents,
                # or a title the leader failed to extract — must still emit
                # what it was holding rather than let the page end on it.
                _append_toc_entry(
                    " ".join(title_prefix_buffer), toc_chapter, toc_entry_titles
                )
            continue

        page_excluded_regions = excluded_text_regions.get(page_num)
        page_ocr_regions = ocr_regions_by_page.get(page_num) or []
        manual_image_regions = image_regions_by_page.get(page_num) or []
        # Hand-drawn regions first: the index lookup below resolves to the
        # first match, so on any overlap the person's own mark wins. The
        # copies matter — the list in image_regions_by_page is live, and
        # appending to it would leak this page's figures into the next.
        page_image_regions = [dict(r) for r in manual_image_regions]
        if auto_figures_embedded < AUTO_FIGURE_MAX_PER_BOOK:
            detected = _auto_figure_regions(
                page,
                page_num,
                auto_figure_profile,
                manual_image_regions,
                page_excluded_regions,
                page_ocr_regions,
                body_blocks,
            )
            room = AUTO_FIGURE_MAX_PER_BOOK - auto_figures_embedded
            page_image_regions.extend(detected[:room])
            auto_figures_embedded += len(detected[:room])
        # Deliberately not discarded for a detected figure: this set drives
        # the "your hand-drawn mark could not be applied" warning, and an
        # automatic find must never be what silences it.
        regions_pages_unhandled.discard(page_num)
        # How much real, extractable text each image region's own interior
        # swallowed — read by the caption pre-pass below regardless of
        # which branch actually populates it.
        image_hit_chars: List[int] = [0 for _ in page_image_regions]
        inside_image: List[tuple] = []  # (region index, block) hidden by a region

        if page_ocr_regions or page_image_regions:
            # A region's job here is the same one excluded_text_regions
            # already does — decide which blocks leave the ordinary
            # paragraph stream — plus, for OCR, putting a replacement back
            # in. Doing both by walking body_blocks once keeps an
            # approved-OCR'd heading and a Görsel region on the same page
            # from fighting over the same block.
            ocr_hit_sizes: List[List[float]] = [[] for _ in page_ocr_regions]
            kept_blocks: List[RawBlock] = []
            for b in body_blocks:
                ocr_idx = next(
                    (i for i, r in enumerate(page_ocr_regions) if _block_center_in_region(b, [r["bbox"]])),
                    None,
                )
                if ocr_idx is not None:
                    ocr_hit_sizes[ocr_idx].append(b.size)
                    continue
                img_idx = next(
                    (i for i, r in enumerate(page_image_regions) if _block_center_in_region(b, [r["bbox"]])),
                    None,
                )
                if img_idx is not None:
                    # How much real, extractable text this region's own
                    # interior swallowed — see the caption pre-pass below.
                    image_hit_chars[img_idx] += len(b.text.strip())
                    inside_image.append((img_idx, b))
                    continue
                kept_blocks.append(b)
            for i, region in enumerate(page_ocr_regions):
                sizes = ocr_hit_sizes[i]
                x0, y0, x1, y1 = region["bbox"]
                # Inherit the size of whatever this replaces — a garbled
                # HEADING OCR'd back to legible text must still measure as
                # a heading, not fall to body size just because the fix
                # came from an image crop instead of the text layer. A
                # region with no text under it at all (OCR run on a pure
                # picture) has nothing to inherit, so it defaults to body
                # size and reads as an ordinary paragraph.
                kept_blocks.append(RawBlock(
                    text=region["text"],
                    size=(max(sizes) if sizes else body_size),
                    bbox=(x0, y0, x1, y1),
                    page_num=page_num,
                    page_width=page.rect.width,
                    page_height=page.rect.height,
                ))
            kept_blocks.sort(key=lambda b: (b.bbox[1], b.bbox[0]))
            body_blocks = kept_blocks

        # Caption binding is a pre-pass over the page's final block list
        # (after OCR substitution, before the main loop consumes any of
        # it) rather than a lookahead inside the loop below, so the
        # decision is made once, from the whole page's layout, instead of
        # block-by-block as the loop happens to reach them.
        caption_consumed_ids: Set[int] = set()
        for region_idx, region in enumerate(page_image_regions):
            # A real picture has little or no extractable text of its own —
            # a photo, a diagram, a plate. A region whose own interior
            # swallowed a substantial run of real text is someone marking
            # *prose* as a picture (an edge case that works — the text is
            # correctly suppressed and embedded as a cropped image either
            # way — but the block right after it is the next sentence of
            # that same prose, not a caption, and binding it as one reads
            # as wrong in exactly the way this whole heuristic exists to
            # avoid). Skip the caption attempt entirely in that case rather
            # than let position/alignment/size agree on the wrong answer.
            if image_hit_chars[region_idx] > 40:
                continue
            x0, y0, x1, y1 = region["bbox"]
            region_width = x1 - x0
            best: Optional[tuple] = None
            for block in body_blocks:
                if id(block) in caption_consumed_ids:
                    continue
                gap = block.bbox[1] - y1
                # Strong evidence, all required at once — position
                # (directly below, close enough it reads as attached),
                # alignment (its width sits under the image, not a
                # full-column paragraph merely starting nearby) and size
                # (never heading-sized, that's the next section starting,
                # not a caption). Any one alone is exactly the kind of
                # single-measurement guess PROJECT_CONTEXT warns against;
                # failing any one leaves the region uncaptioned rather
                # than binding on a guess.
                if gap < -2 or gap > max(body_size * 1.5, 20):
                    continue
                overlap = min(block.bbox[2], x1) - max(block.bbox[0], x0)
                if region_width <= 0 or overlap / region_width < 0.5:
                    continue
                if block.size > body_size + 0.5:
                    continue
                # A chapter's title set under its opening drawing is the
                # title, not the drawing's caption.
                if toc_plan.active and id(block) in toc_plan.roles:
                    continue
                text_len = len(block.text.strip())
                if not (0 < text_len <= 400):
                    continue
                if best is None or gap < best[0]:
                    best = (gap, block)
            if best is not None:
                caption_consumed_ids.add(id(best[1]))
                region["_caption_text"] = _sanitize_plain_text(clean_text(best[1].text))

        pending_images = sorted(page_image_regions, key=lambda r: r["bbox"][1])
        img_ptr = 0

        # Notes begin where the page's text ends, not at a fixed share of
        # the page: an epigraph page's notes started above the bottom 30%
        # and were read into the last quotation. Small type below the last
        # line of text counts as notes when at least one of those lines
        # opens with a note number.
        notes_from: Optional[float] = None
        text_bottom = max(
            (b.bbox[3] for b in body_blocks
             if b.size > body_size - FOOTNOTE_SIZE_DELTA and len(b.text.strip()) >= 20),
            default=None,
        )
        if text_bottom is not None:
            below = [
                b for b in body_blocks
                if b.bbox[1] >= text_bottom
                and b.size <= body_size - FOOTNOTE_SIZE_DELTA
                and b.bbox[1] > b.page_height * 0.45
                and not _is_attribution(b, style, body_size)
            ]
            if any(_split_note_marker(clean_text(b.text))[0] for b in below):
                notes_from = min(b.bbox[1] for b in below)

        # A plate: pictures and their captions on a page that sets no prose.
        # A page that opens a chapter (a drawn title page) is not one: laid
        # out as a plate, its title never reached the chapter it starts.
        opens_chapter = toc_plan.active and any(id(b) in toc_plan.roles for b in body_blocks)
        if (seen_first_heading and page_num not in prose_pages and pending_images
                and all(r.get("_auto") for r in pending_images) and not opens_chapter):
            plate_blocks = [
                b for b in body_blocks
                if not (page_excluded_regions and _block_center_in_region(b, page_excluded_regions))
            ]
            # A picture's raster often runs on under the plate's own title
            # and numbers, which are type, not picture. Lines in the lower
            # part of a picture's box are handed back to the caption and
            # the picture is cut above them.
            for idx, b in inside_image:
                region = page_image_regions[idx]
                x0, y0, x1, y1 = region["bbox"]
                if b.bbox[1] >= y0 + (y1 - y0) * 0.8 and b.size < body_size:
                    region["bbox"] = [x0, y0, x1, min(y1, b.bbox[1] - 1)]
                    plate_blocks.append(b)
            _flush_plate(page_num, pending_images, plate_blocks)
            continue

        for block in body_blocks:
            while img_ptr < len(pending_images) and pending_images[img_ptr]["bbox"][1] <= block.bbox[1]:
                _flush_image_region(page_num, pending_images[img_ptr])
                img_ptr += 1
            if id(block) in caption_consumed_ids:
                continue
            if page_excluded_regions and _block_center_in_region(block, page_excluded_regions):
                continue
            cleaned_raw = repair_hyphenation(block.text)
            block_ends_mid_word = bool(SOFT_HYPHEN_TAIL_RE.search(cleaned_raw))
            cleaned_raw = clean_text(cleaned_raw)
            if not cleaned_raw:
                continue

            # --- endnote-collection mode -------------------------------
            if NOTE_SECTION_HEADING.match(cleaned_raw):
                close_open_paragraph()
                collecting_notes = True
                note_marker_pending = None
                continue

            if collecting_notes:
                heading_candidate = _is_heading(block, body_size)
                if heading_candidate and not BARE_MARKER_LINE.match(cleaned_raw):
                    collecting_notes = False  # a new chapter starts; fall through below
                else:
                    bare = BARE_MARKER_LINE.match(cleaned_raw)
                    if bare:
                        note_marker_pending = _match_marker(bare)
                        continue
                    footnote_counter += 1
                    # The note's own printed marker wins. It is the one the
                    # body's reference carries, so it is the only one that can
                    # link; a marker left pending by a preceding marker-only
                    # block is a fallback for layouts that set the two apart,
                    # and a running counter is the last resort for notes that
                    # print no marker at all.
                    marker, fn_text = _split_note_marker(cleaned_raw)
                    if marker is None:
                        marker = note_marker_pending or str(footnote_counter)
                        fn_text = cleaned_raw
                    note_marker_pending = None
                    current.footnotes.append(
                        Footnote(id=_unique_footnote_id(current, marker), marker=marker,
                                 text=_clean_footnote_text(fn_text))
                    )
                    chapter_is_empty_since_heading = False
                    continue

            # --- fallback: classic bottom-of-page small-font footnote ---
            # Before the first chapter heading there is nothing a note
            # could hang off. The pages up there are the title page, the
            # copyright page and the imprint, set in small type all the
            # way down, so "small text at the foot of the page" picks up
            # the publisher's address and printing certificate number
            # rather than a note.
            if (
                seen_first_heading
                and page_num in prose_pages
                and (
                    _is_footnote_zone(block, body_size)
                    or (notes_from is not None and block.bbox[1] >= notes_from
                        and block.size <= body_size - FOOTNOTE_SIZE_DELTA)
                )
                # This branch is a guess from position and size alone, with
                # nothing marking the page as an actual notes section — the
                # weakest of the footnote heuristics, and the one that read
                # a back cover's printed ISBN ("9 789944 7 5 7461", small
                # type, low on the page) as a note with no citation in it at
                # all. A real annotation is always words about something;
                # digits with no letter anywhere are the book's own
                # packaging, not a note, whichever page they sit on.
                and any(ch.isalpha() for ch in cleaned_raw)
                # (a note running on from the page before opens mid-sentence,
                # in lower case, and stays a note whatever size a scan gives it)
                and not (note_size is not None and block.size > note_size + NOTE_SIZE_MARGIN
                         and _split_note_marker(cleaned_raw)[0] is None
                         and not OCR_NOTE_ONE.match(cleaned_raw)
                         and not _strip_marks(cleaned_raw).lstrip(" \"'“‘(«")[:1].islower())
            ):
                # Deliberately NOT closing open_para here — a footnote is
                # an aside, not a real content-boundary. If the paragraph
                # above it is mid-hyphen-break (very common: footnote
                # markers sit right at the bottom of the page, exactly
                # where a paragraph is most likely to be cut off for a
                # page break), closing it here would discard the pending
                # continuation entirely, leaving the second half of the
                # word to start a bogus new paragraph on its own.
                marker, fn_text = _split_note_marker(cleaned_raw)
                if marker is None:
                    ocr_one = OCR_NOTE_ONE.match(cleaned_raw)
                    if ocr_one and last_note_page != page_num:
                        marker, fn_text = "1", cleaned_raw[ocr_one.end():]
                if (marker is None and last_marked_note is not None and current.footnotes
                        and current.footnotes[-1] is last_marked_note
                        and not NOTE_SYMBOL_START.match(cleaned_raw)):
                    last_marked_note.text = _clean_footnote_text(
                        _join_continuation(last_marked_note.text, cleaned_raw, False)
                    )
                    continue
                footnote_counter += 1
                marked = marker is not None
                if marker is None:
                    marker = str(footnote_counter)
                note = Footnote(id=_unique_footnote_id(current, marker), marker=marker,
                                text=_clean_footnote_text(fn_text))
                current.footnotes.append(note)
                last_marked_note = note if marked else None
                last_note_page = page_num
                chapter_is_empty_since_heading = False
                continue

            # A section label belongs to the title printed under it, so it
            # waits only as long as that page does. Carried across a page
            # break it stops being a label and starts being a stray line
            # looking for somewhere to land — which is how a "2.BÖLÜM"
            # read off an undetected contents list ended up captioning the
            # foreword four pages later. It is still a line the book prints,
            # so it goes back into the chapter it was printed in rather
            # than being deleted on the way past.
            if pending_eyebrow is not None and block.page_num != pending_eyebrow_page:
                stray = _para_html(pending_eyebrow)
                current.paragraphs.append(stray)
                current.char_count += len(stray)
                pending_eyebrow = None
                pending_eyebrow_page = None

            # --- structure from the printed contents page ----------------
            if toc_plan.active:
                role = toc_plan.roles.get(id(block))
                if role is not None and role["role"] == "subheading":
                    close_open_paragraph()
                    h_html = f'<h2 class="subheading">{html.escape(_sanitize_plain_text(role["text"]))}</h2>'
                    current.paragraphs.append(h_html)
                    current.char_count += len(h_html)
                    chapter_is_empty_since_heading = False
                    continue
                if role is not None:
                    if role["role"] in ("title", "anchor"):
                        info = toc_plan.entries[role["entry"]]
                        close_open_paragraph()
                        if (not seen_first_heading and current.kind == "frontmatter"
                                and not current.paragraphs and not current.footnotes
                                and chapters and chapters[-1] is current):
                            current.title = info["title"]
                            current.kind = "chapter"
                        else:
                            _link_footnote_markers(current)
                            current = Chapter(
                                id=f"ch_{next_index[0]:04d}", index=next_index[0], title=info["title"]
                            )
                            chapters.append(current)
                            next_index[0] += 1
                        current.eyebrow = info["eyebrow"]
                        current.byline = info["byline"]
                        current.toc_path = list(info["path"])
                        current.opener = dict(info["opener"]) if info.get("opener") else None
                        info["chapter_id"] = current.id
                        seen_first_heading = True
                        collecting_notes = False
                        chapter_is_empty_since_heading = True
                        wrapped_title_prev = None
                        wrapped_title_lines = 0
                        just_started_chapter_countdown = 2
                    # A bookmark whose title the page did not print in a
                    # readable form starts its chapter at this block; the
                    # block is the chapter's first text — unless it is the
                    # unreadable title itself.
                    if role["role"] == "anchor" and not _is_heading(block, body_size):
                        role = None
                    else:
                        # labels, bylines and title continuations are carried
                        # by the chapter they belong to
                        continue
                # A heading the contents page does not list is a heading
                # inside a section, not the start of a new one.
                inner_heading = _is_heading(block, body_size)
                if inner_heading:
                    close_open_paragraph()
                    h_html = f'<h2 class="subheading">{html.escape(_sanitize_plain_text(inner_heading))}</h2>'
                    current.paragraphs.append(h_html)
                    current.char_count += len(h_html)
                    chapter_is_empty_since_heading = False
                    continue

            # --- a section heading in the book's own sub-heading style ---
            if (subheading_styles and seen_first_heading and _subheading_key(block) in subheading_styles
                    and _repeated_head_key(block) not in running_like_lines):
                nxt_block = next((b for b in sorted(body_blocks, key=lambda b: b.bbox[1])
                                  if b.bbox[1] > block.bbox[1]), None)
                if _could_be_subheading(block, nxt_block, body_size):
                    close_open_paragraph()
                    h_html = (f'<h2 class="subheading">'
                              f'{html.escape(" ".join(_block_plain(block).split()))}</h2>')
                    current.paragraphs.append(h_html)
                    current.char_count += len(h_html)
                    chapter_is_empty_since_heading = False
                    continue

            # --- heading / eyebrow --------------------------------------
            heading_text = _is_heading(block, body_size) if not toc_plan.active else None
            if heading_text:
                if pending_eyebrow is None and _matches_eyebrow(heading_text):
                    # Close first: the label is held back rather than
                    # emitted, and if it is later released as a stray line
                    # it has to land after the text that preceded it, not
                    # in front of a paragraph still being accumulated.
                    close_open_paragraph()
                    pending_eyebrow = heading_text
                    pending_eyebrow_page = block.page_num
                    continue

                close_open_paragraph()

                if (
                    chapter_is_empty_since_heading
                    and not pending_eyebrow
                    and _continues_wrapped_title(
                        block, wrapped_title_prev, current.title, heading_text, wrapped_title_lines
                    )
                ):
                    # Nothing was added to the chapter since the last
                    # heading, and this block sits one line below it in the
                    # same type on the same page — the next physical line of
                    # the SAME wrapped title (e.g. "NEWTON DÖNEMİNDE
                    # İKTİSAT," / "TEKNOLOJİ VE FİZİK"). Merge instead of
                    # spawning an empty chapter that later gets dropped.
                    current.title = f"{current.title} {heading_text}".strip()
                    wrapped_title_prev = {"page": block.page_num, "size": block.size, "y1": block.bbox[3]}
                    wrapped_title_lines += 1
                    continue

                title_text = heading_text
                eyebrow_text = pending_eyebrow
                pending_eyebrow = None
                pending_eyebrow_page = None

                if (not seen_first_heading and not current.paragraphs and not current.footnotes
                        and chapters and chapters[-1] is current):
                    current.title = title_text
                    current.kind = "chapter"
                else:
                    _link_footnote_markers(current)
                    current = Chapter(id=f"ch_{next_index[0]:04d}", index=next_index[0], title=title_text)
                    chapters.append(current)
                    next_index[0] += 1
                seen_first_heading = True
                collecting_notes = False
                chapter_is_empty_since_heading = True
                wrapped_title_prev = {"page": block.page_num, "size": block.size, "y1": block.bbox[3]}
                wrapped_title_lines = 1
                if eyebrow_text:
                    current.eyebrow = eyebrow_text
                just_started_chapter_countdown = 2
                continue

            # --- a page that is not part of the reading flow -------------
            # A plate spread, an imprint, a column of captions: the page
            # sets no prose of its own (_pages_that_set_prose), so nothing
            # on it continues the sentence that was running when it
            # arrived, and nothing on the page after it starts a new one.
            # Emitting these lines through the ordinary path does both:
            # the caption gets glued onto the tail of the interrupted
            # paragraph, and the prose that resumes overleaf is stranded
            # as a fresh paragraph beginning in lower case, mid-sentence.
            # So they are emitted beside the open paragraph rather than
            # into it - the same treatment a footnote already gets, and
            # for the same reason: an aside is not a content boundary.
            #
            # Front matter is excluded for the same reason the footnote
            # branch excludes it: before the first heading there is no
            # reading flow to interrupt, and the pages up there - the
            # author bio, the copyright page - are set small all the way
            # down, so "sets no text at body size" is true of them without
            # meaning any of this. Their lines are ordinary prose and need
            # the continuation machinery like any other.
            if seen_first_heading and page_num not in prose_pages:
                for sub_text in cleaned_raw.split(PARA_BREAK):
                    sub_text = sub_text.strip()
                    if not sub_text:
                        continue
                    classes = _para_classes(block) + [PAGE_ASIDE_CLASS]
                    # A note that runs onto a second line is still one note:
                    # "…, available at" / "www.theatlantic.com/…" came out as
                    # two entries, the second starting in lower case.
                    if (last_aside is not None and last_aside["chapter"] is current
                            and current.paragraphs and current.paragraphs[-1] is last_aside["html"]
                            and _strip_marks(sub_text)[:1].islower()
                            # an index entry ends on its page numbers, not mid-sentence
                            and not _strip_marks(last_aside["text"]).rstrip()[-1:].isdigit()
                            and _sentence_left_open(last_aside["text"], sub_text)):
                        joined = last_aside["text"].rstrip()
                        tail = joined.rsplit(None, 1)[-1]
                        if joined.endswith("/") or (joined.endswith("-") and "/" in tail):
                            joined += sub_text          # an address broken at the line end
                        elif joined.endswith("-"):
                            joined = joined[:-1] + sub_text  # a word broken at the line end
                        else:
                            joined += " " + sub_text
                        p_html = _para_html(joined, last_aside["classes"])
                        current.char_count += len(p_html) - len(current.paragraphs[-1])
                        current.paragraphs[-1] = p_html
                        last_aside.update(text=joined, html=p_html)
                        continue
                    p_html = _para_html(sub_text, classes)
                    current.paragraphs.append(p_html)
                    current.char_count += len(p_html)
                    last_aside = {"chapter": current, "text": sub_text, "classes": classes, "html": p_html}
                chapter_is_empty_since_heading = False
                current = _split_chapter_if_needed(current, chapters, next_index)
                continue

            # --- a section label that body text arrives under -------------
            # A part divider set on its own page ("2. BÖLÜM") that runs
            # straight into prose is not a label waiting for a title — it IS
            # the title. Nothing ever consumed a pending eyebrow that no
            # heading followed, so the divider evaporated and the part's
            # opening prose was filed under the previous section.
            # See EYEBROW_PROMOTION_* for what counts as arriving prose.
            if (
                pending_eyebrow is not None
                and block.size >= body_size * EYEBROW_PROMOTION_MIN_SIZE_RATIO
                and len(cleaned_raw) >= EYEBROW_PROMOTION_MIN_CHARS
                and not is_mostly_punctuation_or_digits(cleaned_raw)
            ):
                close_open_paragraph()
                if not seen_first_heading and not current.paragraphs and not current.footnotes:
                    current.title = pending_eyebrow
                    current.kind = "chapter"
                else:
                    _link_footnote_markers(current)
                    current = Chapter(
                        id=f"ch_{next_index[0]:04d}", index=next_index[0], title=pending_eyebrow
                    )
                    chapters.append(current)
                    next_index[0] += 1
                pending_eyebrow = None
                pending_eyebrow_page = None
                seen_first_heading = True
                wrapped_title_prev = None
                wrapped_title_lines = 0

            # --- ornamental divider right after a heading ---------------
            if is_symbol_line(cleaned_raw):
                close_open_paragraph()
                p_html = _symbol_html(cleaned_raw)
                current.paragraphs.append(p_html)
                current.char_count += len(p_html)
                just_started_chapter_countdown = max(just_started_chapter_countdown, 1)
                continue

            if just_started_chapter_countdown > 0 and block.italic and len(cleaned_raw) <= 70 and _is_centered(block):
                close_open_paragraph()
                p_html = f'<p class="chapter-byline">{_finalize_html_text(cleaned_raw)}</p>'
                current.paragraphs.append(p_html)
                current.char_count += len(p_html)
                just_started_chapter_countdown -= 1
                continue
            just_started_chapter_countdown = max(0, just_started_chapter_countdown - 1)

            # --- academic blockquote / regular paragraph -----------------
            # A quotation's source, set flush right under it.
            if _is_attribution(block, style, body_size) and _follows_quotation(current, open_para, block):
                close_open_paragraph()
                # A note number printed after the name, whatever size the
                # OCR gave it, is a note reference.
                source = TRAILING_NOTE_NUMBER.sub(
                    lambda m: SUP_START + m.group(1) + SUP_END, cleaned_raw.rstrip()
                )
                p_html = _para_html(source, ["attribution"])
                current.paragraphs.append(p_html)
                current.char_count += len(p_html)
                chapter_is_empty_since_heading = False
                continue

            quote = _is_quote_block(block, style, body_size)
            # A centered, narrow block is a set-off quotation. It goes through
            # the same joining as any paragraph: written out block by block,
            # a quotation broken over lines or pages came out one box per line.
            academic = academic_enabled and not quote and _is_academic_blockquote(block)
            kind = "quote" if quote else "academic" if academic else "text"
            classes = _para_classes(block) + (["quote-block"] if quote else [])
            first_top = block.line_boxes[0][1] if block.line_boxes else block.bbox[1]
            for sub_idx, sub_text in enumerate(cleaned_raw.split(PARA_BREAK)):
                sub_text = sub_text.strip()
                if not sub_text:
                    continue
                # In a book that marks paragraphs with space, the next line
                # at ordinary line pitch is the same paragraph, whether or
                # not the line before it happened to end a sentence.
                next_line = (
                    style["spaced"]
                    and open_para is not None
                    and open_para.get("page") == block.page_num
                    and 0 < first_top - open_para.get("last_top", -1e9) <= style["pitch"] * 1.3
                )
                same_flow = (
                    sub_idx == 0
                    and open_para is not None
                    and open_para["chapter"] is current
                )
                continues_word = bool(open_para and open_para.get("hyphen_open")) or _strip_marks(sub_text)[:1].islower()
                can_continue = (
                    same_flow
                    and open_para.get("kind", "text") == kind
                    and (next_line or _sentence_left_open(open_para["text"], sub_text))
                    # Centered short lines are lines by design — a credits
                    # page, a dedication, a poem — and run on only where the
                    # words themselves do.
                    and (kind != "academic" or continues_word)
                )
                # A sentence left open — mid-word, or with no end — and taken
                # up by a line starting in lower case is one paragraph,
                # whatever each half was classified as. A line set in a
                # quotation face, or indented, was enough to cut it in two:
                # 109 of 109 broken paragraphs in one book of the library.
                crosses_kind = (
                    same_flow
                    and not can_continue
                    and (open_para.get("hyphen_open") or _sentence_left_open(open_para["text"], sub_text))
                    and _strip_marks(sub_text)[:1].islower()
                )
                if can_continue or crosses_kind:
                    if crosses_kind and len(sub_text) > len(PAGE_MARK_RE.sub("", open_para["text"])):
                        # the paragraph is what most of it is
                        open_para["kind"], open_para["classes"] = kind, classes
                    if block.page_num in printed and block.page_num not in pages_marked:
                        # a word broken over the page is marked once it is whole
                        whole = not (open_para.get("hyphen_open") or HYPHEN_BREAK_RE.search(open_para["text"]))
                        marked = _with_page_mark(sub_text, printed[block.page_num], continuing=whole)
                        if marked is not None:
                            sub_text = marked
                            pages_marked.add(block.page_num)
                    open_para["text"] = _join_continuation(
                        open_para["text"], sub_text, open_para.get("hyphen_open", False)
                    )
                    open_para["hyphen_open"] = False
                else:
                    if CLOSE_TRACE is not None and open_para is not None:
                        CLOSE_TRACE.append(("why", sub_idx, open_para["chapter"] is current,
                                            open_para.get("kind", "text"), kind, sub_text[:30]))
                    close_open_paragraph()
                    if block.page_num in printed and block.page_num not in pages_marked:
                        marked = _with_page_mark(sub_text, printed[block.page_num], continuing=False)
                        if marked is not None:
                            sub_text = marked
                            pages_marked.add(block.page_num)
                    open_para = {
                        "chapter": current, "text": sub_text,
                        "classes": classes, "hyphen_open": False, "kind": kind,
                    }
            # Remember, while the evidence still exists, that this block
            # ended mid-word. clean_text() has already deleted the soft
            # hyphen that said so, and the next block cannot recover it.
            if open_para is not None:
                open_para["hyphen_open"] = block_ends_mid_word
                open_para["page"] = block.page_num
                open_para["last_top"] = block.line_boxes[-1][1] if block.line_boxes else block.bbox[1]
            chapter_is_empty_since_heading = False
            current = _split_chapter_if_needed(current, chapters, next_index)

        # Any image region below every text block on the page (or the
        # whole page's only content) never triggered the flush inside the
        # loop above — catch it here before moving to the next page.
        while img_ptr < len(pending_images):
            _flush_image_region(page_num, pending_images[img_ptr])
            img_ptr += 1

    close_open_paragraph()
    # an index whose last page never came round (it is always the last of
    # index_pages, so this is a guard, not a path)
    for kind, text, _ in index_pending:
        p_html = _index_entry_html(kind, text)
        current.paragraphs.append(p_html)
        current.char_count += _sized(p_html)
    _link_footnote_markers(current)

    # A page that never reached the ordinary text-processing branch — it
    # was excluded, rendered whole-page as an image, or read as a
    # contents/index page — never got the chance to apply a Görsel/OCR
    # region drawn on it. That is a correction the person made and asked
    # for; silently ignoring it is exactly the kind of gap this whole
    # feature exists to close, so it surfaces as a warning instead.
    for page_num in sorted(regions_pages_unhandled):
        _add_warning(
            warnings,
            f"PDF sayfa {page_num + 1}'de işaretlenmiş bir Görsel/OCR bölgesi uygulanamadı "
            "— sayfa dışlanmış, tam sayfa görsel ya da içindekiler/dizin sayfası olarak işlendi.",
            SEVERITY_WARNING,
        )

    if auto_figures_embedded:
        detail = (
            f" {auto_figures_uncaptioned} tanesine başlık/açıklama eşleştirilemedi."
            if auto_figures_uncaptioned
            else ""
        )
        _add_warning(
            warnings,
            f"Sayfa içindeki {auto_figures_embedded} görsel otomatik bulunup metne "
            f"yerleştirildi.{detail}",
            SEVERITY_INFO,
        )

    # A chapter that ends up with nothing under it is a line the book really
    # prints — a title-page line, a part divider — and dropping it outright
    # deletes that text with no trace. Hand its title to the chapter that
    # follows, as the eyebrow line above that chapter's own title, so the
    # words stay somewhere a reader can see them.
    kept: List[Chapter] = []
    orphan_title: Optional[str] = None
    for chapter in chapters:
        if not (chapter.paragraphs or chapter.footnotes or chapter.kind == "image"):
            if orphan_title is None and chapter.title and chapter.title.strip():
                orphan_title = chapter.title.strip()
            continue
        if orphan_title and chapter.kind != "image" and not chapter.eyebrow:
            chapter.eyebrow = orphan_title
        orphan_title = None
        kept.append(chapter)
    chapters = kept

    # The imprint is not a chapter. A title page prints the book's title and
    # its author in the same large type, so both read as headings and the
    # second opens a chapter — which the copyright page then fills with the
    # ISBN, the printer's certificate number and the publisher's phone
    # number. On a Kindle that is the first thing in the contents list,
    # under the author's name.
    #
    # What separates it from a real chapter is not its title or its length
    # but that it carries almost no running prose: the imprint's lines come
    # off a page that sets none, which PAGE_ASIDE_CLASS already marks, and
    # what is left is a stray credit line from the title page. Measured on
    # the corpus, every such chapter holds under 35 characters of unmarked
    # text, and every real one holds hundreds. The same test also catches a
    # garbled contents heading whose entries were read as a one-line
    # chapter. Only the run before the book's first real chapter is
    # considered, so a mid-book plate section keeps its own entry, and the
    # text is moved rather than dropped — it stays in the front matter,
    # where the book prints it.
    def _is_all_aside(chapter: Chapter) -> bool:
        if chapter.kind != "chapter" or not chapter.paragraphs:
            return False
        prose = sum(
            len(re.sub(r"<[^>]+>", "", p))
            for p in chapter.paragraphs
            if PAGE_ASIDE_CLASS not in p and "region-figure" not in p
        )
        return prose < FRONT_MATTER_STRAY_PROSE_CHARS

    # A leading front-matter section the book never filled — every page up
    # there was marked Görsel, or there is no front matter at all — is not a
    # section, and must not open the reader's menu with an empty page.
    chapters = [c for c in chapters if c.kind != "frontmatter" or c.paragraphs or c.footnotes]

    host = next((c for c in chapters if c.kind == "frontmatter"), None)
    # With the contents page in charge, a leading chapter exists because the
    # book lists it; nothing is second-guessed away.
    in_front_matter = not toc_plan.active
    folded: List[Chapter] = []
    for chapter in chapters:
        if in_front_matter and _is_all_aside(chapter):
            # The title and eyebrow are lines the book prints too — they
            # stop being a contents entry, not text.
            lines = [
                _para_html(t.strip()) for t in (chapter.eyebrow, chapter.title) if t and t.strip()
            ]
            if host is None:
                # A book whose front matter had nothing else in it lost the
                # empty "Ön Bilgiler" section earlier; this becomes it.
                chapter.paragraphs = lines + chapter.paragraphs
                chapter.title, chapter.eyebrow, chapter.kind = "Ön Bilgiler", None, "frontmatter"
                host = chapter
                folded.append(chapter)
                continue
            host.paragraphs.extend(lines)
            host.paragraphs.extend(chapter.paragraphs)
            host.char_count += chapter.char_count
            host.footnotes.extend(chapter.footnotes)
            continue
        # Plates and the contents page sit among the front matter without
        # ending it; the first chapter with real prose does.
        if chapter.kind == "chapter":
            in_front_matter = False
        folded.append(chapter)
    chapters = folded

    _run_content_accounting(doc, chapters, excluded_pages, image_pages, warnings)

    chapter_warnings: List[dict] = []
    if not chapters:
        _add_warning(
            warnings, "No extractable body text was found — check that the PDF is not a scanned image.",
            SEVERITY_CRITICAL,
        )
    else:
        if toc_plan.active:
            _link_toc_entries(toc_chapter, toc_plan, {c.id for c in chapters})
            for title in toc_plan.unmatched:
                _add_warning(
                    warnings,
                    f"İçindekiler'deki '{title}' başlığı kitabın sayfalarında bulunamadı — "
                    "bu bölüm ayrı başlamıyor olabilir, bölüm listesini kontrol edin.",
                    SEVERITY_WARNING,
                )
        elif toc_entry_titles:
            _apply_toc_title_corrections(chapters, toc_entry_titles, warnings)
        _sync_split_continuation_titles(chapters)
        _run_publish_readiness_checks(
            chapters, [] if toc_plan.active else toc_entry_titles, warnings, chapter_warnings
        )

    # Language is read off the text that actually ships, not off the PDF's
    # metadata — a PDF's /Lang is absent far more often than not, and when
    # present it frequently describes the typesetting software's locale
    # rather than the book.
    guess = detect_language(_TAG_RE.sub(" ", " ".join(
        p for c in chapters for p in c.paragraphs
    )))
    if not guess.confident:
        _add_warning(
            warnings,
            f"Kitabın dili kesin olarak belirlenemedi; '{guess.code}' varsayıldı. "
            "Gerekirse üst bilgilerden düzeltin.",
            SEVERITY_INFO,
        )

    doc.close()
    # A scan's misreadings the book itself spells right elsewhere
    # ("ookchin, M." where the text quotes Bookchin; "20ll'den").
    word_counts = build_word_counts(_TAG_RE.sub(" ", p) for c in chapters for p in c.paragraphs)
    word_forms = capitalised_forms(word_counts)
    words_repaired = 0
    for c in chapters:
        for k, p in enumerate(c.paragraphs):
            fixed = repair_text(p, word_counts, word_forms)
            if fixed != p:
                c.paragraphs[k] = fixed
                words_repaired += 1

    # A PDF whose metadata names nothing, or names it wrongly, still prints
    # its title page.
    skip_front = set(toc_pages) | set(excluded_pages)
    inferred_title, inferred_author = _infer_title_and_author(
        page_blocks, body_size, running_elements, skip_front, front_texts=front_texts)
    # a pictured cover's text layer is a scanner's reading of display type
    # ("> Bir Adım İleri"), so it is read only where neither the text pages
    # nor a sound metadata title name the book
    meta_title = (metadata.get("title") or "").strip()
    meta_title_sound = bool(meta_title) and not JUNK_METADATA_TITLE.search(meta_title) \
        and meta_title != meta_title.lower()
    if not inferred_title and not meta_title_sound and len(title_page_blocks) > len(page_blocks):
        inferred_title, cover_author = _infer_title_and_author(
            title_page_blocks, body_size, running_elements, skip_front, front_texts=front_texts)
        inferred_author = inferred_author or cover_author
        if inferred_title:
            inferred_title = inferred_title.lstrip(" >•·*-–—|.,:;") or None
    # a title that is a person's name, honorific and all, is the author set
    # largest ("Dr. Hikmet Kıvılcımlı" over "Tarih Devrim Sosyalizm")
    if (inferred_title and inferred_author and HONORIFIC.match(inferred_title)
            and not HONORIFIC.match(inferred_author)):
        inferred_title, inferred_author = inferred_author, inferred_title
    if not inferred_title or not inferred_author:
        head_title, head_author = _title_from_running_head(page_blocks)
        if not inferred_title and head_title:
            inferred_title, inferred_author = head_title, inferred_author or head_author
    detected_title, detected_author = _choose_title_author(
        (metadata.get("title") or ""), (metadata.get("author") or ""), inferred_title, inferred_author)
    detected_title = _respell_from_book(detected_title, word_counts)
    detected_author = _tidy_author(detected_author, word_counts, front_texts)

    return ConversionResult(
        chapters=chapters,
        warnings=warnings,
        detected_title=detected_title,
        detected_author=detected_author,
        cover_image_base64=cover_image_base64,
        chapter_warnings=chapter_warnings,
        detected_language=guess.code,
        paragraph_style="spaced" if style["spaced"] else "indented",
        decisions={
            "structure": toc_plan.source if toc_plan.active else "heuristic",
            "toc_sequential": bool(toc_plan.active and toc_plan.sequential),
            "toc_entries": len(toc_plan.entries) if toc_plan.active else 0,
            "toc_unmatched": len(toc_plan.unmatched) if toc_plan.active else 0,
            "running_removed": dropped_furniture,
            "rescaled_pages": rescaled_pages,
            "words_repaired": words_repaired,
            "printed_pages": len(pages_marked),
        },
    )
