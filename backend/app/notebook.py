"""Where in the book each highlight is.

A highlight from the Kindle is a run of words and a Kindle location; the
book Matbaa made knows its chapters, sub-headings and paragraphs. Finding
the words in the book gives each highlight its place — chapter, section,
the whole paragraph around it — and its clean text: the book's own words
where a scanned edition's clipping says "yemden" or "bil- ginin".

Matching is done on folded text (letters and digits, Turkish-aware, dotted
and dotless i together, accents dropped), first exactly, then by the
passage's two ends, then by similarity, so a highlight from another
edition of the same book is still placed when it can be.
"""
from __future__ import annotations

import html
import json
import os
import re
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple

from app.clippings import BookClips, Clip, Highlight, group_books
from app.utils.vocab_repair import WORD, build_vocabulary

_ASCII = str.maketrans("çğışöüâîûêô", "cgisouaiueo")
_BLOCK = re.compile(r"<(p|h[1-6]|li|blockquote|figcaption)\b([^>]*)>(.*?)</\1>", re.S | re.I)
# the printed page marks the book carries (pdf_parser._pagebreak_html)
_PAGEBREAK = re.compile(r'<span epub:type="pagebreak"[^>]*\bid="page-([^"]+)"[^>]*></span>')
_MARK = chr(0xE100)        # a page mark's place while the block's text is made plain
ANCHOR = 24          # folded characters taken from each end of a passage
MIN_SIMILARITY = 0.82


def _fold_char(c: str) -> str:
    if c == "I":
        return "i"
    if c == "İ":
        return "i"
    return c.lower().translate(_ASCII)


def fold_ascii(text: str) -> str:
    return "".join(_fold_char(c) for c in text if c.isalnum())


def same_book(a: str, b: str) -> float:
    """How alike two book titles are, 0..1: "georges-politzer-felsefenin-
    baslangic-ilkeleri" names "Felsefenin Başlangıç İlkeleri"."""
    fa, fb = fold_ascii(a), fold_ascii(b)
    if not fa or not fb:
        return 0.0
    if fa == fb:
        return 1.0
    short, long_ = sorted((fa, fb), key=len)
    if len(short) >= 8 and short in long_:
        return 0.9
    # the Kindle cuts a long title off mid-word: "…ideolojik a" names
    # "İdeoloji ve Devletin İdeolojik Aygıtları"
    for x, y in ((fa, fb), (fb, fa)):
        k = len(x)
        while k >= 15 and not y.startswith(x[-k:]):
            k -= 1
        if k >= 15 and k >= 0.6 * len(y):
            return 0.85
    return SequenceMatcher(None, fa, fb).ratio()


@dataclass
class Block:
    chapter_id: str
    chapter_title: str
    kind: str              # "p" | "h" | "note"
    text: str
    subheading: Optional[str]
    page: Optional[str] = None                    # the printed page the block begins on
    marks: Tuple[Tuple[int, str], ...] = ()       # (character, page) where a new page begins inside it

    def page_at(self, char: int) -> Optional[str]:
        page = self.page
        for at, number in self.marks:
            if at <= char:
                page = number
        return page


@dataclass
class Placement:
    chapter_id: str
    chapter_title: str
    subheading: Optional[str]
    paragraph: str
    clean: str             # the book's own words for the passage
    exact: bool            # found word for word (after folding)
    pos: int = 0           # where in the folded book it starts
    quote: str = ""        # the words to keep: the book's or the Kindle's, whichever reads right
    quote_source: str = "kindle"
    page: Optional[str] = None     # the printed page it starts on, where the book carries page marks

    def to_dict(self) -> Dict:
        return asdict(self)


def _plain(fragment: str) -> str:
    fragment = re.sub(r"<sup[^>]*class=\"footnote-ref\"[^>]*>.*?</sup>", "", fragment, flags=re.S)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def _plain_marked(fragment: str) -> Tuple[str, Tuple[Tuple[int, str], ...]]:
    """A block's plain text, and where in it each printed page begins."""
    pages = _PAGEBREAK.findall(fragment)
    if not pages:
        return _plain(fragment), ()
    text = _plain(_PAGEBREAK.sub(" " + _MARK + " ", fragment))
    out: List[str] = []
    marks: List[Tuple[int, str]] = []
    k = 0
    for c in text:
        if c == _MARK:
            marks.append((len(out), pages[min(k, len(pages) - 1)]))
            k += 1
        elif c == " " and (not out or out[-1] == " "):
            continue
        else:
            out.append(c)
    while out and out[-1] == " ":
        out.pop()
    joined = "".join(out)
    return joined, tuple((min(at, len(joined)), number) for at, number in marks)


