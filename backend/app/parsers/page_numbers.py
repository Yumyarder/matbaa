"""Which printed page each PDF page is.

A PDF's page index is not the book's page number: a cover and front matter
come first, plates are printed on leaves the numbering skips, a scanner
misses a page. The numbers printed in the margins (pdf_parser._detect_folios)
say what pages are called; this settles, for every page, the number a
reader would cite — or none, where the book does not say.

- A *run* is at least RUN_MIN folios in a row whose number minus the page
  index is the same.
- The book's numbering is the chain of runs, in page order, that the most
  folios agree on, with numbers that only increase and never jump ahead by
  more than MAX_SKIP pages. A list or figure numbered in the margin
  ("7, 8, 9"), or a folio a scanner read with the rule beside it as a
  leading one ("|157" -> "1157"), is a run the chain leaves out.
- A page inside a run takes its offset. Between two runs the pages are
  numbered on from the run before; where the next run's offset is lower,
  the numbering skipped that many pages (plates, inserts) and those get no
  number, the pages without text first, since a plate carries none.
- Before the first run and after the last, the nearest run's offset holds
  for EXTEND pages, from page 1 up: a chapter's opening page rarely prints
  its folio, and front matter numbered in roman comes out below 1. Further
  out the book does not say, and a page-list that is silent is better than
  one that is wrong; nor past a run the chain left out, where the book is
  numbered some other way (a second volume bound in).
- Two printed pages on one PDF page (a scanned spread) make no run at all:
  such a book gets no page numbers.
"""
from __future__ import annotations

from collections import Counter
from typing import Container, Dict, List, NamedTuple, Optional, Tuple

RUN_MIN = 3
MAX_SKIP = 50
EXTEND = 20


class Run(NamedTuple):
    first: int      # PDF page index of its first folio
    last: int       # … and of its last
    offset: int     # printed number - page index
    folios: int     # how many folios it is made of


def _read_again(folios: Dict[int, int]) -> Dict[int, int]:
    """A scanner reads the rule printed beside a folio as a leading one:
    "|157" comes back "1157". Without that one, such a folio agrees with the
    offset most of the book's folios have; where it does, that is the
    number."""
    def without_one(n: int) -> Optional[int]:
        s = str(n)
        return int(s[1:]) if len(s) >= 3 and s[0] == "1" and s[1] != "0" else None

    votes = Counter()
    for page, n in folios.items():
        votes[n - page] += 1
        alt = without_one(n)
        if alt is not None:
            votes[alt - page] += 1
    if not votes:
        return folios
    usual = votes.most_common(1)[0][0]
    fixed = dict(folios)
    for page, n in folios.items():
        alt = without_one(n)
        if n - page != usual and alt is not None and alt - page == usual:
            fixed[page] = alt
    return fixed


def _runs(folios: Dict[int, int]) -> List[Run]:
    found: List[Run] = []
    pages = sorted(folios)
    start = 0
    for i in range(1, len(pages) + 1):
        if i < len(pages) and folios[pages[i]] - pages[i] == folios[pages[start]] - pages[start]:
            continue
        if i - start >= RUN_MIN:
            found.append(Run(pages[start], pages[i - 1], folios[pages[start]] - pages[start], i - start))
        start = i
    return found


def _follows(a: Run, b: Run) -> bool:
    return (b.first + b.offset > a.last + a.offset          # numbers increase
            and b.offset - a.offset <= MAX_SKIP)            # no leap ahead


def numbering(folios: Dict[int, int]) -> Tuple[List[Run], List[Run]]:
    """The runs the book's numbering is made of, in page order; and the
    runs it leaves out."""
    runs = _runs(_read_again(folios))
    if not runs:
        return [], []
    best: List[tuple] = []          # (folios in the best chain ending here, previous run)
    for i, run in enumerate(runs):
        score, prev = run.folios, None
        for j in range(i):
            if best[j][0] + run.folios > score and _follows(runs[j], run):
                score, prev = best[j][0] + run.folios, j
        best.append((score, prev))
    i: Optional[int] = max(range(len(runs)), key=lambda k: best[k][0])
    chain: List[Run] = []
    while i is not None:
        chain.append(runs[i])
        i = best[i][1]
    chain.reverse()
    left_out = [r for r in runs if r not in chain]
    merged: List[Run] = []
    for run in chain:
        if merged and merged[-1].offset == run.offset:
            m = merged[-1]
            merged[-1] = Run(m.first, run.last, run.offset, m.folios + run.folios)
        else:
            merged.append(run)
    return merged, left_out


def printed_pages(folios: Dict[int, int], page_count: int,
                  text_pages: Optional[Container[int]] = None) -> Dict[int, int]:
    """PDF page index -> printed page number, for the pages the book numbers.
    `text_pages`, if given, holds the pages that carry text."""
    runs, left_out = numbering(folios)
    if not runs:
        return {}
    pages: Dict[int, int] = {}
    head, tail = runs[0], runs[-1]
    # beyond the chain, a run it left out says the pages there are numbered
    # otherwise (a second volume bound in): the extension stops at it
    start = max([head.first - EXTEND, 0] + [r.last + 1 for r in left_out if r.last < head.first])
    end = min([tail.last + 1 + EXTEND, page_count] + [r.first for r in left_out if r.first > tail.last])
    for page in range(start, head.first):
        if page + head.offset >= 1:
            pages[page] = page + head.offset

    for run, nxt in zip(runs, runs[1:] + [None]):
        for page in range(run.first, run.last + 1):
            pages[page] = page + run.offset
        if nxt is None:
            break
        gap = list(range(run.last + 1, nxt.first))
        skipped = max(0, run.offset - nxt.offset)
        blank = [p for p in gap if text_pages is not None and p not in text_pages][:skipped]
        rest = skipped - len(blank)
        unnumbered = set(blank) | set(gap[len(gap) - rest:] if rest else [])
        number = run.last + run.offset
        for page in gap:
            if page not in unnumbered:
                number += 1
                pages[page] = number

    for page in range(tail.last + 1, end):
        pages[page] = page + tail.offset
    return pages
