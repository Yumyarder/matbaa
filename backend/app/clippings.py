"""What a reader marked on the Kindle, read back.

A Kindle keeps every highlight, note and bookmark in `documents/My
Clippings.txt` — books sent with Send to Kindle included — and Amazon's
"Export notes" gives the same as an HTML notebook. Both are read here into
one shape: per book, its highlights in reading order, each with the note
the reader typed on it.

The Kindle writes a new entry every time a highlight is extended or
re-marked, so the raw file repeats itself; the longest of overlapping
highlights is the one the reader meant. A note is written at the
location where its highlight ends, which is how it is paired back.
"""
from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

SEPARATOR = "=========="
# what the Kindle writes in place of a highlight past the book's clipping limit
CLIPPING_LIMIT = re.compile(r"^\s*<[^>]*(clipping limit|kırpma sınır|alıntı sınır|limite)[^>]*>\s*$", re.I)

# words the Kindle uses, in the interface languages a Turkish reader meets
_KIND_WORDS = {
    "bookmark": re.compile(r"bookmark|yer\s*imi|lesezeichen|signet|marcador|segnalibro", re.I),
    "note": re.compile(r"\bnote\b|\bnot(?:unuz|u)?\b|notiz|\bnota\b", re.I),
    "highlight": re.compile(r"highlight|vurgula|markierung|surlignement|subrayado|evidenziazione|clip", re.I),
}
_LOCATION = re.compile(r"(?:location|loc\.|konum|position|posici[oó]n|posizione|emplacement)\s*(\d+)(?:\s*-\s*(\d+))?", re.I)
_PAGE = re.compile(r"(?:page|sayfa|seite|p[aá]gina)\s*([0-9ivxlcdm]+)(?:\s*-\s*([0-9ivxlcdm]+))?", re.I)


def fold(text: str) -> str:
    """Text reduced to what survives a scan or a re-typing: Turkish-aware
    lower case, words re-joined across a line-end hyphen ("bil- ginin"),
    letters and digits only."""
    # dotted and dotless i are folded together: they are what a scanner
    # confuses most often in Turkish; everything not a letter or digit goes,
    # which also re-joins a word broken at a line end
    text = text.replace("I", "ı").replace("İ", "i").lower().replace("ı", "i")
    return _NOT_ALNUM.sub("", text)


_NOT_ALNUM = re.compile(r"[\W_]+")


def block_id(text: str) -> str:
    """A stable Obsidian block id for a passage: the same highlight gets the
    same id on every sync, so it is recognised and never written twice."""
    return "h-" + hashlib.sha1(fold(text).encode("utf-8")).hexdigest()[:6]


@dataclass
class Clip:
    book: str
    author: str
    kind: str                      # "highlight" | "note" | "bookmark"
    text: str
    loc_start: Optional[int] = None
    loc_end: Optional[int] = None
    page: Optional[str] = None
    added: str = ""
    color: Optional[str] = None
    section: Optional[str] = None  # the chapter heading, when the source names it


@dataclass
class Highlight:
    id: str
    text: str
    note: Optional[str] = None
    loc_start: Optional[int] = None
    loc_end: Optional[int] = None
    page: Optional[str] = None
    added: str = ""
    color: Optional[str] = None
    section: Optional[str] = None
    note_original: Optional[str] = None   # the note as the Kindle wrote it, when the reader corrected it

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class BookClips:
    title: str
    author: str
    highlights: List[Highlight] = field(default_factory=list)
    # highlights the Kindle did not write out: past a book's "clipping
    # limit" My Clippings gets a placeholder line instead of the text
    limited: int = 0

    @property
    def key(self) -> str:
        return fold(self.title)[:60] or "kitap"

    def to_dict(self) -> Dict:
        return {"key": self.key, "title": self.title, "author": self.author, "limited": self.limited,
                "highlights": [h.to_dict() for h in self.highlights]}


# --- book titles as the Kindle has them ------------------------------------------------------

_UNKNOWN_AUTHOR = {"bilinmiyor", "bilinmeyen yazar", "unknown", "anonim", "anonymous"}
_NAME_PARTICLES = {"de", "da", "van", "von", "der", "bin", "ibn", "el", "al", "la", "le", "di"}


def _looks_like_name(text: str) -> bool:
    words = text.split()
    if not 2 <= len(words) <= 4 or any(c.isdigit() for c in text):
        return False
    return all(w[:1].isupper() or w.lower() in _NAME_PARTICLES for w in words) and \
        all(len(w) <= 15 for w in words) and not text.isupper()


