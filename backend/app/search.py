"""Search in a book, or in every book saved in Matbaa — the ground of
"Kitapla sohbet".

Each readable block of a book (book_blocks: paragraphs and notes, with the
printed page they are on) is indexed by its words' headwords
(app/turkish_words.py through the Turkish dictionary, when it is made) or,
without the dictionary, by the words folded to plain letters; a question
finds its blocks by BM25, the ranking search engines use. Nothing here needs
a model or the network: the passages found are shown as they are, with
their pages, and the same passages are what a model (or ChatGPT, pasted to
by the reader) is asked about.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from app.notebook import book_blocks, fold_ascii
from app.turkish_words import lower_tr

WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?|\d+", re.UNICODE)
# words a question is made of that say nothing about what is asked
QUESTION_WORDS = {fold_ascii(w) for w in (
    "ne nedir neden niçin nasıl hangi kim kimdir kime kimin nerede ne zaman mı mi mu mü midir mıdır "
    "bu şu o bir ve ile ya da de da ki için gibi kadar göre olan olarak diye ise ama fakat yani "
    "yazar yazara kitap kitapta kitabın söylüyor anlatıyor diyor ediyor ne demek açıkla anlat "
    "the a an of to in is what why how who which does do".split())}
K1, B = 1.4, 0.75
SNIPPET = 320


@dataclass
class Hit:
    session_id: str
    book_title: str
    chapter_id: str
    chapter_title: str
    page: Optional[str]
    text: str
    score: float
    block: int

    def to_dict(self) -> Dict:
        return asdict(self)


class BookIndex:
    """One book's blocks, indexed by their words' headwords."""

    def __init__(self, session, lemma: Optional[Callable[[str], Optional[str]]] = None):
        self.session_id = session.session_id
        self.title = session.book_title
        self.lemma = lemma
        self.blocks = [b for b in book_blocks(session) if b.kind in ("p", "note") and len(b.text) > 20]
        self.postings: Dict[str, Dict[int, int]] = defaultdict(dict)
        self.lengths: List[int] = []
        for i, b in enumerate(self.blocks):
            terms = self.terms(b.text)
            self.lengths.append(len(terms))
            for t, n in Counter(terms).items():
                self.postings[t][i] = n
        self.avg = (sum(self.lengths) / len(self.lengths)) if self.lengths else 1.0

    def term(self, word: str) -> str:
        w = re.split(r"['’]", word)[0]
        if self.lemma and not w.isdigit():
            head = self.lemma(w)
            if head:
                return fold_ascii(head)
        return fold_ascii(lower_tr(w))

    def terms(self, text: str) -> List[str]:
        return [self.term(m.group(0)) for m in WORD.finditer(text or "") if len(m.group(0)) > 1]

    def search(self, query_terms: List[str], limit: int = 10) -> List[Tuple[float, int]]:
        n = len(self.blocks)
        scores: Dict[int, float] = defaultdict(float)
        for t in set(query_terms):
            posting = self.postings.get(t)
            if not posting:
                continue
            idf = math.log(1 + (n - len(posting) + 0.5) / (len(posting) + 0.5))
            for i, tf in posting.items():
                norm = tf * (K1 + 1) / (tf + K1 * (1 - B + B * self.lengths[i] / self.avg))
                scores[i] += idf * norm
        return sorted(((s, i) for i, s in scores.items()), reverse=True)[:limit]


def query_terms(index: BookIndex, question: str) -> List[str]:
    words = [m.group(0) for m in WORD.finditer(question or "") if len(m.group(0)) > 1]
    kept = [w for w in words if fold_ascii(w) not in QUESTION_WORDS]
    return [index.term(w) for w in (kept or words)]


def _snippet(text: str, terms: Iterable[str], index: BookIndex) -> str:
    if len(text) <= SNIPPET:
        return text
    wanted = set(terms)
    first = next((m.start() for m in WORD.finditer(text) if index.term(m.group(0)) in wanted), 0)
    start = max(0, first - SNIPPET // 3)
    start = text.rfind(" ", 0, start) + 1 if start else 0
    cut = text[start:start + SNIPPET]
    cut = cut[:cut.rfind(" ")] if len(text) > start + SNIPPET else cut
    return ("…" if start else "") + cut + ("…" if start + SNIPPET < len(text) else "")


def _page(block) -> Optional[str]:
    """The printed page or pages a passage stands on: "41", or "12–13" for
    one that runs over a page."""
    first = block.page_at(0) or (block.marks[0][1] if block.marks else None)
    last = block.marks[-1][1] if block.marks else first
    return first if first == last or not last else f"{first}–{last}"


def search(indexes: List[BookIndex], question: str, limit: int = 10) -> List[Hit]:
    hits: List[Hit] = []
    for index in indexes:
        terms = query_terms(index, question)
        for score, i in index.search(terms, limit):
            b = index.blocks[i]
            hits.append(Hit(index.session_id, index.title, b.chapter_id, b.chapter_title, _page(b),
                            _snippet(b.text, terms, index), round(score, 3), i))
    # the same passage from another saved copy of the same book is shown once
    out: List[Hit] = []
    seen = set()
    for h in sorted(hits, key=lambda h: -h.score):
        key = fold_ascii(h.text)[:240]
        if key in seen:
            continue
        seen.add(key)
        out.append(h)
    return out[:limit]


def passages(indexes: List[BookIndex], question: str, limit: int = 10) -> List[Hit]:
    """The blocks a question is about, whole (not cut to a snippet)."""
    out = []
    by_id = {ix.session_id: ix for ix in indexes}
    for h in search(indexes, question, limit):
        b = by_id[h.session_id].blocks[h.block]
        out.append(Hit(h.session_id, h.book_title, h.chapter_id, h.chapter_title, h.page, b.text, h.score, h.block))
    return out
