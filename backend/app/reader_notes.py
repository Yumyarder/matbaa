"""The reader's own marks, carried back into the book.

A book read once with highlights and notes is a different book the second
time. Exported "notlarımla", a Matbaa book carries:

- a quiet mark on every passage the reader highlighted (an underline on the
  exact words where they sit inside one paragraph as plain text, otherwise
  a thin rule beside the paragraph), each with an anchor;
- an appendix, "Notlarım ve Sorularım", listing the reader's notes — their
  questions first — each linked to its passage.

Only text-node wrapping and attributes change: the book's own markup is
never rewritten, and a passage that cannot be found is simply not marked.
"""
from __future__ import annotations

import html
import re
from typing import Dict, List, Optional, Tuple

from app.clippings import BookClips
from app.models import ChapterOut
from app.notebook import _BLOCK, _plain, current_books, place_book, same_book
from app import notebook

APPENDIX_ID = "ch_reader_notes"
_PAGEBREAK = 'epub:type="pagebreak"'
_PAGEBREAK_GAP = r'(?:<span epub:type="pagebreak"[^>]*></span>)?'
CSS = """
/* the reader's own marks (exported "notlarımla") */
.reader-mark { text-decoration: underline; }
.reader-marked { border-left: 2px solid #999999; padding-left: 0.5em; }
.reader-notes h2 { font-size: 1.05em; text-align: left; page-break-before: auto; margin-top: 1.4em; }
.reader-notes .rn-quote { font-style: italic; text-indent: 0; margin: 0.9em 0 0.2em; }
.reader-notes .rn-note { text-indent: 0; margin: 0 0 0.3em 1em; }
.reader-notes .rn-link { text-indent: 0; margin: 0 0 0.6em 1em; font-size: 0.85em; }
"""


def book_for_session(session) -> Optional[BookClips]:
    """The Kindle highlights of this Matbaa book, if any were imported."""
    books = current_books()
    scored = sorted(((same_book(b.title, session.book_title or ""), b) for b in books), key=lambda t: -t[0])
    if scored and scored[0][0] >= 0.8:
        return notebook.with_edits(scored[0][1])
    return None


def _anchor(hid: str) -> str:
    return "hl-" + hid.split("-", 1)[-1]


def _mark_block(inner: str, clean: str, anchor: str) -> Tuple[str, bool]:
    """Wrap the passage inside one block's inner HTML when it is there as
    plain text; True when the words themselves were marked."""
    target = html.escape(clean, quote=False)
    if "<" in target:
        return inner, False
    at, end = inner.find(target), -1
    if at >= 0:
        end = at + len(target)
    elif _PAGEBREAK in inner:
        # a passage running over a printed page break has the page's empty
        # marker inside it; the underline goes around both
        m = re.search(_PAGEBREAK_GAP.join(re.escape(c) for c in target), inner)
        if m:
            at, end = m.start(), m.end()
    if at < 0:
        return inner, False
    return (inner[:at] + f'<span class="reader-mark" id="{anchor}">' + inner[at:end] + "</span>"
            + inner[end:]), True


def annotate(session, book: BookClips) -> Tuple[List[ChapterOut], int]:
    """Copies of the session's chapters with the reader's passages marked,
    plus the appendix chapter; and how many passages were marked."""
    placements = place_book(book, session)
    by_chapter: Dict[str, list] = {}
    for h in book.highlights:
        p = placements.get(h.id)
        if h.text and p:
            by_chapter.setdefault(p.chapter_id, []).append((h, p))

    marked: Dict[str, Tuple[str, str]] = {}     # highlight id -> (chapter file, anchor)
    chapters: List[ChapterOut] = []
    for ch in session.chapters:
        items = by_chapter.get(ch.id)
        if not items or ch.kind == "image":
            chapters.append(ch)
            continue
        text = ch.html or ""
        for h, p in items:
            anchor = _anchor(h.id)
            if f'id="{anchor}"' in text:
                continue

            def mark(m: "re.Match") -> str:
                tag, attrs, inner = m.group(1), m.group(2), m.group(3)
                if _plain(inner) != p.paragraph:
                    return m.group(0)
                new_inner, exact = _mark_block(inner, p.clean, anchor)
                if exact:
                    return f"<{tag}{attrs}>{new_inner}</{tag}>"
                cls = re.search(r'class="([^"]*)"', attrs)
                attrs2 = (attrs.replace(cls.group(0), f'class="{cls.group(1)} reader-marked"') if cls
                          else attrs + ' class="reader-marked"')
                if " id=" not in attrs2:
                    attrs2 += f' id="{anchor}"'
                return f"<{tag}{attrs2}>{inner}</{tag}>"

            new_text, n = _BLOCK.subn(mark, text, count=0)
            if new_text != text:
                text = new_text
                # the anchor is the span's id, or the paragraph's own id when it had one
                if f'id="{anchor}"' in text:
                    marked[h.id] = (f"{ch.id}.xhtml", anchor)
        chapters.append(ch.model_copy(update={"html": text}))

    appendix = _appendix(book, placements, marked)
    if appendix is not None:
        chapters.append(appendix)
    return chapters, len(marked)


def _appendix(book: BookClips, placements, marked) -> Optional[ChapterOut]:
    from app.obsidian import classify_note

    notes = [h for h in book.highlights if h.note and classify_note(h.note).kind != "link"]
    if not notes:
        return None
    questions = [h for h in notes if classify_note(h.note).kind == "question"]
    others = [h for h in notes if h not in questions]
    parts = ['<div class="reader-notes">']
    for title, items in (("Sorularım", questions), ("Notlarım", others)):
        if not items:
            continue
        parts.append(f"<h2>{title}</h2>")
        for h in items:
            kind = classify_note(h.note)
            if h.text:
                quote = h.text if len(h.text) <= 220 else h.text[:217].rsplit(" ", 1)[0] + "…"
                parts.append(f'<p class="rn-quote">“{html.escape(quote)}”</p>')
            label = "Ben: " if kind.kind == "idea" else ""
            parts.append(f'<p class="rn-note">{html.escape(label + (kind.text or h.note))}</p>')
            where = marked.get(h.id)
            p = placements.get(h.id)
            place = " · ".join(x for x in (f"s. {h.page}" if h.page else "", p.chapter_title if p else "") if x)
            if where:
                parts.append(f'<p class="rn-link"><a href="{where[0]}#{where[1]}">{html.escape(place or "pasaja git")}</a></p>')
            elif place:
                parts.append(f'<p class="rn-link">{html.escape(place)}</p>')
    parts.append("</div>")
    return ChapterOut(id=APPENDIX_ID, index=10_000, title="Notlarım ve Sorularım", kind="chapter",
                      html="".join(parts))


def count_for_session(session) -> Dict:
    book = book_for_session(session)
    if not book:
        return {"highlights": 0, "notes": 0}
    return {"highlights": sum(1 for h in book.highlights if h.text),
            "notes": sum(1 for h in book.highlights if h.note)}
