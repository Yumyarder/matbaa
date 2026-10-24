"""An index for a book that has none: names, and the reader's own concepts.

Most of the library has no printed index. Two kinds of entry can be found
without a model, and both are worth a reader's time:

- **Names** (people, places, parties, books). Turkish spelling gives a
  proper noun away: its suffix stands behind an apostrophe ("Marx'ın",
  "Lenin'e", "TİP'in"), and away from a sentence's start it keeps its
  capital. A word counts when the book uses it so, more than once, and does
  not also use it as a common word in small letters; consecutive capitalised
  words are one name ("Antonio Gramsci", "Paris Komünü"), and a surname
  alone is counted under the one full name it ends. Headings, the months
  and days, and roman numerals are left out.
- **Concepts from the reader's vault**: the titles and aliases of their
  Obsidian notes, wherever the book uses them, in any of their forms
  ("müştereklerin" under "Müşterek"). The index then shows the reader's
  own network inside the book.

Each place is the printed page the book marks (`<a href="#page-N">`, which
the builder points at the chapter that holds the page); a book without
printed pages gets numbered links to the paragraphs themselves, given an id
in the exported copy only. A term found on nearly every page is no help in
an index and is dropped.
"""
from __future__ import annotations

import html
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

from app.notebook import Block, book_blocks, fold_ascii

TOKEN = re.compile(r"[^\W\d_][^\W_]*(?:[-‐][^\W\d_]+)?(?:['’][^\W\d_]+)?", re.UNICODE)
APOSTROPHE = re.compile(r"['’]")
SENTENCE_END = re.compile(r"[.!?…:]\s*[\"“”'’»)]*\s*$")
UPPER = re.compile(r"^[A-ZÇĞİÖŞÜÂÎÛ]")
ROMAN = re.compile(r"^[IVXLCDM]+$")
MIN_NAME = 3            # times a one-word name must be used as one
MIN_MULTI = 2           # a name of several words
MAX_SHARE = 0.5         # of the book's pages (or paragraphs): more, and the term is no help in an index
MAX_PLACES = 60
STOP = {fold_ascii(w) for w in (
    "Ocak Şubat Mart Nisan Mayıs Haziran Temmuz Ağustos Eylül Ekim Kasım Aralık "
    "Pazartesi Salı Çarşamba Perşembe Cuma Cumartesi Pazar Bölüm Giriş Sonuç Önsöz Sonsöz Ek Bkz Ayrıca "
    "Tablo Şekil Not Notlar Kaynakça Dizin İçindekiler Sayfa Cilt Ed Çev Der Haz Age Agy Ibid Op Cit "
    "The And Of In To For On With By From At As Is It This That Or Bu Şu O Bir Ve İle Ama Fakat "
    "Ancak Çünkü Eğer Ne Nasıl Neden Hangi Her Hiç Daha En Çok Gibi Kadar Sonra Önce Şimdi Yani "
    "Böylece Dolayısıyla Örneğin Bunun Bunu Buna Onun Onu Ona Biz Siz Onlar Ben Sen".split())}
JOINERS = {"de", "da", "van", "von", "der", "den", "la", "le", "du", "bin", "ibn", "el", "al"}
# nationalities and languages: Turkish capitalises them, an index does not list them
NATIONS = {fold_ascii(w) for w in (
    "Türk Türkçe Alman Almanca Fransız Fransızca İngiliz İngilizce Rus Rusça Yunan Yunanca Amerikan Amerikalı "
    "İtalyan İtalyanca İspanyol İspanyolca Japon Japonca Çinli Arap Arapça Kürt Kürtçe Ermeni Ermenice Avrupalı "
    "Osmanlıca Farsça Latince Hollandalı Polonyalı Macar Bulgar Sırp Hırvat Arnavut Yahudi Hristiyan Müslüman "
    "Batılı Doğulu Asyalı Afrikalı Latin".split())}
# the book's apparatus: names there are references, not the book's subjects
APPARATUS = re.compile(r"kaynak|bibliyograf|bibliograph|references|works cited|okuma listesi|dizin|index|"
                       r"\bnot(?:lar|ları)\b|\bsonnotlar|endnotes|\bnotes\b", re.I)
# a case or possessive ending on a name written without its apostrophe
# ("Marksizmin", "Komünün"): counted under the name itself
CASE_ENDING = re.compile(r"(?:n?[ıiuü]n|[ıiuü]|y?[ae]|[dt][ae]n?|l[ae]|n[ıiuü]n|s[ıiuü])$")


