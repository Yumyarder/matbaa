from __future__ import annotations

import base64
import datetime
import io
import html
import re
import uuid
from typing import List, Optional

from ebooklib import epub
from lxml import etree

from app.eink import prepare as eink_prepare
from app.fonts import FAMILIES as FONT_FAMILIES, faces as font_faces, font_css, with_family
from app.hyphenate import hyphenate_html
from app.models import ChapterOut
from app.typography import set_html, set_text


EMPTY_PAGE_SHIELD = "<p>&#160;</p>"
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
# A printed page's start, as the parser marks it (pdf_parser._pagebreak_html).
_PAGEBREAK_RE = re.compile(r'<span epub:type="pagebreak"[^>]*\bid="page-([^"]+)"[^>]*></span>')
# A link to a printed page, as an index entry carries it (pdf_parser._index_entry_html).
_PAGE_LINK_RE = re.compile(r'<a href="#page-([^"]+)">(.*?)</a>', re.S)


def _safe_plain_text(text: str | None) -> str:
    """Strip control characters only, no HTML-escaping. Use this for values
    passed to ebooklib's own API (set_title, add_author, EpubHtml(title=)) —
    those get escaped automatically by lxml when the OPF/nav XML is
    serialized, so escaping them here too would double-escape."""
    if not text:
        return ""
    return _CONTROL_CHARS_RE.sub(" ", text).strip()


def _safe_xml_text(text: str | None) -> str:
    """Strip control characters (invalid in XML) and HTML-escape. Used for
    anything embedded raw into an XML tag body/title — titles and eyebrows
    aren't pre-escaped upstream the way paragraph bodies are, so a stray
    control character or an unescaped '&'/'<' here would crash lxml on
    write_epub() exactly like an empty document does."""
    if not text:
        return ""
    return html.escape(_CONTROL_CHARS_RE.sub(" ", text)).strip()


# An image is named and declared by what its bytes are, not by what the
# code that made it once produced: page images became JPEGs while the
# EPUB still called them PNGs, and Amazon's Send to Kindle turns such a
# book away without saying why.
_IMAGE_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "png", "image/png"),
    (b"\xff\xd8\xff", "jpg", "image/jpeg"),
    (b"GIF87a", "gif", "image/gif"),
    (b"GIF89a", "gif", "image/gif"),
)


def image_kind(data: bytes) -> tuple[str, str]:
    """(file extension, media type) of an image from its first bytes."""
    for magic, ext, media_type in _IMAGE_SIGNATURES:
        if data.startswith(magic):
            return ext, media_type
    return "png", "image/png"


_UNSAFE_ID_RE = re.compile(r"[^A-Za-z0-9_.-]")


def _safe_id(raw: str) -> str:
    """Make a footnote id usable as an XML id attribute.

    Ids are built from the note's printed marker, and a marker is not always
    a number — '*', '†' and '5.' all occur. Digit markers, which are the
    only ones _link_footnote_markers builds hrefs for, pass through
    unchanged, so sanitising here cannot break an existing link.
    """
    cleaned = _UNSAFE_ID_RE.sub("_", raw or "")
    return cleaned if cleaned[:1].isalpha() or cleaned[:1] == "_" else f"fn_{cleaned}"


# Kindle's cover guidance: 1600x2560 (1:1.6), RGB JPEG, under 5 MB.
KINDLE_COVER_HEIGHT = 2560
KINDLE_COVER_MAX_BYTES = 5_000_000


def kindle_cover_jpeg(image_bytes: bytes) -> bytes:
    """The cover as Kindle asks for it: a real JPEG (it was a PNG saved
    under a .jpg name), RGB, no taller than 2560px, under 5 MB."""
    from PIL import Image

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    if img.height > KINDLE_COVER_HEIGHT:
        img = img.resize((round(img.width * KINDLE_COVER_HEIGHT / img.height), KINDLE_COVER_HEIGHT),
                         Image.LANCZOS)
    for quality in (90, 82, 72, 60):
        out = io.BytesIO()
        img.save(out, "JPEG", quality=quality, optimize=True)
        if out.tell() <= KINDLE_COVER_MAX_BYTES:
            break
    return out.getvalue()