def clean_title(title: str, author: str = "") -> "tuple[str, str]":
    """A Kindle title as a book's name, and the author it carries:
    "[İthaki Yayınları 14. Tarih-Toplum-Kuram. 180] Louis Althusser - İdeoloji
    ve…" -> "İdeoloji ve…"; "Tarih, Türkiye, Sosyalizm - Metin Çulhaoğlu" ->
    the title and its author; "Cinsiyet Belası _ Feminizm…" -> "Cinsiyet
    Belası: Feminizm…" (the Kindle writes a colon as an underscore)."""
    known = author if author and author.lower() not in _UNKNOWN_AUTHOR else ""
    t = re.sub(r"^\s*\[[^\]]*\]\s*", "", title).replace(" _ ", ": ").replace("_", " ")
    parts = [p.strip() for p in re.split(r"\s+[-–—]\s+", t) if p.strip()]
    while len(parts) > 1:
        last = parts[-1]
        if last.lower() in _UNKNOWN_AUTHOR or (known and fold(last) == fold(known)):
            parts.pop()
        elif not known and _looks_like_name(last):
            known = last
            parts.pop()
        else:
            break
    if len(parts) > 1 and (fold(parts[0]) == fold(known) or (not known and _looks_like_name(parts[0]))):
        known = known or parts[0]
        parts.pop(0)
    name = " - ".join(parts) or title
    if name.isupper():
        from app.parsers.pdf_parser import turkish_title_case
        name = turkish_title_case(name)
    return " ".join(name.split()), known


_MONTHS = {m: i + 1 for i, names in enumerate([
    ("january", "ocak"), ("february", "şubat", "subat"), ("march", "mart"), ("april", "nisan"),
    ("may", "mayıs", "mayis"), ("june", "haziran"), ("july", "temmuz"), ("august", "ağustos", "agustos"),
    ("september", "eylül", "eylul"), ("october", "ekim"), ("november", "kasım", "kasim"),
    ("december", "aralık", "aralik")]) for m in names}


def parse_added(text: str):
    """The date in a clipping's "Added on …" part, in English or Turkish."""
    import datetime as _dt
    low = text.lower()
    year = re.search(r"\b(20\d\d|19\d\d)\b", low)
    month = next((n for name, n in _MONTHS.items() if re.search(r"\b" + name + r"\b", low)), None)
    if not year or not month:
        return None
    day = None
    for m in re.finditer(r"\b(\d{1,2})\b", low[:year.start()] + " " + low[year.end():year.end() + 1]):
        if 1 <= int(m.group(1)) <= 31:
            day = int(m.group(1))
            break
    try:
        return _dt.date(int(year.group(1)), month, day or 1)
    except ValueError:
        return None


# --- My Clippings.txt -----------------------------------------------------------------

def _title_author(line: str) -> "tuple[str, str]":
    """ "Müşterek Mekan (Stavros Stavrides)" -> title, author: the author is
    the last parenthesis, a title may hold parentheses of its own."""
    line = line.strip().lstrip("﻿").strip()
    m = re.match(r"^(.*)\(([^()]*)\)\s*$", line)
    if m and m.group(1).strip():
        return m.group(1).strip(), m.group(2).strip()
    return line, ""


def _range(start: str, end: Optional[str]) -> "tuple[int, int]":
    a = int(start)
    if not end:
        return a, a
    # an abbreviated end ("180-82") keeps the start's leading digits
    if len(end) < len(start):
        end = start[: len(start) - len(end)] + end
    return a, max(a, int(end))


def _parse_meta(line: str) -> Dict:
    parts = [p.strip() for p in line.lstrip("- ").split("|")]
    head = parts[0] if parts else ""
    kind = next((k for k, rx in _KIND_WORDS.items() if rx.search(head)), "highlight")
    meta: Dict = {"kind": kind, "added": parts[-1] if len(parts) > 1 else ""}
    loc = _LOCATION.search(line)
    if loc:
        meta["loc_start"], meta["loc_end"] = _range(loc.group(1), loc.group(2))
    page = _PAGE.search(head) or _PAGE.search(line)
    if page:
        meta["page"] = page.group(1)
    return meta


