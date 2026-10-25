"""Turns one conversion run into a comparable signature.

The most important number here is `probe_missing`. Everything else describes
shape; that one describes loss.

How the probes work
-------------------
Every line of the PDF's own text layer that is long enough to be body prose
(>= 8 normalised words — which excludes running heads, folios, and short
labels) becomes a candidate. From each candidate we take a six-word window
starting at the third word, and check whether that exact window survives
into the built EPUB.

Taking the window from the *middle* of the line rather than the whole line
is what makes this robust: a line's first and last words are precisely where
hyphen-joining, footnote-marker insertion and paragraph-boundary decisions
legitimately change the text. The middle of a line is content the converter
has no business altering. If a mid-line six-gram from the PDF is absent from
the EPUB, some text was lost — no interpretation required.

Pages the operator's page-modes told the pipeline to skip (blank/junk pages,
pages rendered as images) are excluded from the probe pool. Their text was
not lost; it was deliberately not read.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pymupdf as fitz

from . import textnorm
from .epubinspect import EpubInfo, inspect_epub

PROBE_MIN_WORDS = 8
PROBE_WINDOW = 6
PROBE_WINDOW_START = 2
PROBE_TARGET_COUNT = 400

_TAG_RE = re.compile(r"<[^>]+>")
HYPHEN_TAIL_RE = re.compile(r"(?<=[^\W\d_])[-­]$")


@dataclass
class Probe:
    page: int
    key: str
    source: str


def collect_probes(pdf_path: str, skip_pages: set) -> List[Probe]:
    doc = fitz.open(pdf_path)
    candidates: List[Probe] = []
    try:
        for i in range(doc.page_count):
            if i in skip_pages:
                continue
            for line in doc[i].get_text("text").split("\n"):
                w = textnorm.words(line)
                if len(w) < PROBE_MIN_WORDS:
                    continue
                key = " ".join(w[PROBE_WINDOW_START:PROBE_WINDOW_START + PROBE_WINDOW])
                if len(key.split()) < PROBE_WINDOW:
                    continue
                candidates.append(Probe(page=i, key=key, source=line.strip()[:110]))
    finally:
        doc.close()

    if len(candidates) <= PROBE_TARGET_COUNT:
        return candidates
    step = len(candidates) / PROBE_TARGET_COUNT
    return [candidates[int(n * step)] for n in range(PROBE_TARGET_COUNT)]


def _plain(html: str) -> str:
    return _TAG_RE.sub(" ", html or "")


@dataclass
class Signature:
    book: str
    available: bool = True
    note: str = ""
    page_count: int = 0
    page_modes: dict = field(default_factory=dict)

    # --- content survival -------------------------------------------------
    probe_total: int = 0
    probe_missing: int = 0
    probe_missing_examples: List[dict] = field(default_factory=list)
    pdf_words: int = 0
    epub_words: int = 0
    epub_letters: int = 0
    word_recovery: float = 0.0

    # --- structure --------------------------------------------------------
    chapters_total: int = 0
    chapters_real: int = 0
    chapters_image: int = 0
    chapters_split: int = 0
    chapter_titles: List[str] = field(default_factory=list)
    toc_entries_detected: int = 0
    footnotes_total: int = 0
    chapters_under_200_chars: int = 0

    # --- paragraph quality ------------------------------------------------
    paragraphs_total: int = 0
    paragraph_median_chars: int = 0
    paragraphs_lowercase_start: int = 0
    paragraphs_dangling_hyphen: int = 0

    # --- pipeline diagnostics (populated when the parser reports them) -----
    diagnostics: dict = field(default_factory=dict)

    # --- built artifact ---------------------------------------------------
    epub_bytes: int = 0
    epub_ok: bool = True
    epub_language: Optional[str] = None
    epub_spine_count: int = 0
    epub_xhtml_count: int = 0
    epub_image_count: int = 0
    epub_has_cover: bool = False
    epub_cover_in_spine: bool = False
    epub_nav_toc_entries: int = 0
    epub_nav_pagelist_entries: int = 0
    epub_ncx_navpoints: int = 0
    epub_xhtml_parse_errors: int = 0
    epub_footnote_asides: int = 0
    epub_noteref_links: int = 0
    epub_dangling_noterefs: int = 0
    epub_duplicate_ids: int = 0
    epub_validation_errors: int = 0       # app.validate: what EPUBCheck / a Kindle would reject
    epub_errors: List[str] = field(default_factory=list)

    warnings_count: int = 0
    warnings_critical_count: int = 0
    warnings: List[dict] = field(default_factory=list)  # {"message", "severity"}

    def to_json(self) -> dict:
        d = dict(self.__dict__)
        d["probe_missing_examples"] = self.probe_missing_examples[:25]
        d["warnings"] = self.warnings[:40]
        d["epub_errors"] = self.epub_errors[:25]
        return d


def measure(book_key: str, run, probes: List[Probe]) -> Signature:
    import os

    sig = Signature(book=book_key)
    sig.page_count = run.page_count
    sig.page_modes = run.modes.as_dict()

    result = run.result
    chapters = run.chapters

    sig.warnings = list(result.warnings)
    sig.warnings_count = len(result.warnings)
    sig.warnings_critical_count = sum(1 for w in result.warnings if w.get("severity") == "critical")
    sig.diagnostics = dict(getattr(result, "diagnostics", {}) or {})

    sig.chapters_total = len(chapters)
    sig.chapters_image = sum(1 for c in chapters if c.kind == "image")
    sig.chapters_split = sum(1 for c in chapters if c.is_split_continuation)
    real = [c for c in chapters if c.kind == "chapter" and not c.is_split_continuation]
    sig.chapters_real = len(real)
    sig.chapter_titles = [c.title for c in chapters]
    sig.footnotes_total = sum(len(c.footnotes) for c in chapters)
    sig.toc_entries_detected = sum(
        c.html.count('class="toc-entry"') for c in chapters if c.kind == "toc"
    )
    sig.chapters_under_200_chars = sum(1 for c in real if len(_plain(c.html).strip()) < 200)

    para_lens: List[int] = []
    for c in chapters:
        for attrs, p in re.findall(r"<p\b([^>]*)>(.*?)</p>", c.html or "", re.S):
            plain = _plain(p).strip()
            if not plain:
                continue
            para_lens.append(len(plain))
            if HYPHEN_TAIL_RE.search(plain):
                sig.paragraphs_dangling_hyphen += 1
            # An index runs "elektrik 47, 100" and a caption runs "detay,
            # Neues Palais" because that is how they are printed, not because
            # a sentence failed to join — the converter's own publish-readiness
            # check (pdf_parser.py, PAGE_ASIDE_CLASS) already knows this and
            # skips these paragraphs for the same reason. A guard that doesn't
            # match fires on every index/caption page a book has.
            if "page-aside" in attrs or "index-entry" in attrs:
                continue
            if plain[0].islower():
                sig.paragraphs_lowercase_start += 1
    sig.paragraphs_total = len(para_lens)
    if para_lens:
        para_lens.sort()
        sig.paragraph_median_chars = para_lens[len(para_lens) // 2]

    info: EpubInfo = inspect_epub(run.epub_path)
    sig.epub_bytes = os.path.getsize(run.epub_path)
    sig.epub_ok = info.ok
    sig.epub_language = info.language
    sig.epub_spine_count = info.spine_count
    sig.epub_xhtml_count = info.xhtml_count
    sig.epub_image_count = info.image_count
    sig.epub_has_cover = info.has_cover_image
    sig.epub_cover_in_spine = info.cover_in_spine
    sig.epub_nav_toc_entries = info.nav_toc_entries
    sig.epub_nav_pagelist_entries = info.nav_pagelist_entries
    sig.epub_ncx_navpoints = info.ncx_navpoints
    sig.epub_xhtml_parse_errors = info.xhtml_parse_errors
    sig.epub_footnote_asides = info.footnote_asides
    sig.epub_noteref_links = info.noteref_links
    sig.epub_dangling_noterefs = info.dangling_noterefs
    sig.epub_duplicate_ids = info.duplicate_ids
    from app.validate import check_epub
    sig.epub_validation_errors = sum(1 for f in check_epub(run.epub_path) if f.severity == "error")
    sig.epub_errors = list(info.errors)

    haystack = textnorm.normalize(info.plain_text)
    sig.epub_words = len(haystack.split())
    # Letters, not words, is the honest content-loss signal. Correctly
    # rejoining a word broken across a line ("kuram" + "cılarından") is an
    # improvement that *lowers* the word count, so a word-count guard reads
    # a fix as a regression. Letter count is unmoved by the join and still
    # drops the moment text actually goes missing.
    sig.epub_letters = sum(1 for c in haystack if c.isalnum())

    # A probe is read off the PDF's own text layer, which on OCR'd books
    # carries spaces PyMuPDF invented inside words ("maddesel lik"). Once the
    # converter stops reproducing those, the probe no longer matches word
    # for word although not a letter was lost — so a probe also counts as
    # present when it matches with all spaces removed.
    squashed = haystack.replace(" ", "")
    missing: List[dict] = []
    for probe in probes:
        if probe.key not in haystack and probe.key.replace(" ", "") not in squashed:
            missing.append({"page": probe.page, "key": probe.key, "source": probe.source})
    sig.probe_total = len(probes)
    sig.probe_missing = len(missing)
    sig.probe_missing_examples = missing

    doc = fitz.open(run.pdf_path)
    try:
        skip = run.modes.skipped_pages()
        total = 0
        for i in range(doc.page_count):
            if i in skip:
                continue
            total += len(textnorm.words(doc[i].get_text("text")))
        sig.pdf_words = total
    finally:
        doc.close()
    sig.word_recovery = round(sig.epub_words / sig.pdf_words, 4) if sig.pdf_words else 0.0

    return sig