def book_blocks(session) -> List[Block]:
    """The book's readable text, block by block, in reading order, each
    block with the printed page it is on where the book carries them."""
    blocks: List[Block] = []
    page: Optional[str] = None
    for ch in session.chapters:
        if ch.kind == "image":
            continue
        sub = None
        for tag, attrs, inner in _BLOCK.findall(ch.html or ""):
            text, marks = _plain_marked(inner)
            start = page
            if marks:
                page = marks[-1][1]
            if not text:
                continue
            if tag.lower().startswith("h"):
                sub = text
                blocks.append(Block(ch.id, ch.title, "h", text, sub, start, marks))
            else:
                blocks.append(Block(ch.id, ch.title, "p", text, sub, start, marks))
        for fn in ch.footnotes or []:
            blocks.append(Block(ch.id, ch.title, "note", _plain(fn.text), sub, page))
    return blocks


class BookText:
    """The whole book folded into one string, with a way back from any
    folded position to its block and to the original characters."""

    def __init__(self, blocks: List[Block]):
        self.blocks = blocks
        chars: List[str] = []
        self.where: List[Tuple[int, int]] = []        # folded index -> (block, char in block)
        for bi, b in enumerate(blocks):
            for ci, c in enumerate(b.text):
                if c.isalnum():
                    chars.append(_fold_char(c))
                    self.where.append((bi, ci))
        self.folded = "".join(chars)

    def _span(self, start: int, end: int, exact: bool) -> Placement:
        bi, ci = self.where[start]
        bj, cj = self.where[end - 1]
        first = self.blocks[bi]
        if not exact:
            # a near match starts and ends on whole words
            while ci > 0 and first.text[ci - 1].isalnum():
                ci -= 1
            last_text = self.blocks[bj].text
            while cj + 1 < len(last_text) and last_text[cj + 1].isalnum():
                cj += 1
        if bi == bj:
            clean = first.text[ci:cj + 1]
        else:
            parts = [first.text[ci:]] + [self.blocks[k].text for k in range(bi + 1, bj)] + [self.blocks[bj].text[:cj + 1]]
            clean = "\n\n".join(parts)
        # the passage ends where its sentence's punctuation ends
        tail = self.blocks[bj].text[cj + 1:cj + 3]
        m = re.match(r"^[.!?…,;:)\"”’»]+", tail)
        if m:
            clean += m.group(0)
        return Placement(first.chapter_id, first.chapter_title, first.subheading, first.text, clean, exact, start,
                         page=first.page_at(ci))

    def occurrences(self, text: str, limit: int = 200) -> List[int]:
        q = fold_ascii(text)
        out, pos = [], self.folded.find(q) if q else -1
        while pos >= 0 and len(out) < limit:
            out.append(pos)
            pos = self.folded.find(q, pos + 1)
        return out

    def find(self, text: str) -> Optional[Placement]:
        q = fold_ascii(text)
        if len(q) < 3:
            return None
        hit = self.folded.find(q)
        if hit >= 0:
            if len(q) < 12 and self.folded.find(q, hit + 1) >= 0:
                return None                    # a short phrase found in many places is not a place
            return self._span(hit, hit + len(q), True)
        if len(q) < 2 * ANCHOR:
            return self._fuzzy(q)
        head, tail = q[:ANCHOR], q[-ANCHOR:]
        h = self.folded.find(head)
        while h >= 0:
            t = self.folded.find(tail, h + len(q) // 2)
            if 0 <= t <= h + len(q) * 1.3:
                return self._span(h, t + ANCHOR, False)
            h = self.folded.find(head, h + 1)
        return self._fuzzy(q)

    def _fuzzy(self, q: str) -> Optional[Placement]:
        """A misread letter or two at either end: look where a piece of the
        passage is found, and accept the window most like it."""
        if len(q) < 12:
            return None
        seeds = {q[i:i + 10] for i in range(0, len(q) - 10, max(5, len(q) // 6))}
        best: Tuple[float, int] = (0.0, -1)
        for seed in seeds:
            pos = self.folded.find(seed)
            tries = 0
            while pos >= 0 and tries < 20:
                offset = q.find(seed)
                start = max(0, pos - offset)
                window = self.folded[start:start + len(q)]
                r = SequenceMatcher(None, window, q, autojunk=False).ratio()
                if r > best[0]:
                    best = (r, start)
                pos = self.folded.find(seed, pos + 1)
                tries += 1
        if best[0] >= MIN_SIMILARITY:
            return self._aligned(best[1], q)
        return None

    def _aligned(self, start: int, q: str) -> Placement:
        """The window's edges moved onto where the passage really begins and
        ends, so a near match does not carry a neighbour's last letters."""
        lo = max(0, start - 12)
        window = self.folded[lo:start + len(q) + 12]
        blocks = [b for b in SequenceMatcher(None, window, q, autojunk=False).get_matching_blocks() if b.size >= 3]
        if not blocks:
            return self._span(start, min(len(self.folded), start + len(q)), False)
        begin = lo + blocks[0].a - blocks[0].b if blocks[0].b < 4 else lo + blocks[0].a
        last = blocks[-1]
        end = lo + last.a + last.size + max(0, len(q) - (last.b + last.size)) \
            if len(q) - (last.b + last.size) < 4 else lo + last.a + last.size
        begin = max(0, begin)
        return self._span(begin, min(len(self.folded), max(begin + 1, end)), False)


def tidy_quote(text: str) -> str:
    """A highlight as it should read: a word broken at a line end and the
    break carried into the clipping joined again ("bil- ginin",
    "Althusser’- den")."""
    text = re.sub(r"(?<=[^\W\d_])[-­]\s+(?=[a-zçğıöşü])", "", text)
    text = re.sub(r"(?<=[’'])[-­]\s*(?=[a-zçğıöşü])", "", text)
    if "\n\n" in text:
        return "\n\n".join(" ".join(p.split()) for p in text.split("\n\n"))
    return " ".join(text.split())


def _known(word: str, vocab: Counter) -> bool:
    return vocab.get(word.lower(), 0) >= 2


def choose_quote(kindle: str, book: str, exact: bool, vocab: Counter) -> "tuple[str, str]":
    """What the reader highlighted is kept, tidied; the book's words replace
    it only where the clipping is visibly damaged — a word the book never
    prints ("yemden") where the book has a word it does print ("yeniden").
    A scanned edition the reader did not read can be the worse of the two
    ("İröydcülükte" for "fröydcülükte"), so the book never wins by default."""
    if exact:
        return tidy_quote(kindle), "kindle"
    kw = [w for w in WORD.findall(tidy_quote(kindle)) if len(w) >= 3]
    bw = [w for w in WORD.findall(book) if len(w) >= 3]
    k_only = [w for w in kw if w not in bw]
    b_only = [w for w in bw if w not in kw]
    damaged = [w for w in k_only if not _known(w, vocab)]
    if damaged and b_only and all(_known(w, vocab) for w in b_only) and len(b_only) <= len(k_only) + 1:
        return tidy_quote(book), "kitap"
    return tidy_quote(kindle), "kindle"


def place_book(book: BookClips, session) -> Dict[str, Optional[Placement]]:
    """Each highlight's place in the book, keyed by its id; None where the
    words could not be found. A word or two highlighted alone is found in
    many places; it is placed between the highlights the Kindle recorded
    just before and after it."""
    blocks = book_blocks(session)
    text = BookText(blocks)
    vocab = Counter({w.lower(): n for w, n in build_vocabulary(b.text for b in blocks).items()})
    out: Dict[str, Optional[Placement]] = {}
    for h in book.highlights:
        out[h.id] = text.find(h.text) if h.text else None

    ordered = [h for h in book.highlights if h.text]
    for i, h in enumerate(ordered):
        if out[h.id] is not None:
            continue
        prev = next((out[o.id].pos for o in reversed(ordered[:i]) if out[o.id]), -1)
        nxt = next((out[o.id].pos for o in ordered[i + 1:] if out[o.id]), len(text.folded))
        hits = text.occurrences(h.text)
        inside = [p for p in hits if prev <= p <= nxt]
        after = [p for p in hits if p >= prev]
        pick = (inside or after or hits or [None])[0]
        if pick is not None:
            out[h.id] = text._span(pick, pick + len(fold_ascii(h.text)), True)

    for h in book.highlights:
        p = out[h.id]
        if p is not None:
            p.quote, p.quote_source = choose_quote(h.text, p.clean, p.exact, vocab)
    return out


def best_project(book: BookClips, projects: List[Dict]) -> Optional[Dict]:
    """The saved Matbaa book this Kindle book is, if any."""
    scored = sorted(((same_book(book.title, p.get("book_title") or ""), p) for p in projects),
                    key=lambda t: -t[0])
    if scored and scored[0][0] >= 0.8:
        return scored[0][1]
    return None


def highlight_view(h: Highlight, placement: Optional[Placement]) -> Dict:
    d = h.to_dict()
    d["placement"] = placement.to_dict() if placement else None
    d["quote"] = placement.quote if placement else tidy_quote(h.text)
    d["changed"] = bool(placement and placement.quote_source == "kitap" and fold_ascii(placement.clean) != fold_ascii(h.text))
    return d


# --- what has been imported, kept between sessions -------------------------------------------

def notebook_dir() -> str:
    return os.environ.get("MATBAA_NOTEBOOK") or os.path.join(os.path.expanduser("~"), "Matbaa", "notebook")


def _clips_file() -> str:
    return os.path.join(notebook_dir(), "clippings.json")


def load_clips() -> List[Clip]:
    try:
        with open(_clips_file(), encoding="utf-8") as f:
            raw = json.load(f)
        return [Clip(**{k: unicodedata.normalize("NFC", v) if isinstance(v, str) else v for k, v in d.items()})
                for d in raw]
    except (OSError, ValueError, TypeError):
        return []


def import_clips(new: List[Clip]) -> int:
    """Add clippings to what is kept, each once; returns how many were new.
    My Clippings only ever grows, so importing it again adds nothing twice."""
    kept = load_clips()
    seen = {(c.book, c.kind, c.text, c.loc_start, c.added) for c in kept}
    added = 0
    for c in new:
        key = (c.book, c.kind, c.text, c.loc_start, c.added)
        if key not in seen:
            seen.add(key)
            kept.append(c)
            added += 1
    os.makedirs(notebook_dir(), exist_ok=True)
    tmp = _clips_file() + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump([asdict(c) for c in kept], f, ensure_ascii=False)
    os.replace(tmp, _clips_file())
    return added


def current_books() -> List[BookClips]:
    return group_books(load_clips())


# --- answers the reader brought back for their questions ----------------------------------------

def _answers_file() -> str:
    return os.path.join(notebook_dir(), "answers.json")


def load_answers() -> Dict[str, Dict]:
    """highlight id -> {"text", "source", "saved"}: what ChatGPT (or a
    configured model) answered to the reader's question on that passage."""
    try:
        with open(_answers_file(), encoding="utf-8") as f:
            return json.load(f) or {}
    except (OSError, ValueError):
        return {}


def save_answer(highlight_id: str, text: str, source: str = "chatgpt") -> Dict[str, Dict]:
    import datetime as _dt

    answers = load_answers()
    text = (text or "").strip()
    if text:
        answers[highlight_id] = {"text": text, "source": source, "saved": _dt.date.today().isoformat()}
    else:
        answers.pop(highlight_id, None)
    os.makedirs(notebook_dir(), exist_ok=True)
    tmp = _answers_file() + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(answers, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _answers_file())
    return answers


# --- the reader's corrections to their own notes -------------------------------------------------

def _edits_file() -> str:
    return os.path.join(notebook_dir(), "edits.json")


def load_edits() -> Dict[str, str]:
    """highlight id -> the note as the reader corrected it (Turkish letters
    restored on their click, or retyped)."""
    try:
        with open(_edits_file(), encoding="utf-8") as f:
            return json.load(f) or {}
    except (OSError, ValueError):
        return {}


def save_edits(changes: Dict[str, Optional[str]]) -> Dict[str, str]:
    edits = load_edits()
    for hid, note in changes.items():
        if note is None or not str(note).strip():
            edits.pop(hid, None)
        else:
            edits[hid] = str(note).strip()
    os.makedirs(notebook_dir(), exist_ok=True)
    tmp = _edits_file() + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(edits, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _edits_file())
    return edits


def with_edits(book: BookClips) -> BookClips:
    """The book with the reader's corrected notes in place; the note as the
    Kindle wrote it is kept alongside, so a passage pasted in with the old
    wording is still recognised."""
    from dataclasses import replace

    edits = load_edits()
    if not edits:
        return book
    out = []
    for h in book.highlights:
        if h.id in edits and h.note and edits[h.id] != h.note:
            out.append(replace(h, note=edits[h.id], note_original=h.note))
        else:
            out.append(h)
    return replace(book, highlights=out)


# --- the last reading session, and a quote for today ---------------------------------------------

def last_session(book: BookClips) -> Optional[Dict]:
    """The latest day the reader marked this book, and what they marked."""
    from app.clippings import parse_added

    days: Dict = {}
    for h in book.highlights:
        day = parse_added(h.added) if h.added else None
        if day:
            days.setdefault(day, []).append(h)
    if not days:
        return None
    day = max(days)
    items = days[day]
    return {"date": day.isoformat(), "highlights": sum(1 for h in items if h.text),
            "notes": sum(1 for h in items if h.note)}

