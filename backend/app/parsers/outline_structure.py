"""The PDF's own bookmarks (outline), read as the book's structure.

Many PDFs carry a bookmark tree with every chapter's title, spelled right,
and its page — even when the printed pages are hard to read: on seven books
of the library survey the text layer was noise while the bookmarks were
clean Turkish. Ignoring them left those books with no chapters at all and
others with running heads and sub-sections promoted to chapters.

But a bookmark tree is not always the contents. Scanning software writes
one bookmark per page ("Untitled.FR12 - 0003_2R"), some PDFs carry a few
placeholder entries ("Boş Sayfa"), and e-book exports list the title page,
copyright and dedication beside the chapters. This module tells a usable
tree from those, and turns it into a reading order of chapters (with the
part each belongs to) and in-chapter sub-headings, deep enough for the
Kindle menu and no deeper: Kindle accepts two levels of nesting.

Works on plain `doc.get_toc()` rows so it can be tested without a PDF.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from app.parsers.toc_structure import squash

# Bookmarks scanners and converters write on their own.
GENERATED_ENTRY = re.compile(
    r"untitled|\.fr\d+|^img[_-]?\d|^(page|sayfa|p\.?)\s*\d+$|^\d+$|^boş sayfa$|^blank page$|\.(tiff?|jpe?g|png)\b",
    re.IGNORECASE,
)
# Entries for the pages around the text, not the text: they stay front matter.
FRONT_MATTER_ENTRY = re.compile(
    r"^\W*(title( page)?|half[- ]title|cover|kapak|copyright( notice| page)?|telif|dedication|ithaf|"
    r"epigraphs?|contents|table of contents|i̇?çindekiler|içindekiler|also by .*|about the (author|publisher))\W*$",
    re.IGNORECASE,
)
# How many bookmarks may be generated or repeated before the tree is noise.
NOISE_SHARE_MAX = 0.3
# One bookmark per page, give or take, is a page index, not a contents.
PAGE_INDEX_SHARE = 0.8
MIN_CHAPTERS = 2


@dataclass
class OutlineNode:
    level: int
    title: str
    page: int  # 0-based
    children: List["OutlineNode"] = field(default_factory=list)


@dataclass
class OutlineItem:
    """One stop in the reading order the bookmarks describe."""
    kind: str               # "chapter" | "subheading"
    title: str
    page: int               # 0-based
    path: List[str] = field(default_factory=list)   # the part it belongs to
    label: Optional[str] = None                      # printed above the title ("Chapter 1")
    first_in_part: bool = False


_LETTER_SPACED = re.compile(r"\b(?:[^\W\d_] ){2,}[^\W\d_]\b")


def clean_title(title: str) -> str:
    """Tabs and runs of spaces collapsed; letter-spaced words ("Ö n s ö z")
    closed up; trailing punctuation that only padded the bookmark dropped."""
    t = re.sub(r"\s+", " ", title.replace("\t", " ")).strip()
    t = _LETTER_SPACED.sub(lambda m: m.group(0).replace(" ", ""), t)
    return t.strip(" .·-–—")


def usable_entries(toc: Sequence[Sequence], page_count: int) -> Optional[List[tuple]]:
    """(level, title, page) rows of a bookmark tree that describes the
    book's contents, or None when the tree is noise."""
    rows = []
    for row in toc:
        level, title, page = int(row[0]), clean_title(str(row[1])), int(row[2])
        if page >= 1 and title:
            rows.append((level, title, page - 1))
    if len(rows) < 3:
        return None
    generated = sum(1 for _, t, _ in rows if GENERATED_ENTRY.search(t))
    counts = Counter(squash(t) for _, t, _ in rows)
    repeated = sum(n for n in counts.values() if n > 1)
    if (generated + repeated) / len(rows) > NOISE_SHARE_MAX:
        return None
    if page_count and len(rows) >= PAGE_INDEX_SHARE * page_count and len(rows) > 30:
        return None
    return rows


def _tree(rows: Sequence[tuple]) -> List[OutlineNode]:
    roots: List[OutlineNode] = []
    stack: List[OutlineNode] = []
    for level, title, page in rows:
        node = OutlineNode(level, title, page)
        while stack and stack[-1].level >= level:
            stack.pop()
        (stack[-1].children if stack else roots).append(node)
        stack.append(node)
    return roots


def _drop_front_matter(nodes: List[OutlineNode], book_title: Optional[str]) -> List[OutlineNode]:
    """Front-matter bookmarks leave; anything nested under one (a whole book
    filed under "İÇİNDEKİLER") takes its place."""
    out: List[OutlineNode] = []
    title_sq = squash(book_title or "")
    for i, node in enumerate(nodes):
        # The first bookmark names the book when the contents or other front
        # matter follows it; on its own it may just be a first chapter on
        # the first page.
        followed_by_front_matter = (
            i + 1 < len(nodes) and bool(FRONT_MATTER_ENTRY.match(nodes[i + 1].title))
        )
        is_book_title = (
            node.page == 0 and i == 0 and not node.children and followed_by_front_matter
            or (title_sq and squash(node.title) == title_sq)
        )
        if FRONT_MATTER_ENTRY.match(node.title) or is_book_title:
            out.extend(_drop_front_matter(node.children, book_title))
            continue
        node.children = _drop_front_matter(node.children, book_title)
        out.append(node)
    return out


