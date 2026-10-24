"""What the automatic index (backend/app/auto_index.py) makes of real books.

    python tools/measure_index.py            # the sample books (tools/qa/sample.txt)
    python tools/measure_index.py --all      # the whole library
    python tools/measure_index.py Stavros    # books whose file name holds this

Converts each book as the app does (the library run's OCR copies where it
made them), builds its index with the reader's vault concepts, and prints
how many entries it has, of which kind, and the first ones to read. For a
book with a printed index, it also says how many of the printed index's
capitalised entries the automatic one names (its recall on names).
"""
from __future__ import annotations

import glob
import html
import os
import re
import sys
from types import SimpleNamespace

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "backend"))

from app import auto_index, obsidian  # noqa: E402
from app.dictionary import Dictionary  # noqa: E402
from app.notebook import fold_ascii  # noqa: E402
from app.parsers.pdf_parser import convert_pdf_to_chapters, get_pdf_page_previews  # noqa: E402
from app.pipeline import chapters_out  # noqa: E402

from app.dictionary_build import library_folder  # noqa: E402

LIBRARY = library_folder()
OCR_CACHE = os.path.join(REPO_ROOT, ".matbaa-work", "library", "ocr")


def books(args):
    pdfs = sorted(glob.glob(os.path.join(LIBRARY, "**", "*.pdf"), recursive=True))
    if "--all" in args:
        return pdfs
    wanted = [a for a in args if not a.startswith("--")]
    if not wanted:
        sample = os.path.join(REPO_ROOT, "tools", "qa", "sample.txt")
        wanted = [ln.strip() for ln in open(sample, encoding="utf-8") if ln.strip() and not ln.startswith("#")]
    return [p for p in pdfs if any(w in os.path.basename(p) for w in wanted)]


def convert(pdf):
    name = os.path.splitext(os.path.basename(pdf))[0]
    copies = sorted(glob.glob(os.path.join(OCR_CACHE, glob.escape(name) + "-*.pdf")), key=os.path.getmtime)
    source = copies[-1] if copies else pdf
    previews = get_pdf_page_previews(source)
    modes = {m: {p.index for p in previews if p.suggested_mode == m} for m in ("image", "toc", "exclude")}
    result = convert_pdf_to_chapters(source, excluded_pages=modes["exclude"], image_pages=modes["image"],
                                     toc_pages=modes["toc"])
    return chapters_out(result)


def printed_terms(chapters):
    out = []
    for ch in chapters:
        for m in re.finditer(r'<p class="index-entry[^"]*">(.*?)</p>', ch.html or "", re.S):
            text = html.unescape(re.sub(r"<[^>]+>", "", m.group(1)))
            out.append(re.split(r",\s*\d|\s\d", text)[0].strip(" ,"))
    return out


def main() -> int:
    settings = obsidian.load_settings()
    vault = settings.get("vault")
    concepts = auto_index.concept_index(vault, settings) if vault and os.path.isdir(vault) else None
    lemma = Dictionary().lemmatizer().lemma if Dictionary.available() else None
    for pdf in books(sys.argv[1:]):
        chapters = convert(pdf)
        printed = printed_terms(chapters)
        body = [c for c in chapters if 'class="index-entry' not in (c.html or "")]
        session = SimpleNamespace(chapters=body)
        entries = auto_index.build(session, concepts, lemma)
        names = [e for e in entries if e.kind == "ad"]
        ideas = [e for e in entries if e.kind == "kavram"]
        paged = any(e.pages() for e in entries)
        print(f"\n== {os.path.basename(pdf)[:70]}")
        print(f"   {len(entries)} madde ({len(names)} ad, {len(ideas)} kavram), "
              f"{'basılı sayfalarla' if paged else 'paragraf bağlantılarıyla'}"
              f"{', basılı dizini var' if printed else ''}")
        top = sorted(entries, key=lambda e: -e.count)[:30]
        print("   en çok:", "; ".join(f"{e.term}{' ◦' if e.kind == 'kavram' else ''} ({e.count})" for e in top))
        if ideas:
            print("   kasandan:", "; ".join(e.term for e in ideas[:25]))
        if printed:
            capital = [t for t in printed if t[:1].isupper() and not t.lower().startswith("ayrıca")]
            keys = set()
            for e in names:
                words = e.term.split()
                keys |= {fold_ascii(e.term), fold_ascii(words[0]), fold_ascii(words[-1])}
            hit = [t for t in capital if fold_ascii(re.split(r"[\s,:'’(]", t)[0]) in keys or fold_ascii(t) in keys]
            print(f"   basılı dizinin büyük harfli {len(capital)} maddesinden {len(hit)} tanesi bulundu "
                  f"({len(hit) / max(1, len(capital)):.0%})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