def _footnote_section_html(chapter: ChapterOut) -> str:
    if not chapter.footnotes:
        return ""
    items = []
    for fn in chapter.footnotes:
        # fn.text is plain text straight off the page, never markup. A note
        # citing "Routledge & Kegan Paul" or "<The Intertwining>" writes a
        # bare '&' or '<' into the XHTML, and write_epub() then fails to
        # parse its own output — an entire book lost to one ampersand in a
        # bibliography. Same for fn.marker.
        fid = _safe_id(fn.id)
        # A note nothing in the text refers to has nowhere to go back to;
        # a back-link to a missing anchor is an EPUBCheck error, and on a
        # Kindle a tap that does nothing.
        back = (f' <a class="footnote-back" href="#fnref_{fid}">↩</a>'
                if f'id="fnref_{fid}"' in (chapter.html or "") else "")
        items.append(
            f'<aside epub:type="footnote" id="{fid}"><p>'
            f'<span class="footnote-marker">{_safe_xml_text(fn.marker)}</span> '
            f'{_safe_xml_text(fn.text)}{back}</p></aside>'
        )
    return (
        '<div class="footnote-section">'
        '<p class="footnote-title">Notlar</p>' + "".join(items) + "</div>"
    )


def _same_name(a: str, b: str) -> bool:
    fold = lambda t: re.sub(r"\W+", "", (t or "").casefold())
    return bool(fold(a)) and fold(a) == fold(b)


def _nested_toc(chapters: List[ChapterOut], epub_chapters: list) -> tuple:
    """The reader's chapter menu, nested the way the book's contents page
    nests it: "1. BÖLÜM" › "Görme ve Bilgi", …

    Each chapter carries the labels above it (`toc_path`); consecutive
    chapters under the same label share one section, and a section links to
    its first chapter so tapping it goes somewhere. A book without a readable
    contents page has empty paths and gets the flat list it always had.
    Full-page plates and split continuations stay out of the menu.
    """
    root: list = []
    stack: list = []  # [(name, children)]
    for ch, item in zip(chapters, epub_chapters):
        if ch.is_split_continuation or ch.kind == "image":
            continue
        path = list(getattr(ch, "toc_path", None) or [])
        depth = 0
        while depth < len(stack) and depth < len(path) and stack[depth][0] == path[depth]:
            depth += 1
        del stack[depth:]
        opened = False
        for name in path[depth:]:
            children: list = []
            parent = stack[-1][1] if stack else root
            parent.append((epub.Section(_safe_plain_text(name) or name, item.file_name), children))
            stack.append((name, children))
            opened = True
        # A part's own opening pages, titled with the part's name, are what
        # the part's entry already links to; listing them again under it
        # read "Part I › Part I".
        if opened and path and _same_name(ch.title, path[-1]):
            continue
        (stack[-1][1] if stack else root).append(item)

    def freeze(nodes: list) -> list:
        return [
            (node[0], tuple(freeze(node[1]))) if isinstance(node, tuple) else node
            for node in nodes
        ]

    return tuple(freeze(root))


class _PageListWriter(epub.EpubWriter):
    """ebooklib's writer, with the nav's page-list made from the book's own
    page marks. ebooklib's epub3_pages option lists every element that
    carries an epub:type and an id as a page — the footnote <aside>s too —
    so it stays off and the list is written here."""

    def __init__(self, name, book, options, pages):
        super().__init__(name, book, options)
        self._pages = pages          # [(chapter file, printed page)] in reading order

    def _get_nav(self, item):
        nav = super()._get_nav(item)
        if not self._pages:
            return nav
        root = etree.fromstring(nav)
        body = next(el for el in root.iter() if isinstance(el.tag, str) and etree.QName(el).localname == "body")
        xhtml = etree.QName(body).namespace
        tag = (lambda name: f"{{{xhtml}}}{name}") if xhtml else (lambda name: name)
        page_list = etree.SubElement(body, tag("nav"), {
            "{%s}type" % epub.NAMESPACES["EPUB"]: "page-list", "id": "pages", "hidden": "hidden"})
        etree.SubElement(page_list, tag("h2")).text = "Sayfalar"
        ol = etree.SubElement(page_list, tag("ol"))
        for file_name, label in self._pages:
            link = etree.SubElement(etree.SubElement(ol, tag("li")), tag("a"), {"href": f"{file_name}#page-{label}"})
            link.text = label
        return etree.tostring(root, pretty_print=True, encoding="utf-8", xml_declaration=True)