def _subheadings(node: OutlineNode, out: List[OutlineItem], path: List[str]) -> None:
    for child in node.children:
        out.append(OutlineItem("subheading", child.title, child.page, list(path)))
        _subheadings(child, out, path)


_BARE_ENUMERATOR = re.compile(r"^\s*(?:[ivxlcdm]+|\d+|[a-z])\s*[.)]?\s*$", re.IGNORECASE)


def _children_are_chapters(node: OutlineNode) -> bool:
    """Do the entries under a bookmark name chapters of their own, or only
    number the sections of one ("I", "II", "III")?"""
    named = sum(1 for c in node.children if not _BARE_ENUMERATOR.match(c.title))
    return named / len(node.children) >= 0.5


def reading_order(toc: Sequence[Sequence], page_count: int,
                  book_title: Optional[str] = None) -> List[OutlineItem]:
    """Chapters and in-chapter sub-headings, in reading order.

    - A top-level bookmark with nothing under it is a chapter.
    - One whose single child starts on the same page is a label printed over
      that child's title ("Chapter 1" / "Shyness and Social Anxiety"): one
      chapter, the label above it.
    - One with several children is a part: the children are its chapters
      (deeper levels become sub-headings inside them). If the part starts
      before its first child, the pages in between are a chapter of their
      own under the part's name.
    """
    rows = usable_entries(toc, page_count)
    if rows is None:
        return []
    roots = _drop_front_matter(_tree(rows), book_title)
    # A single bookmark wrapping everything is the book, not a part of it.
    while len(roots) == 1 and len(roots[0].children) >= MIN_CHAPTERS:
        roots = roots[0].children

    items: List[OutlineItem] = []
    for node in roots:
        if not node.children:
            items.append(OutlineItem("chapter", node.title, node.page))
            continue
        if len(node.children) == 1:
            child = node.children[0]
            if abs(child.page - node.page) <= 1:
                items.append(OutlineItem("chapter", child.title, child.page, label=node.title))
            else:
                # one entry filed under another a few pages on: two chapters
                items.append(OutlineItem("chapter", node.title, node.page))
                items.append(OutlineItem("chapter", child.title, child.page))
            _subheadings(child, items, [])
            continue
        if not _children_are_chapters(node):
            # "I", "II", "III" under an essay are its sections, not chapters
            items.append(OutlineItem("chapter", node.title, node.page))
            _subheadings(node, items, [])
            continue
        part = [node.title]
        first = True
        if node.page < node.children[0].page:
            items.append(OutlineItem("chapter", node.title, node.page, list(part), first_in_part=True))
            first = False
        for child in node.children:
            items.append(OutlineItem("chapter", child.title, child.page, list(part), first_in_part=first))
            first = False
            _subheadings(child, items, list(part))
    # A flat outline that names the same step in chapter after chapter
    # ("Beşinci Adım — Düzeltilmiş Yanıt" eleven times) is bookmarking the
    # sections of its chapters: a chapter title is not repeated, a section
    # heading in a fixed method is. Inside parts a repeat is legitimate
    # ("Giriş" opening each part), so only entries outside one count.
    repeats = Counter(squash(it.title) for it in items if it.kind == "chapter" and not it.path)
    for it in items:
        if it.kind == "chapter" and not it.path and it.label is None and repeats[squash(it.title)] > 1:
            it.kind = "subheading"
    items.sort(key=lambda it: it.page)  # stable: outline order within a page
    if sum(1 for it in items if it.kind == "chapter") < MIN_CHAPTERS:
        return []
    return items


# "BİR - Dogmacılık", "I. İki Dünya Görüşü", "Chapter 3 Getting…", "1. YASA":
# the printed page may set the number and the name on separate lines.
ENUMERATOR_PREFIX = re.compile(
    r"^\s*(?:(?:chapter|part|bölüm|kısım|kitap)\s+)?"
    r"(?:[ivxlcdm]+|\d+|[a-zçğıöşü]|bir|iki|üç|dört|beş|altı|yedi|sekiz|dokuz|on)"
    r"\s*[.):\-–—]\s*",
    re.IGNORECASE,
)


def title_variants(title: str) -> List[str]:
    """The forms a bookmark's title may be printed in on its page."""
    variants = [title]
    stripped = ENUMERATOR_PREFIX.sub("", title, count=1).strip()
    if stripped and stripped != title and len(squash(stripped)) >= 4:
        variants.append(stripped)
    for sep in (" - ", " – ", " — ", ": "):
        if sep in title:
            tail = title.split(sep, 1)[1].strip()
            if len(squash(tail)) >= 4 and tail not in variants:
                variants.append(tail)
    return variants
