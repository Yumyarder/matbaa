"""Make the Matbaa Turkish dictionary for the Kindle (backend/app/dictionary.py,
dictionary_build.py).

    python tools/make_dictionary.py            # the whole dictionary
    python tools/make_dictionary.py --test     # 50 words, to try on the Kindle first
    python tools/make_dictionary.py --measure  # only how much of the books finds a headword

Reads the Turkish Wiktionary extraction (~/.matbaa/sozluk/
raw-wiktextract-data.jsonl.gz, from kaikki.org/trwiktionary), adds the word
forms of the reader's books (the PDFs in MATBAA_LIBRARY, else the folder
the library run remembered, through the library run's OCR copies where it
made them, and the books saved in Matbaa), writes tr.db for Matbaa itself
and compiles the Kindle dictionary with kindlegen. The app remakes it the
same way from the "Kindle'ım" card.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from collections import Counter

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "backend"))

from app import dictionary, dictionary_build  # noqa: E402


def measure(heads, counts: Counter) -> None:
    lem = dictionary.lemmatizer(heads)
    found = Counter()
    for w, n in counts.items():
        if w in heads:
            found["kelimenin kendisi madde başı"] += n
        elif w in lem.forms:
            found["Vikisözlük çekimi"] += n
        elif lem.lemma(w):
            found["ek soyarak"] += n
        else:
            found["bulunamadı"] += n
    total = sum(found.values()) or 1
    print(f"\nKitapların metni: {total} kelime, {len(counts)} farklı biçim")
    for k in ("kelimenin kendisi madde başı", "Vikisözlük çekimi", "ek soyarak", "bulunamadı"):
        print(f"  {k:32} {found[k] / total:6.1%}")
    missing = Counter({w: n for w, n in counts.items() if w not in heads and not lem.lemma(w)})
    print("  en sık bulunamayanlar:", ", ".join(f"{w} ({n})" for w, n in missing.most_common(40)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true", help="50 words of the books, to try on the Kindle")
    ap.add_argument("--measure", action="store_true", help="only measure, make nothing")
    args = ap.parse_args()
    source = os.path.join(dictionary.DATA_DIR, dictionary.SOURCE_FILE)
    if not os.path.isfile(source):
        print(f"Kaynak yok: {source}\nİndirin: {dictionary.SOURCE_URL}")
        return 1
    if not (args.test or args.measure):
        result = dictionary_build.rebuild(lambda step: print(f"… {step}"))
        print(f"\n{result['headwords']} madde başı, kitaplardan {result['book_forms']} biçim, "
              f"{result['size'] / 1e6:.1f} MB ({result['seconds']} sn)")
        return 0
    heads = dictionary.load_source(source)
    counts = dictionary_build.book_words()
    measure(heads, counts)
    if args.measure:
        return 0
    dictionary.add_book_forms(heads, counts)
    lem = dictionary.lemmatizer(heads)
    by_head = Counter()
    for w, n in counts.items():
        h = w if w in heads else lem.lemma(w)
        if h and len(h) >= 5:
            by_head[h] += n
    chosen = {h for h, _ in by_head.most_common(49)} | {"müşterek"}
    heads = {w: h for w, h in heads.items() if w in chosen}
    print("Deneme sözlüğü:", ", ".join(sorted(heads)))
    build = os.path.join(dictionary.DATA_DIR, "build-test")
    shutil.rmtree(build, ignore_errors=True)
    dump = time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(source)))
    opf = dictionary.write_source(heads, build, dump=dump)
    name = "Matbaa-Turkce-Sozluk-deneme.mobi"
    mobi, report = dictionary.compile_mobi(opf, name)
    if not mobi:
        print(report[-2000:])
        return 1
    final = os.path.join(dictionary.DATA_DIR, name)
    shutil.copyfile(mobi, final)
    print(f"{final}: {os.path.getsize(final) / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
