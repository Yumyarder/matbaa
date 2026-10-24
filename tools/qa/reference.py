"""Compare a fresh conversion against a historical, hand-corrected EPUB.

These reference files are NOT goldens. After Matbaa produced them a person
went through and fixed things by hand — apostrophes, punctuation, and an
unknown number of other small text-level defects. So a difference here is
evidence to read, never a verdict.

Concretely, that means:
  * structural counts (chapters, footnotes, roughly how much text) are
    meaningful — a person fixing apostrophes does not delete a chapter;
  * a shortfall in *our* text against the reference is worth investigating;
  * a punctuation or spacing difference is expected and is not reported.

Everything below is informational. Nothing here can fail a run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from . import textnorm
from .epubinspect import inspect_epub


@dataclass
class ReferenceComparison:
    available: bool = False
    ref_xhtml: int = 0
    ref_words: int = 0
    ref_nav_entries: int = 0
    ref_footnote_asides: int = 0
    cur_words: int = 0
    word_ratio: float = 0.0
    missing_from_current: int = 0
    missing_examples: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_json(self) -> dict:
        d = dict(self.__dict__)
        d["missing_examples"] = self.missing_examples[:15]
        return d


SAMPLE_WINDOW = 6
SAMPLE_STRIDE = 40


def compare_against_reference(reference_epub: str, current_epub: str) -> ReferenceComparison:
    cmp = ReferenceComparison(available=True)

    ref = inspect_epub(reference_epub)
    cur = inspect_epub(current_epub)

    cmp.ref_xhtml = ref.xhtml_count
    cmp.ref_nav_entries = ref.nav_toc_entries
    cmp.ref_footnote_asides = ref.footnote_asides

    ref_words = textnorm.normalize(ref.plain_text).split()
    cur_norm = textnorm.normalize(cur.plain_text)
    cmp.ref_words = len(ref_words)
    cmp.cur_words = len(cur_norm.split())
    cmp.word_ratio = round(cmp.cur_words / cmp.ref_words, 4) if cmp.ref_words else 0.0

    # Walk the reference's own text in six-word windows and ask how much of
    # it survives into today's conversion. This is the one direction that
    # matters: text the old pipeline delivered and the new one does not.
    missing: List[str] = []
    for start in range(0, max(0, len(ref_words) - SAMPLE_WINDOW), SAMPLE_STRIDE):
        window = " ".join(ref_words[start:start + SAMPLE_WINDOW])
        if window not in cur_norm:
            missing.append(window)
    cmp.missing_from_current = len(missing)
    cmp.missing_examples = missing

    if cmp.word_ratio < 0.95:
        cmp.notes.append(
            f"current conversion has {cmp.word_ratio:.1%} of the reference's words — investigate"
        )
    if ref.footnote_asides and cur.footnote_asides < ref.footnote_asides * 0.9:
        cmp.notes.append(
            f"footnotes {cur.footnote_asides} vs reference {ref.footnote_asides}"
        )
    return cmp