IMPRINT_LABELS = (("original_title", "Özgün adı"), ("translator", "Çeviren"), ("editor", "Editör"),
                  ("publisher", "Yayınevi"), ("isbn", "ISBN"))


def _imprint_page(book_title: str, author: str, imp: dict, language: str):
    """"Bu baskı hakkında": which printed edition the book was made from,
    and that it was made from it; None when the imprint says nothing."""
    rows = [(label, imp.get(key)) for key, label in IMPRINT_LABELS if imp.get(key)]
    printing = ", ".join(x for x in (f"{imp['edition']}. baskı" if imp.get("edition") else "",
                                     str(imp.get("year") or "")) if x)
    if printing:
        rows.append(("Baskı", printing))
    if not rows:
        return None
    lines = "".join(f"<p><b>{html.escape(label)}:</b> {_safe_xml_text(str(value))}</p>" for label, value in rows)
    made = datetime.date.today().strftime("%d.%m.%Y")
    content = (
        "<?xml version='1.0' encoding='utf-8'?>\n"
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">\n'
        "<head><title>Bu baskı hakkında</title>"
        '<link rel="stylesheet" type="text/css" href="style/matbaa.css"/></head>\n'
        '<body class="frontmatter-page"><section epub:type="colophon">'
        "<h1>Bu baskı hakkında</h1>"
        f"<p><i>{_safe_xml_text(book_title or '')}</i>{(', ' + _safe_xml_text(author)) if author else ''}</p>"
        f"{lines}"
        f"<p>Bu e-kitap, yukarıdaki basılı baskının PDF'inden kişisel okuma için Matbaa ile hazırlandı ({made}).</p>"
        "</section></body>\n</html>"
    )
    page = epub.EpubHtml(title="Bu baskı hakkında", file_name="bu_baski_hakkinda.xhtml", lang=language)
    page.set_content(content.encode("utf-8"))
    return page


