from __future__ import annotations
from typing import Dict, List, Optional
from pydantic import BaseModel


class Footnote(BaseModel):
    id: str
    marker: str
    text: str


class ChapterImage(BaseModel):
    """An in-chapter figure from the PDF Editor's 'Görsel' region marker —
    referenced from ChapterOut.html by `<img src="images/{id}.png">`.
    Distinct from ChapterOut.image_base64, which stands in for an entire
    chapter (a whole page marked Görsel in Page Review); these sit
    alongside ordinary text within one."""
    id: str
    base64: str


class ChapterOut(BaseModel):
    id: str                 # e.g. "ch_0003" or "ch_0003_b" for a silent split
    index: int
    title: str
    kind: str = "chapter"    # "chapter" | "frontmatter" | "toc" | "image"
    eyebrow: Optional[str] = None
    html: str                # editable XHTML body (inner content only)
    footnotes: List[Footnote] = []
    is_split_continuation: bool = False
    image_base64: Optional[str] = None  # set only when kind == "image"
    images: List[ChapterImage] = []
    # Author line under the title ("Steven Holl"), printed as its own line.
    byline: Optional[str] = None
    # Enclosing sections from the book's printed contents, outermost first;
    # the reader's chapter menu is nested along it.
    toc_path: List[str] = []
    # Measured opening layout: title/label alignment and scale, white space
    # before the text, whether the section starts mid-page.
    opener: Optional[dict] = None


# "critical" — content loss or a structural defect (a chapter missing,
#   text that never made it into the EPUB, a chapter boundary that's wrong).
# "warning"  — a real defect that isn't content loss (broken paragraph
#   flow, a footnote/navigation problem, a titling drift signal).
# "info"     — a tolerated, cosmetic-tier note (garbled title from PDF font
#   corruption, uncertain language detection) — visible, not urgent.
class Warning(BaseModel):
    message: str
    severity: str = "warning"


class ChapterWarning(BaseModel):
    chapter_id: str
    message: str
    severity: str = "warning"


class ConversionSession(BaseModel):
    session_id: str
    book_title: str
    author: str = "Unknown"
    # BCP-47 tag written to dc:language. Readers use it for hyphenation,
    # text-to-speech voice and line-breaking rules, so a wrong value is not
    # cosmetic. Detected from the book's own text; editable in the workbench.
    language: str = "en"
    # Soft hyphens at Turkish syllable breaks in the exported book
    # (app/hyphenate.py); off until the reader has seen it on their Kindle.
    hyphenate: bool = False
    # The typeface embedded in the book (app/fonts.py): "kindle", none, by
    # default — Bookerly was drawn for the Kindle's screen, and a Kindle
    # shows a book's own face only under "Yayıncı yazı tipi" — or
    # "literata", offered as the publisher's font.
    font: str = "kindle"
    chapters: List[ChapterOut]
    css: str
    warnings: List[Warning] = []
    chapter_warnings: List[ChapterWarning] = []
    cover_image_base64: Optional[str] = None
    # Which cover the book carries (app/cover.py): "pdf", the PDF's own,
    # cleaned, or "matbaa", one set in type from the title and author. The
    # PDF's is kept so the reader can go back to it.
    cover_kind: str = "pdf"
    pdf_cover_base64: Optional[str] = None
    # a cover found online by the book's ISBN ("web"), on the reader's request
    web_cover_base64: Optional[str] = None
    # The book's imprint (app/imprint.py Imprint.to_dict()): ISBN, translator,
    # editor, original title, publisher, printing, year — read from its own
    # pages, editable, completed online only on request. It goes into the
    # EPUB's metadata; imprint_page adds a page "Bu baskı hakkında".
    imprint: Optional[dict] = None
    imprint_page: bool = False
    # An index made for a book without one (app/auto_index.py): names, and
    # the concepts of the reader's vault. None: on when the book has no
    # printed index and enough is found; the terms the reader took out.
    auto_index: Optional[bool] = None
    index_removed: List[str] = []
    # app.diagnosis.BookReport.to_dict(): what kind of PDF this was, what the
    # engine did with it, and what it could not resolve.
    report: Optional[dict] = None
    # What kind of book this is (app/genre.py GENRES key: "felsefe",
    # "rus-edebiyati"…), where it came from ("wikidata", "auto": the book's
    # own reading, "reader": chosen by hand) and why, in a line.
    genre: Optional[str] = None
    genre_source: Optional[str] = None
    genre_reason: Optional[str] = None
    # Counted once on the site's counter (app/counter.py), at the book's
    # first export or Send to Kindle.
    counted: bool = False
    # A line from the book (or its author) found on Vikisöz for the start
    # screen (app/quote_lookup.py); {"none": True} once looked for in vain.
    web_quote: Optional[dict] = None