def _subject_blocks(blocks: List[Block]) -> List[Tuple[int, Block]]:
    """The blocks of the book's own text: not its headings, notes or
    bibliography."""
    return [(i, b) for i, b in enumerate(blocks)
            if b.kind == "p" and not APPARATUS.search(b.chapter_title or "")]


@dataclass
class Place:
    chapter_id: str
    page: Optional[str]
    block: int              # the block's index in the book (book_blocks)


@dataclass
class Entry:
    term: str
    kind: str               # "ad" | "kavram"
    places: List[Place] = field(default_factory=list)
    count: int = 0

    def pages(self) -> List[str]:
        """The printed pages, in the book's order."""
        out: List[str] = []
        for p in sorted(self.places, key=lambda p: p.block):
            if p.page and p.page not in out:
                out.append(p.page)
        return out


def _base(token: str) -> str:
    return APOSTROPHE.split(token)[0]


def _is_capital(word: str) -> bool:
    return bool(UPPER.match(word)) and not word.isupper()


def _acronym(word: str) -> bool:
    return word.isupper() and 2 <= len(word) <= 5 and not ROMAN.match(word)


def find_names(blocks: List[Block]) -> Dict[str, Entry]:
    """Names the book uses, each with the blocks it stands in."""
    lower_uses: Dict[str, int] = defaultdict(int)
    text_blocks = _subject_blocks(blocks)
    for _, b in text_blocks:
        for m in TOKEN.finditer(b.text):
            w = _base(m.group(0))
            if w[:1].islower():
                lower_uses[fold_ascii(w)] += 1

    found: Dict[str, Entry] = {}
    strong: Dict[str, int] = defaultdict(int)
    for bi, b in text_blocks:
        tokens = list(TOKEN.finditer(b.text))
        k = 0
        while k < len(tokens):
            m = tokens[k]
            word = _base(m.group(0))
            initial = k == 0 or bool(SENTENCE_END.search(b.text[:m.start()]))
            if not (_is_capital(word) or (_acronym(word) and not lower_uses.get(fold_ascii(word)))):
                k += 1
                continue
            # the run of capitalised words that make one name
            run = [m]
            j = k + 1
            while j < len(tokens) and len(run) < 4:
                gap = b.text[run[-1].end():tokens[j].start()]
                nxt = tokens[j].group(0)
                if gap.strip() or APOSTROPHE.search(run[-1].group(0)):
                    break
                if _is_capital(_base(nxt)) or (_base(nxt).lower() in JOINERS and j + 1 < len(tokens)
                                               and _is_capital(_base(tokens[j + 1].group(0)))):
                    run.append(tokens[j])
                    j += 1
                    continue
                break
            while run and _base(run[-1].group(0)).lower() in JOINERS:
                run.pop()
            words = [_base(t.group(0)) for t in run]
            if initial and len(words) > 1 and (fold_ascii(words[0]) in STOP or lower_uses.get(fold_ascii(words[0]))):
                words, run = words[1:], run[1:]      # "Bu Gramsci'nin…": the sentence's first word is no part of it
            name = " ".join(words)
            key = fold_ascii(name)
            marked = bool(APOSTROPHE.search(run[-1].group(0))) if run else False
            if key and (not initial or marked or len(words) > 1) and fold_ascii(words[0]) not in STOP \
                    and not ROMAN.match(words[0]) and len(key) >= 2 and key not in NATIONS:
                e = found.setdefault(key, Entry(name, "ad"))
                e.places.append(Place(b.chapter_id, b.page_at(m.start()), bi))
                e.count += 1
                if marked:
                    strong[key] += 1
            k = j if len(run) > 1 else k + 1

    # the book's own headings, quoted in its text ("Üçüncü Bölüm", a chapter's title)
    raw = {b.chapter_title or "" for b in blocks} | {b.text for b in blocks if b.kind == "h"}
    headings = {fold_ascii(h) for h in raw}
    titled = {fold_ascii(h.split(":")[0]) for h in raw if ":" in h}      # "Paylaşılan Heterotopyalar: Atina'daki…"
    keep: Dict[str, Entry] = {}
    for key, e in found.items():
        words = e.term.split()
        if key in headings or any(fold_ascii(w) in ("bolum", "kisim", "fasil") for w in words) \
                or (len(words) > 1 and key in titled):
            continue
        need = MIN_MULTI if len(words) > 1 else MIN_NAME
        if e.count < need:
            continue
        # a word the book also writes in small letters is a common word
        # capitalised, unless the apostrophe marks it as a name
        if len(words) == 1 and lower_uses.get(key, 0) * 2 > e.count and strong.get(key, 0) < 2:
            continue
        if len(words) == 1 and e.term.isupper() and strong.get(key, 0) == 0 and e.count < 2 * MIN_NAME:
            continue
        keep[key] = e

    # a name with a case ending, counted under the name ("Sol Kemalizmin" under "Sol Kemalizm")
    for key, e in sorted(keep.items(), key=lambda kv: -len(kv[0])):
        last = e.term.split()[-1]
        m = CASE_ENDING.search(last)
        if not m or len(last) - len(m.group(0)) < 3:
            continue
        stem_term = e.term[:len(e.term) - len(m.group(0))]
        target = keep.get(fold_ascii(stem_term))
        if target is not None and target is not e:
            target.places += e.places
            target.count += e.count
            del keep[key]

    # a surname alone counted under the one full name it ends
    for key, e in list(keep.items()):
        if len(e.term.split()) != 1:
            continue
        fuller = [f for f in keep.values() if len(f.term.split()) > 1 and fold_ascii(f.term.split()[-1]) == key]
        if len(fuller) == 1:
            fuller[0].places += e.places
            fuller[0].count += e.count
            del keep[key]
    return keep


