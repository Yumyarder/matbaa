"""How often the genre guess (backend/app/genre.py) names a fair genre.

    python tools/measure_genre.py              # every labelled book
    python tools/measure_genre.py Kivilcimli   # labelled books whose path holds this

Reads .matbaa-work/genre-labels.tsv (private: the reader's own books), one
line per book: its path under the library folder (or test-corpus/...) and
the genres it may fairly be called. Each book is read straight from its PDF
(the library run's OCR copy where it made one): its first and last pages,
and its text blocks standing for paragraphs, which is close to what the
conversion hands the guess and much faster. Prints every guess and the
share that lands in a fair genre.
"""
from __future__ import annotations

import glob
import html
import os
import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "backend"))

import pymupdf as fitz  # noqa: E402

from app import book_names, genre, imprint  # noqa: E402
from app.dictionary_build import library_folder  # noqa: E402

LABELS = os.path.join(REPO_ROOT, ".matbaa-work", "genre-labels.tsv")
OCR_CACHE = os.path.join(REPO_ROOT, ".matbaa-work", "library", "ocr")
BODY_PAGES = 160


def labelled():
    with open(LABELS, encoding="utf-8") as fh:
        for line in fh:
            if line.strip() and not line.startswith("#"):
                path, fair = line.rstrip("\n").split("\t")
                yield path, set(fair.split(","))


def resolve(path: str) -> str:
    if path.startswith("test-corpus/"):
        return os.path.join(REPO_ROOT, path)
    return os.path.join(library_folder(), path)


def readable(pdf: str) -> str:
    stem = os.path.splitext(os.path.basename(pdf))[0]
    copies = sorted(glob.glob(os.path.join(OCR_CACHE, glob.escape(stem) + "-*.pdf")), key=os.path.getmtime)
    return copies[-1] if copies else pdf


def read(pdf: str):
    source = readable(pdf)
    with fitz.open(source) as doc:
        paragraphs = []
        for number in range(min(4, doc.page_count - 1), min(doc.page_count, 4 + BODY_PAGES)):
            for block in doc[number].get_text("blocks"):
                text = " ".join(block[4].split())
                if text:
                    paragraphs.append("<p>" + html.escape(text) + "</p>")
        sample = " ".join(paragraphs[:300]).lower()
        language = "en" if sample.count(" the ") + sample.count(" and ") > sample.count(" ve ") + 20 else "tr"
    body = "".join(paragraphs)
    return body, language, genre.front_pages_text(source), imprint.read_pdf(source).to_dict()


def main(argv) -> int:
    only = argv[0].lower() if argv else ""
    rows, right = 0, 0
    for path, fair in labelled():
        if only and only not in path.lower():
            continue
        pdf = resolve(path)
        if not os.path.exists(pdf):
            print(f"  yok   {path}")
            continue
        body, language, front, imp = read(pdf)
        if len(body) < 2000:
            # a scan with no OCR copy yet: the app reads it first, this tool cannot
            print(f"  metin yok  {path}")
            continue
        title, author = book_names.from_filename(os.path.basename(pdf), language)
        g = genre.guess(title or "", author or "", [("", body, "chapter")], imp, language, front)
        ok = g.key in fair
        rows += 1
        right += ok
        mark = "  ✓ " if ok else "  ✗ "
        print(f"{mark} {g.label:16} {g.confidence:.2f}  {os.path.basename(path)[:60]:60}  "
              f"({'/'.join(sorted(fair))}; {g.reason})")
    if rows:
        print(f"\n{right}/{rows} kitap adil bir türde: %{round(100 * right / rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