def build_epub(
    book_title: str,
    author: str,
    chapters: List[ChapterOut],
    css: str,
    output_path: str,
    cover_image_base64: str | None = None,
    language: str = "en",
    hyphenate: bool = False,
    font: Optional[str] = None,
    eink_images: bool = True,
    imprint: Optional[dict] = None,
    imprint_page: bool = False,
    subject: Optional[str] = None,
) -> str:
    book = epub.EpubBook()
    book.set_identifier(str(uuid.uuid4()))
    book.set_title(_safe_plain_text(book_title) or "Untitled Book")
    # dc:language drives hyphenation, the text-to-speech voice and line
    # breaking in the reader. Hard-coding "en" onto a Turkish book is not a
    # metadata detail -- it hyphenates the text by the wrong rules and has it
    # read aloud in the wrong voice.
    language = (language or "").strip() or "en"
    book.set_language(language)
    # Matbaa's syllable rules are Turkish ones; a Kindle hyphenates other
    # languages from its own dictionaries.
    soft_hyphens = hyphenate and language.lower().startswith("tr")
    book.add_author(_safe_plain_text(author) or "Unknown")
    # The edition the book was made from, as its imprint gives it
    # (app/imprint.py): a reader's library shows the publisher and year,
    # and the ISBN names the printed edition.
    imp = imprint or {}
    if imp.get("publisher"):
        book.add_metadata("DC", "publisher", _safe_plain_text(imp["publisher"]))
    if re.fullmatch(r"\d{4}", str(imp.get("year") or "")):
        book.add_metadata("DC", "date", str(imp["year"]))
    if re.fullmatch(r"97[89]\d{10}", str(imp.get("isbn") or "")):
        book.add_metadata("DC", "identifier", f"urn:isbn:{imp['isbn']}", {"id": "isbn"})
    for key, role in (("translator", "trl"), ("editor", "edt")):
        if imp.get(key):
            book.add_metadata("DC", "contributor", _safe_plain_text(imp[key]), {"id": role})
            book.add_metadata(None, "meta", role, {"refines": f"#{role}", "property": "role", "scheme": "marc:relators"})
    # the book's genre (app/genre.py), which a reader's library can sort by
    if subject:
        book.add_metadata("DC", "subject", _safe_plain_text(subject))
    # EPUB Accessibility 1.1 discovery metadata: what a reader needs to know
    # before opening the book — it is text, read in order, with a navigable
    # table of contents and headings, and nothing in it flashes or moves.
    has_images = any(ch.image_base64 or ch.images for ch in chapters)
    for prop, value in (
        [("schema:accessMode", "textual")]
        + ([("schema:accessMode", "visual")] if has_images else [])
        + [("schema:accessModeSufficient", "textual"),
           ("schema:accessibilityFeature", "structuralNavigation"),
           ("schema:accessibilityFeature", "tableOfContents"),
           ("schema:accessibilityFeature", "readingOrder"),
           ("schema:accessibilityHazard", "none"),
           ("schema:accessibilitySummary",
            "Metin olarak okunur; bölümler ve başlıklar gezinilebilir, içindekiler bağlantılıdır."
            + (" Bazı sayfalar resim olarak verilmiştir." if has_images else ""))]
    ):
        book.add_metadata(None, "meta", value, {"property": prop})

    if cover_image_base64:
        try:
            book.set_cover("images/cover.jpg", kindle_cover_jpeg(base64.b64decode(cover_image_base64)))
        except Exception:  # noqa: BLE001
            pass  # a missing/broken cover should never fail the whole export

    # The book's own typeface (app/fonts.py), the letters it uses only: a
    # Kindle sets it when the reader picks "Yayıncı yazı tipi".
    if font in FONT_FAMILIES:
        used = [book_title or "", author or ""]
        for ch in chapters:
            used += [ch.title or "", ch.eyebrow or "", getattr(ch, "byline", None) or "",
                     html.unescape(re.sub(r"<[^>]+>", " ", ch.html or ""))]
            used += [fn.text or "" for fn in ch.footnotes] + [fn.marker or "" for fn in ch.footnotes]
        text = set_text(" ".join(used))
        for k, (name, data) in enumerate(font_faces(font, text)):
            book.add_item(epub.EpubItem(uid=f"font_{k}", file_name=f"fonts/{name}",
                                        media_type="font/ttf", content=data))
        css = font_css(font) + with_family(css or "", font)

    style = epub.EpubItem(
        uid="matbaa_style",
        file_name="style/matbaa.css",
        media_type="text/css",
        content=css,
    )
    book.add_item(style)

    pages: list = []                 # (chapter file, printed page) in reading order
    seen_pages: set = set()
    # Which chapter holds each printed page, for the index's links: the
    # first mark of a page is the one kept (_page_once).
    page_files: dict = {}
    for ch in chapters:
        for m in _PAGEBREAK_RE.finditer(ch.html or ""):
            page_files.setdefault(m.group(1), f"{ch.id}.xhtml")

    def _page_link(match: "re.Match", file_name: str) -> str:
        target = page_files.get(match.group(1))
        if target is None:
            return match.group(2)    # a page the book does not mark: the number stays, unlinked
        href = f"#page-{match.group(1)}" if target == file_name else f"{target}#page-{match.group(1)}"
        return f'<a class="page-link" href="{href}">{match.group(2)}</a>'

    def _page_once(match: "re.Match", file_name: str) -> str:
        if match.group(1) in seen_pages:
            return ""
        seen_pages.add(match.group(1))
        pages.append((file_name, match.group(1)))
        return match.group(0)

    epub_chapters = []
    for ch in chapters:
        file_name = f"{ch.id}.xhtml"

        chapter_title_raw = _CONTROL_CHARS_RE.sub(" ", ch.title or "Untitled").strip()
        chapter_title = html.escape(chapter_title_raw)

        if ch.kind == "image" and ch.image_base64:
            try:
                img_bytes = base64.b64decode(ch.image_base64)
            except Exception:  # noqa: BLE001
                img_bytes = None
            if img_bytes:
                # a grey scan on yellowed paper: grey-scale, white paper (app/eink.py);
                # a picture in colour is left as it is
                if eink_images:
                    img_bytes = eink_prepare(img_bytes) or img_bytes
                ext, media_type = image_kind(img_bytes)
                img_file_name = f"images/{ch.id}.{ext}"
                image_item = epub.EpubImage(
                    uid=f"img_{ch.id}",
                    file_name=img_file_name,
                    media_type=media_type,
                    content=img_bytes,
                )
                book.add_item(image_item)
                content = (
                    "<?xml version='1.0' encoding='utf-8'?>\n"
                    '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">\n'
                    f"<head><title>{chapter_title}</title>"
                    '<link rel="stylesheet" type="text/css" href="style/matbaa.css"/></head>\n'
                    f'<body class="image-page"><div class="image-page-wrapper">'
                    f'<img src="{img_file_name}" alt="{chapter_title}"/></div></body>\n'
                    "</html>"
                )
                epub_chapter = epub.EpubHtml(title=chapter_title_raw, file_name=file_name, lang=language)
                epub_chapter.set_content(content.encode("utf-8"))
                epub_chapter.add_item(style)
                book.add_item(epub_chapter)
                epub_chapters.append(epub_chapter)
                continue
            # fall through to the normal text path if decoding failed —
            # better to show a placeholder than to silently drop the page

        # In-chapter figures from the PDF Editor's "Görsel" region marker —
        # distinct from the whole-page ch.image_base64 case above, a
        # chapter can carry any number of these alongside its ordinary
        # text, each already referenced from ch.html by
        # <img src="images/{id}.png">.
        renamed_images = {}
        for img in ch.images:
            try:
                img_bytes = base64.b64decode(img.base64)
            except Exception:  # noqa: BLE001
                continue  # the <img> tag stays in the html; a broken image icon beats losing the page
            if eink_images:
                img_bytes = eink_prepare(img_bytes) or img_bytes
            ext, media_type = image_kind(img_bytes)
            if ext != "png":
                renamed_images[f"images/{img.id}.png"] = f"images/{img.id}.{ext}"
            book.add_item(epub.EpubImage(
                uid=f"img_{img.id}",
                file_name=f"images/{img.id}.{ext}",
                media_type=media_type,
                content=img_bytes,
            ))

        # Empty-page shield: a chapter with no body content (e.g. right
        # after a manual split, or if someone deletes everything in the
        # editor) produces a <body> with nothing in it, which some
        # ebooklib/lxml versions choke on with "Document is empty". A
        # non-breaking-space paragraph keeps the XHTML non-degenerate.
        body_html = ch.html if ch.html and ch.html.strip() else EMPTY_PAGE_SHIELD
        body_html = _CONTROL_CHARS_RE.sub(" ", body_html)
        for old_src, new_src in renamed_images.items():
            body_html = body_html.replace(f'"{old_src}"', f'"{new_src}"')
        footnotes_html = _footnote_section_html(ch)

        heading_tag = "h1" if not ch.is_split_continuation else "h2"
        opener = getattr(ch, "opener", None) or {}
        label_cls = ""
        if opener.get("label_align"):
            label_cls = f' align-{opener["label_align"]} scale-{opener.get("label_scale") or "small"}'
            if opener.get("label_gap"):
                label_cls += f' gap-{opener["label_gap"]}'
        eyebrow_html = (
            f'<p class="chapter-eyebrow{label_cls}">{_safe_xml_text(ch.eyebrow)}</p>'
            if (ch.eyebrow and not ch.is_split_continuation)
            else ""
        )
        title_cls = ""
        if opener:
            title_cls = f' class="align-{opener.get("title_align", "center")} scale-{opener.get("title_scale", "medium")}"'
        title_html = "" if ch.is_split_continuation else f"<{heading_tag}{title_cls}>{chapter_title}</{heading_tag}>"
        byline = getattr(ch, "byline", None)
        byline_html = (
            f'<p class="chapter-byline opener-byline">{_safe_xml_text(byline)}</p>'
            if (byline and not ch.is_split_continuation)
            else ""
        )
        opener_html = eyebrow_html + title_html + byline_html
        if opener_html and ch.kind == "chapter":
            opener_cls = "opener"
            if opener:
                opener_cls += " measured" + (" inline" if opener.get("inline") else "")
                opener_cls += f' drop-{opener.get("drop", 1)}'
                opener_cls += f' align-{opener.get("title_align", "center")}'
            opener_html = f'<div class="{opener_cls}">{opener_html}</div>'

        body_class = {
            "frontmatter": "frontmatter-page",
            "toc": "toc-page",
        }.get(ch.kind, "")
        body_attr = f' class="{body_class}"' if body_class else ""

        # Set as a printer sets it (app/typography.py) and, where asked, with
        # soft hyphens at the syllable breaks (app/hyphenate.py): text nodes
        # only, in the book as shipped. The session keeps the text as read,
        # so the editor and the Okuma Defteri see the same words as before.
        opener_html = set_html(opener_html)
        text_html = set_html(body_html + footnotes_html)
        if soft_hyphens:
            text_html = hyphenate_html(text_html)
        # The printed pages this chapter begins, for the page-list. A page
        # marked twice — text copied in the editor — keeps its first mark:
        # an id used twice is an EPUBCheck error, and Send to Kindle drops
        # a book that has one.
        text_html = _PAGEBREAK_RE.sub(lambda m: _page_once(m, file_name), text_html)
        text_html = _PAGE_LINK_RE.sub(lambda m: _page_link(m, file_name), text_html)

        content = (
            "<?xml version='1.0' encoding='utf-8'?>\n"
            '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">\n'
            f"<head><title>{chapter_title}</title>"
            '<link rel="stylesheet" type="text/css" href="style/matbaa.css"/></head>\n'
            f"<body{body_attr}>{opener_html}{text_html}</body>\n"
            "</html>"
        )

        # The menu shows what the printed contents page shows: "İnce Buz,
        # Steven Holl", not the title alone.
        menu_title = set_text(f"{chapter_title_raw}, {byline}" if byline else chapter_title_raw)
        epub_chapter = epub.EpubHtml(
            title=menu_title,
            file_name=file_name,
            lang=language,
        )
        # set_content() (rather than assigning .content directly) makes sure
        # ebooklib stores well-formed encoded bytes; passing a plain str
        # through the raw .content setter is what let a degenerate/empty
        # value slip through to lxml's parser on write_epub().
        epub_chapter.set_content(content.encode("utf-8"))
        epub_chapter.add_item(style)
        book.add_item(epub_chapter)
        epub_chapters.append(epub_chapter)

    # A full-page plate stays in the reading flow but is not a section of
    # the book: listing it put entries like "Görsel Sayfa 2" between the
    # front matter and the contents page in the reader's chapter menu.
    book.toc = _nested_toc(chapters, epub_chapters)
    about = _imprint_page(book_title, author, imp, language) if imprint_page else None
    if about is not None:
        about.add_item(style)
        book.add_item(about)
        epub_chapters.append(about)
        book.toc = list(book.toc) + [epub.Link(about.file_name, about.title, "about")]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    # The reading flow has to open on the cover. ebooklib marks cover.xhtml
    # linear="no", and the generated contents page was the first linear
    # document, so a Kindle opened the book on a bare list of links and the
    # cover was not part of the page-turn sequence at all — "things come
    # before the cover". The cover is now the first linear page, and the
    # generated nav page is kept out of the flow: the reader's own contents
    # menu is built from it regardless, and the book already carries its
    # own printed İçindekiler where the book prints it. It is not in the
    # spine at all: a non-linear spine item nothing links to is an
    # EPUBCheck error (OPF-096), and EPUB 3 does not ask for the nav there.
    cover_item = book.get_item_with_id("cover") if cover_image_base64 else None
    spine = list(epub_chapters)
    if cover_item is not None:
        cover_item.is_linear = True
        spine.insert(0, "cover")
    book.spine = spine

    # Kindle's conversion pipeline still reads the EPUB 2 <guide> to find
    # the cover page and where the text starts; without it, which page
    # opens first is left to guesswork.
    first_text = next(
        (epub_chapters[i] for i, ch in enumerate(chapters)
         if ch.kind == "chapter" and not ch.is_split_continuation),
        epub_chapters[0] if epub_chapters else None,
    )
    if cover_item is not None:
        book.guide.append({"type": "cover", "href": cover_item.file_name, "title": "Kapak"})
    if first_text is not None:
        book.guide.append({"type": "text", "href": first_text.file_name, "title": "Başlangıç"})

    # The page-list is the book's own printed pages (_PageListWriter);
    # ebooklib's epub3_pages would list the footnotes as pages. Unlike
    # epub.write_epub(), a failed write is not swallowed.
    writer = _PageListWriter(output_path, book, {"epub3_pages": False}, pages)
    writer.process()
    writer.write()
    return output_path