def find_concepts(blocks: List[Block], concepts: Dict[str, str],
                  lemma: Optional[Callable[[str], Optional[str]]] = None) -> Dict[str, Entry]:
    """The reader's concepts the book uses. `concepts`: folded name or alias
    -> the note's name."""
    singles: Dict[str, str] = {}
    phrases: List[Tuple[str, str]] = []
    for folded_name, note in concepts.items():
        words = folded_name.split()
        if not folded_name or len(folded_name) < 3:
            continue
        if len(words) == 1:
            singles[folded_name] = note
        else:
            phrases.append((folded_name, note))
    out: Dict[str, Entry] = {}
    for bi, b in _subject_blocks(blocks):
        for m in TOKEN.finditer(b.text):
            w = _base(m.group(0))
            f = fold_ascii(w)
            note = singles.get(f)
            if note is None and lemma:
                head = lemma(w)
                note = singles.get(fold_ascii(head)) if head else None
            if note:
                e = out.setdefault(fold_ascii(note), Entry(note, "kavram"))
                e.places.append(Place(b.chapter_id, b.page_at(m.start()), bi))
                e.count += 1
        if phrases:
            spaced = " ".join(fold_ascii(t.group(0)) for t in TOKEN.finditer(b.text))
            for phrase, note in phrases:
                for _ in re.finditer(r"(?<!\w)" + re.escape(phrase) + r"\w*", spaced):
                    e = out.setdefault(fold_ascii(note), Entry(note, "kavram"))
                    e.places.append(Place(b.chapter_id, b.page, bi))
                    e.count += 1
    return out


# --- the index chapter ------------------------------------------------------------

_TR_ORDER = "aâbcçdefgğhıiîjklmnoöprsştuüûvyzqwx"


def sort_key(term: str) -> List[int]:
    """Turkish alphabetical order: c before ç, ı before i, o before ö."""
    low = term.replace("I", "ı").replace("İ", "i").lower()
    return [(_TR_ORDER.index(c) if c in _TR_ORDER else 100 + ord(c)) for c in low if c.isalnum() or c == " "]


def _letter(term: str) -> str:
    first = term[:1]
    return first.replace("i", "İ").replace("ı", "I").upper()


def has_printed_index(chapters) -> bool:
    return any('class="index-entry' in (ch.html or "") for ch in chapters)


def build(session, concepts: Optional[Dict[str, str]] = None,
          lemma: Optional[Callable[[str], Optional[str]]] = None,
          removed: Iterable[str] = ()) -> List[Entry]:
    """The index of a book without one: names and the reader's concepts."""
    blocks = book_blocks(session)
    gone = {fold_ascii(t) for t in removed}
    entries = dict(find_names(blocks))
    for key, e in (find_concepts(blocks, concepts, lemma) if concepts else {}).items():
        if key in entries:
            entries[key].kind = "kavram"          # a name the reader has a note for
        else:
            entries[key] = e
    paged = any(b.page for b in blocks) or any(b.marks for b in blocks)
    total = len({b.page_at(0) for b in blocks if b.page or b.marks}) if paged else len(blocks)
    out = []
    for key, e in entries.items():
        if key in gone:
            continue
        spread = len(e.pages()) if paged else len({p.block for p in e.places})
        if total and spread > max(8, MAX_SHARE * total) or spread > MAX_PLACES:
            continue
        out.append(e)
    return sorted(out, key=lambda e: sort_key(e.term))