def parse_my_clippings(text: str) -> List[Clip]:
    clips: List[Clip] = []
    for entry in text.replace("\r\n", "\n").split(SEPARATOR):
        lines = [l for l in entry.strip("\n").split("\n")]
        while lines and not lines[0].strip():
            lines.pop(0)
        if len(lines) < 2:
            continue
        book, author = _title_author(lines[0])
        meta = _parse_meta(lines[1])
        body = "\n".join(lines[2:]).strip()
        if CLIPPING_LIMIT.match(body):
            meta["kind"], body = "limit", ""
        elif meta["kind"] != "bookmark" and not body:
            continue
        clips.append(Clip(book=book, author=author, text=body, **meta))
    return clips


# --- the HTML notebook from "Export notes" ---------------------------------------------

_DIV = re.compile(r"<(div|h[1-6])[^>]*class=['\"]?(bookTitle|authors|sectionHeading|noteHeading|noteText)['\"]?[^>]*>(.*?)</\1>",
                  re.S | re.I)


def _plain(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def parse_notebook_html(text: str) -> List[Clip]:
    clips: List[Clip] = []
    book = author = ""
    section = None
    pending: Optional[Dict] = None
    for _tag, cls, inner in _DIV.findall(text):
        cls = cls.lower()
        if cls == "booktitle":
            book = _plain(inner)
        elif cls == "authors":
            author = _plain(inner)
        elif cls == "sectionheading":
            section = _plain(inner)
        elif cls == "noteheading":
            heading = _plain(inner)
            meta = _parse_meta(heading)
            color = re.search(r"\(\s*(\w+)\s*\)", heading)
            meta["color"] = color.group(1).lower() if color and meta["kind"] == "highlight" else None
            pending = meta
        elif cls == "notetext" and pending is not None:
            clips.append(Clip(book=book, author=author, text=_plain(inner), section=section, **pending))
            pending = None
    return clips


def parse_notebook_csv(text: str) -> List[Clip]:
    """The CSV the Kindle apps export alongside the HTML notebook: a few
    header lines (title, "by author"), then rows of annotation type,
    location, starred, text."""
    import csv
    import io as _io

    rows = list(csv.reader(_io.StringIO(text)))
    book = author = ""
    start = None
    for i, row in enumerate(rows):
        cells = [c.strip() for c in row]
        if cells and cells[0].lower().startswith(("annotation type", "not türü", "açıklama türü")):
            start = i + 1
            break
        if len(cells) == 1 and cells[0]:
            if not book and not cells[0].lower().startswith(("your kindle notes", "kindle not")):
                book = cells[0]
            elif cells[0].lower().startswith(("by ", "yazar")) and not author:
                author = re.sub(r"^(by|yazar:?)\s+", "", cells[0], flags=re.I)
    clips: List[Clip] = []
    if start is None:
        return clips
    for row in rows[start:]:
        if len(row) < 4 or not row[3].strip():
            continue
        meta = _parse_meta(f"{row[0]} | {row[1]}")
        color = re.search(r"\(\s*(\w+)\s*\)", row[0])
        meta["color"] = color.group(1).lower() if color and meta["kind"] == "highlight" else None
        clips.append(Clip(book=book, author=author, text=row[3].strip(), **meta))
    return clips


def parse_any(data: bytes | str) -> List[Clip]:
    text = data.decode("utf-8-sig", errors="replace") if isinstance(data, bytes) else data
    # the Kindle writes some titles decomposed ("I" + a combining dot): one
    # form for every letter, or "İdeoloji" and "İdeoloji" are two books
    text = unicodedata.normalize("NFC", text)
    # a Matbaa book carries soft hyphens (app/hyphenate.py); a highlight that
    # kept them would put invisible characters into the vault and out of its search
    text = text.replace("\u00ad", "")
    if re.search(r"class=['\"]?noteText", text, re.I):
        return parse_notebook_html(text)
    if re.search(r'^"?Annotation Type"?\s*,', text, re.I | re.M):
        return parse_notebook_csv(text)
    return parse_my_clippings(text)


# --- one book's highlights, as the reader left them -------------------------------------------

def _overlaps(a: Clip, b: Clip) -> bool:
    if a.loc_start is None or b.loc_start is None:
        return False
    return a.loc_start <= (b.loc_end or b.loc_start) and b.loc_start <= (a.loc_end or a.loc_start)


def _shared(a: str, b: str) -> int:
    from difflib import SequenceMatcher
    return SequenceMatcher(None, a, b, autojunk=False).find_longest_match(0, len(a), 0, len(b)).size


def _merge_highlights(clips: List[Clip]) -> List[Clip]:
    """One highlight per passage. The Kindle keeps every version of a
    highlight the reader extended, shortened or moved; the file is in the
    order things were done, so of two versions of one passage the later
    is the reader's. Two highlights are versions of one passage when their
    locations overlap and they share most of their words — adjacent
    highlights share a location number, not their text."""
    kept: List[Clip] = []
    keys: List[str] = []              # folded text of each kept clip, computed once
    sizes: List[int] = []             # its word count
    for c in clips:
        fc = fold(c.text)
        if not fc:
            continue
        nc = len(c.text.split())
        replaced = False
        for i, k in enumerate(kept):
            fk, nk = keys[i], sizes[i]
            same = fc == fk
            if not same and k.loc_start is None and c.loc_start is None:
                same = fc in fk or fk in fc
            # a word or two marked inside a longer highlight is the reader
            # making a link, not a new version of that highlight
            short = min(nc, nk) <= 4 < max(nc, nk)
            if not same and not short and _overlaps(c, k):
                same = fc in fk or fk in fc or _shared(fc, fk) >= 0.5 * min(len(fc), len(fk))
            if not same and not short and min(len(fc), len(fk)) >= 30:
                same = fc in fk or fk in fc       # a sentence highlighted again, as part of a longer one
            if same:
                if c.loc_start is not None or len(fc) > len(fk):
                    kept[i], keys[i], sizes[i] = c, fc, nc
                replaced = True
                break
        if not replaced:
            kept.append(c)
            keys.append(fc)
            sizes.append(nc)
    return kept


def _latest_notes(notes: List[Clip]) -> List[Clip]:
    """One note per place: the Kindle logs a note again every time it is
    saved while being typed ("he", "her sehy", "her sey"), so of the notes
    at one location only the last written is the reader's note."""
    latest: Dict[tuple, Clip] = {}
    order: List[tuple] = []
    for n in notes:
        place = (n.loc_start, n.page) if (n.loc_start is not None or n.page) else ("seq", len(order))
        if place not in latest:
            order.append(place)
        latest[place] = n
    return [latest[p] for p in order]


def group_books(clips: List[Clip]) -> List[BookClips]:
    books: Dict[str, BookClips] = {}
    order: Dict[str, List[Clip]] = {}
    for c in clips:
        title, author = clean_title(c.book, c.author)
        key = fold(title)[:60] or "kitap"
        if key not in books:
            books[key] = BookClips(title=title, author=author)
            order[key] = []
        elif author and not books[key].author:
            books[key].author = author
        order[key].append(c)

    for key, book in books.items():
        items = order[key]
        sequential = all(c.loc_start is None for c in items)
        highlights = _merge_highlights([c for c in items if c.kind == "highlight"])
        book.limited = sum(1 for c in items if c.kind == "limit")
        notes = _latest_notes([c for c in items if c.kind == "note"])
        out = [Highlight(id=block_id(h.text), text=h.text, loc_start=h.loc_start, loc_end=h.loc_end,
                         page=h.page, added=h.added, color=h.color, section=h.section) for h in highlights]
        by_clip = {id(h): out[i] for i, h in enumerate(highlights)}

        if sequential:
            # no locations (an HTML export without them): a note belongs to
            # the highlight just before it in the source
            last = None
            by_text = {fold(h.text): by_clip[id(h)] for h in highlights}
            for c in items:
                if c.kind == "highlight":
                    last = by_text.get(fold(c.text), last)
                elif c.kind == "note":
                    if last is not None and not last.note:
                        last.note = c.text
                    else:
                        out.append(Highlight(id=block_id("not:" + c.text), text="", note=c.text,
                                             added=c.added, section=c.section))
        else:
            for n in notes:
                target = None
                for h in highlights:          # the highlight ending where the note sits
                    if h.loc_end == n.loc_start:
                        target = by_clip[id(h)]
                for h in highlights if target is None else []:
                    if h.loc_start is not None and h.loc_start <= (n.loc_start or 0) <= (h.loc_end or h.loc_start):
                        target = by_clip[id(h)]
                if target is not None and not target.note:
                    target.note = n.text
                elif target is not None:
                    target.note += "\n\n" + n.text
                else:
                    out.append(Highlight(id=block_id("not:" + n.text), text="", note=n.text,
                                         loc_start=n.loc_start, loc_end=n.loc_end, page=n.page, added=n.added))
            out.sort(key=lambda h: (h.loc_start if h.loc_start is not None else 10 ** 9))
        book.highlights = out
    return list(books.values())


def read_books(data: bytes | str) -> List[BookClips]:
    return group_books(parse_any(data))
