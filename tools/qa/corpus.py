"""The permanent regression corpus.

Three books, each kept for a different reason. None of them may be optimised
for individually — a change that helps one and hurts another is a trade to
argue about explicitly, not something to discover later.

The binaries themselves are NOT tracked in git (see test-corpus/README.md);
only this registry and the derived baselines are. If a book is missing from
test-corpus/ the harness reports it as unavailable and keeps going rather
than failing, so a partial corpus still gives partial evidence.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CORPUS_DIR = os.environ.get("MATBAA_CORPUS_DIR") or os.path.join(REPO_ROOT, "test-corpus")


@dataclass
class CorpusBook:
    key: str
    label: str
    role: str
    pdf_name: str
    reference_epub_name: Optional[str] = None

    @property
    def pdf_path(self) -> Optional[str]:
        p = os.path.join(CORPUS_DIR, self.pdf_name)
        return p if os.path.exists(p) else None

    @property
    def reference_epub_path(self) -> Optional[str]:
        if not self.reference_epub_name:
            return None
        p = os.path.join(CORPUS_DIR, self.reference_epub_name)
        return p if os.path.exists(p) else None


BOOKS = [
    CorpusBook(
        key="tenin",
        label="Tenin Gözleri — Juhani Pallasmaa",
        # Acrobat ClearScan OCR output: synthetic CID fonts, a blank full-page
        # raster underlay on every page, one text block per visual line, and
        # no style flags at all. Nothing in the pipeline was tuned on it.
        role="adversarial / generalisation specimen",
        pdf_name="Tenin Gozleri - Juhani Pallasmaa.pdf",
        reference_epub_name=None,
    ),
    CorpusBook(
        key="hessen",
        label="Boris Hessen — Newton'ın Principia'sının Toplumsal ve İktisadi Kökleri",
        # Academic translation: endnotes, a real İçindekiler page, tracked
        # small-caps headings. Several current heuristics were written
        # against this book, so it is the strongest regression signal there is.
        role="historical academic / endnote / TOC specimen",
        pdf_name="Newton’ın Principia’sının Toplumsal ve İktisadi Kökleri.pdf",
        reference_epub_name="NEWTON’IN PRINCIPIA’SININ TOPLUMSAL VE İKTİSADİ KÖKLERİ.epub",
    ),
    CorpusBook(
        key="dazai",
        label="Osamu Dazai — İnsanlığımı Yitirirken",
        # Novel: broken heading font encoding (garbled titles), narrative
        # prose with few structural cues, translator's notes inline.
        role="historical novel / broken-heading / text-recovery specimen",
        pdf_name="Osamu-Dazai-Insanligimi-Yitirirken-Ithaki-Japon-Klasikleri.pdf",
        reference_epub_name="İnsanlığımı Yitirirken.epub",
    ),
]

BY_KEY = {b.key: b for b in BOOKS}
