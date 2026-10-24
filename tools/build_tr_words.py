"""Build the word list Okuma Defteri restores Turkish letters from.

    python tools/build_tr_words.py [library folder]

Reads the text layer of the Turkish books in the library (default: the
MATBAA_LIBRARY folder, else the one tools/run_library.py remembered) and
writes, for every word spelled with Turkish letters, how often each spelling
occurs and how often its letter-less form occurs as it is:
backend/app/data/tr_words.tsv. Only single words and their counts are
kept — no text of any book.

A Kindle-typed note says "Cok hos, isci sinifi"; the books say "çok hoş",
"işçi sınıfı". That is all the restorer needs to know.
"""
from __future__ import annotations

import glob
import os
import sys
from collections import Counter, defaultdict

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "backend"))

import fitz  # noqa: E402

from app.deasciify import asciify, tr_lower, words  # noqa: E402
from app.dictionary_build import library_folder as _library_folder  # noqa: E402

OUT = os.path.join(REPO_ROOT, "backend", "app", "data", "tr_words.tsv")
TURKISH_LETTERS = set("çğıöşüÇĞİÖŞÜ")
MIN_COUNT = 2


def library_folder() -> str:
    if len(sys.argv) > 1:
        return sys.argv[1]
    return _library_folder()


def book_words(pdf: str) -> Counter:
    counts: Counter = Counter()
    try:
        with fitz.open(pdf) as doc:
            for page in doc:
                counts.update(tr_lower(w) for w in words(page.get_text()))
    except Exception:  # noqa: BLE001
        pass
    return counts


def is_turkish(counts: Counter) -> bool:
    total = sum(counts.values())
    if total < 2000:
        return False
    with_tr = sum(n for w, n in counts.items() if TURKISH_LETTERS & set(w))
    return with_tr / total > 0.15


def main() -> None:
    forms: dict = defaultdict(Counter)       # ascii form -> Counter(spelling)
    plain: Counter = Counter()                # ascii form occurring as it is
    used = 0
    for pdf in sorted(glob.glob(os.path.join(library_folder(), "**", "*.pdf"), recursive=True)):
        counts = book_words(pdf)
        if not is_turkish(counts):
            continue
        used += 1
        for w, n in counts.items():
            a = asciify(w)
            if a == w:
                plain[a] += n
            else:
                forms[a][w] += n
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    rows = 0
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write("# ascii\tspelling:count,...\tcount as written without Turkish letters\n")
        for a in sorted(forms):
            spelled = {w: n for w, n in forms[a].items() if n >= MIN_COUNT}
            if not spelled:
                continue
            f.write(a + "\t" + ",".join(f"{w}:{n}" for w, n in sorted(spelled.items(), key=lambda t: -t[1]))
                    + f"\t{plain.get(a, 0)}\n")
            rows += 1
    print(f"{used} Turkish books, {rows} words -> {OUT}")


if __name__ == "__main__":
    main()