class ChapterUpdate(BaseModel):
    html: str
    footnotes: Optional[List[Footnote]] = None
    title: Optional[str] = None
    eyebrow: Optional[str] = None
    byline: Optional[str] = None


class LlmProposals(BaseModel):
    merge: List[int] = []
    replace: List[dict] = []


class CoverChoice(BaseModel):
    kind: str            # "pdf" | "matbaa" | "web" (ConversionSession.cover_kind)


class MetaUpdate(BaseModel):
    book_title: Optional[str] = None
    author: Optional[str] = None
    language: Optional[str] = None
    css: Optional[str] = None
    hyphenate: Optional[bool] = None
    # a theme from app/builders/themes.py, laid over the book's stylesheet
    theme: Optional[str] = None
    font: Optional[str] = None
    # the imprint's fields the reader corrected (a field set to "" is cleared)
    imprint: Optional[dict] = None
    imprint_page: Optional[bool] = None
    auto_index: Optional[bool] = None
    index_removed: Optional[List[str]] = None
    # the reader's own choice of genre (app/genre.py GENRES key)
    genre: Optional[str] = None


class PagePreviewOut(BaseModel):
    index: int
    text_snippet: str
    thumbnail_base64: str
    likely_junk: bool
    suggested_mode: str = "text"


class UploadPreview(BaseModel):
    upload_id: str
    page_count: int
    pages: List[PagePreviewOut]
    # Pages that carry no text of their own — a scan. They can only be read
    # by OCR, which the review screen starts before showing its suggestions.
    scanned_pages: List[int] = []
    # Why those pages need reading: "scan" (no text), "broken-text" (the text
    # layer is noise — a broken font encoding), "sparse-scan" (a scanner's
    # OCR layer read almost nothing).
    ocr_reason: Optional[str] = None
    ocr_available: bool = True
    ocr_message: Optional[str] = None


class ImageRegion(BaseModel):
    """The PDF Editor's 'Görsel' bounding-box action, as sent to
    /api/convert — see convert_pdf_to_chapters's docstring for exactly
    how each one is applied."""
    page_index: int
    bbox: List[float]


class ApprovedOcrRegion(BaseModel):
    """The PDF Editor's 'OCR' bounding-box action. Approval already
    happened in the editor (the person reviewed/edited the OCR text and
    clicked 'Onayla') before this ever reaches the backend — there is no
    unapproved-OCR path here. source_text/confidence are carried through
    for provenance only; conversion only ever uses `text`."""
    page_index: int
    bbox: List[float]
    text: str
    confidence: Optional[int] = None
    source_text: Optional[str] = None


class ConvertRequest(BaseModel):
    excluded_pages: List[int] = []
    image_pages: List[int] = []
    toc_pages: List[int] = []
    cover_page_index: Optional[int] = None
    header_margin_ratio: Optional[float] = None
    footer_margin_ratio: Optional[float] = None
    excluded_text_regions: Dict[int, List[List[float]]] = {}
    image_regions: List[ImageRegion] = []
    ocr_regions: List[ApprovedOcrRegion] = []
    auto_figures: bool = True


class ChapterSplitRequest(BaseModel):
    before_html: str
    after_html: str
    new_title: str


class ReorderRequest(BaseModel):
    chapter_ids: List[str]


class OcrRequest(BaseModel):
    upload_id: str
    page_index: int
    bbox: List[float]
    lang: str = "tur"