def chapter_html(entries: List[Entry], paged: bool) -> str:
    """The index's HTML: letter headings, one entry a line, its places
    linked. A book with printed pages links "#page-N"; one without links the
    paragraphs, numbered, by the ids `anchor_ids` gives them."""
    parts: List[str] = []
    letter = None
    for e in entries:
        first = _letter(e.term)
        if first != letter:
            letter = first
            parts.append(f'<p class="index-letter">{html.escape(first)}</p>')
        if paged:
            links = ", ".join(f'<a href="#page-{html.escape(p)}">{html.escape(p)}</a>' for p in e.pages())
        else:
            seen: List[Tuple[str, int]] = []
            for p in sorted(e.places, key=lambda p: p.block):
                if (p.chapter_id, p.block) not in seen:
                    seen.append((p.chapter_id, p.block))
            links = ", ".join(f'<a href="{cid}.xhtml#ix-{bi}">{k}</a>' for k, (cid, bi) in enumerate(seen, 1))
        if not links:
            continue
        mark = " ◦" if e.kind == "kavram" else ""
        parts.append(f'<p class="index-entry">{html.escape(e.term)}{mark}, {links}</p>')
    return "".join(parts)


_P_OPEN = re.compile(r"<p(?=[\s>])")


def anchor_ids(session, entries: List[Entry]) -> Dict[str, str]:
    """chapter id -> its HTML with an id on each paragraph the index points
    at (the exported copy only; book_blocks' numbering)."""
    wanted: Dict[str, Set[int]] = defaultdict(set)
    for e in entries:
        for p in e.places:
            wanted[p.chapter_id].add(p.block)
    if not wanted:
        return {}
    # book_blocks numbers the readable blocks book-wide; walk the same way
    from app.notebook import _BLOCK, _plain_marked
    out: Dict[str, str] = {}
    index = 0
    for ch in session.chapters:
        if ch.kind == "image":
            continue
        html_text = ch.html or ""
        pieces: List[str] = []
        last = 0
        for m in _BLOCK.finditer(html_text):
            text, _ = _plain_marked(m.group(3))
            if not text:
                continue
            if index in wanted.get(ch.id, ()) and m.group(1).lower() == "p" and "id=" not in m.group(2):
                start = m.start()
                pieces.append(html_text[last:start])
                pieces.append(f'<p id="ix-{index}"' + html_text[start + 2:m.end()])
                last = m.end()
            index += 1
        index += len(ch.footnotes or [])
        if pieces:
            pieces.append(html_text[last:])
            out[ch.id] = "".join(pieces)
    return out


def concept_index(vault: str, settings: Optional[Dict] = None) -> Dict[str, str]:
    """The reader's concepts: folded name or alias (words kept apart) -> the
    note's name. The vault keeps them in its concept folders ("6 - Tags",
    "3 - Gelişen Notlar", "4 - Tam Notlar"); its sources, its inbox and the
    pages Matbaa keeps are not concepts. A name with digits (a dated note)
    or of more than five words is a note, not a term."""
    import os

    from app.obsidian import (DASHBOARD, IDEAS_PAGE, SKIP_DIRS, _find_dir, _note_aliases, developing_folder,
                              fold_ascii_keep_spaces, tags_folder)

    skip_pages = {DASHBOARD, IDEAS_PAGE, "Kelime Defteri", "AGENTS", "README"}
    folders = {tags_folder(vault, settings), developing_folder(vault, settings),
               _find_dir(vault, "tam not") or os.path.join(vault, "4 - Tam Notlar")}
    out: Dict[str, str] = {}
    for folder in sorted(f for f in folders if f and os.path.isdir(f)):
        for root, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and "template" not in d.lower()]
            for f in files:
                name = f[:-3]
                if not f.endswith(".md") or name in skip_pages or re.search(r"\d", name) or len(name.split()) > 5:
                    continue
                for k, label in enumerate([name] + _note_aliases(os.path.join(root, f))):
                    key = fold_ascii_keep_spaces(label).replace(" ?", "").strip()
                    # a short one-word alias ("zor" for Tahakküm) is an everyday word in a book
                    if len(key) >= 3 and not (k and " " not in key and len(key) < 5):
                        out.setdefault(key, name)
    return out
