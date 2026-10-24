"""Headless driver for the real conversion pipeline.

Calls exactly what POST /api/convert and POST /api/session/{id}/export call —
convert_pdf_to_chapters() then build_epub() — with no server, no browser and
no session store, and with the same per-page modes the Page Review screen
pre-selects from _suggest_page_mode(). So this reproduces what a person gets
if they accept every default and click through.

Page modes can be forced via MATBAA_FORCE_MODES for experiments:
    MATBAA_FORCE_MODES="text"
    MATBAA_FORCE_MODES="image=22,28;toc=4,5;exclude=0,9"
The corpus always runs on defaults — forcing modes measures a different
thing (the pipeline given a perfect operator) and must not be confused with
the baseline.
"""

from __future__ import annotations

import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if os.path.join(REPO_ROOT, "backend") not in sys.path:
    sys.path.insert(0, os.path.join(REPO_ROOT, "backend"))

from app.builders.css_template import book_css            # noqa: E402
from app.builders.epub_builder import build_epub            # noqa: E402
from app.models import ChapterImage, ChapterOut, Footnote   # noqa: E402
from app.parsers.pdf_parser import (                        # noqa: E402
    convert_pdf_to_chapters,
    get_pdf_page_previews,
)


@dataclass
class PageModes:
    excluded: Set[int] = field(default_factory=set)
    image: Set[int] = field(default_factory=set)
    toc: Set[int] = field(default_factory=set)
    cover_index: int = 0

    def as_dict(self) -> dict:
        return {
            "excluded": sorted(self.excluded),
            "image": sorted(self.image),
            "toc": sorted(self.toc),
            "cover_index": self.cover_index,
        }

    def skipped_pages(self) -> Set[int]:
        """Pages whose text is legitimately not expected in the EPUB.

        Only genuinely excluded pages count. Pages rendered as images are
        deliberately NOT exempt: turning a page of prose into a picture
        loses its text for search, reflow, text-to-speech and every other
        thing an e-reader does with words. That is content loss, and the
        harness has to be able to see it — it is the exact failure the
        blank-raster-underlay misclassification produces.
        """
        return set(self.excluded)


def _parse_forced(spec: str) -> Optional[PageModes]:
    spec = (spec or "").strip()
    if not spec:
        return None
    modes = PageModes()
    buckets = {"image": modes.image, "toc": modes.toc, "exclude": modes.excluded}
    for part in spec.split(";"):
        if "=" not in part:
            continue
        key, val = part.split("=", 1)
        bucket = buckets.get(key.strip())
        if bucket is None:
            continue
        bucket.update(int(n) for n in re.findall(r"\d+", val))
    return modes


def choose_page_modes(previews) -> PageModes:
    forced = _parse_forced(os.environ.get("MATBAA_FORCE_MODES", ""))
    if forced is not None:
        included = [p.index for p in previews if p.index not in forced.excluded]
        forced.cover_index = min(forced.image) if forced.image else (included[0] if included else 0)
        return forced

    modes = PageModes()
    for p in previews:
        mode = getattr(p, "suggested_mode", None) or "text"
        if mode == "exclude":
            modes.excluded.add(p.index)
        elif mode == "image":
            modes.image.add(p.index)
        elif mode == "toc":
            modes.toc.add(p.index)

    first_image = next((p.index for p in previews
                        if (getattr(p, "suggested_mode", None) or "text") == "image"), None)
    first_included = next((p.index for p in previews
                           if (getattr(p, "suggested_mode", None) or "text") != "exclude"), 0)
    modes.cover_index = first_image if first_image is not None else first_included
    return modes


@dataclass
class RunResult:
    pdf_path: str
    epub_path: str
    page_count: int
    modes: PageModes
    result: object                 # ConversionResult
    chapters: List[ChapterOut]
    timings: Dict[str, float]


def convert_book(pdf_path: str, out_dir: str, slug: str) -> RunResult:
    os.makedirs(out_dir, exist_ok=True)

    t0 = time.time()
    previews = get_pdf_page_previews(pdf_path)
    t_preview = time.time() - t0

    modes = choose_page_modes(previews)

    t1 = time.time()
    result = convert_pdf_to_chapters(
        pdf_path,
        excluded_pages=modes.excluded,
        cover_page_index=modes.cover_index,
        image_pages=modes.image,
        toc_pages=modes.toc,
        header_ratio=None,
        footer_ratio=None,
        excluded_text_regions=None,
    )
    t_convert = time.time() - t1

    chapters = [
        ChapterOut(
            id=ch.id, index=ch.index, title=ch.title, kind=ch.kind,
            eyebrow=ch.eyebrow, html="".join(ch.paragraphs),
            footnotes=[Footnote(id=f.id, marker=f.marker, text=f.text) for f in ch.footnotes],
            is_split_continuation=ch.is_split_continuation,
            image_base64=ch.image_base64,
            # Mirrors main.py's ChapterOut construction. Leaving this out
            # made the harness blind to every in-flow figure — the <img>
            # tags were measured in the HTML while the files they point at
            # were never packaged, so epub_image_count only ever counted
            # whole-page image chapters and no figure regression could fail
            # a run.
            images=[ChapterImage(**img) for img in ch.images],
            byline=ch.byline,
            toc_path=list(ch.toc_path),
            opener=ch.opener,
        )
        for ch in result.chapters
    ]

    epub_path = os.path.join(out_dir, slug + ".epub")
    t2 = time.time()
    build_epub(
        book_title=result.detected_title,
        author=result.detected_author,
        chapters=chapters,
        css=book_css(result.paragraph_style),
        output_path=epub_path,
        cover_image_base64=result.cover_image_base64,
        language=result.detected_language,
    )
    t_build = time.time() - t2

    return RunResult(
        pdf_path=pdf_path,
        epub_path=epub_path,
        page_count=len(previews),
        modes=modes,
        result=result,
        chapters=chapters,
        timings={"preview": round(t_preview, 2),
                 "convert": round(t_convert, 2),
                 "build": round(t_build, 2)},
    )
