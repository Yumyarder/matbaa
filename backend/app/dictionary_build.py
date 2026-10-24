"""Making (or remaking) the Turkish dictionary from the Wiktionary extract
and the reader's books (app/dictionary.py holds what it is made of).

The Kindle finds a word only in a form the dictionary lists, so the forms
the reader's books print are added to their headwords. A new book brings
new forms; remaking the dictionary takes them in: the library's PDFs
(their text cached per file), and every book saved in Matbaa.
"""
from __future__ import annotations

import glob
import html
import json
import os
import re
import shutil
import time
from collections import Counter
from typing import Callable, Dict

from app import dictionary
from app.turkish_words import words

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
OCR_CACHE = os.path.join(REPO_ROOT, ".matbaa-work", "library", "ocr")
TAG = re.compile(r"<[^>]+>")


# where tools/run_library.py remembers the reader's library folder
LIBRARY_MEMO = os.path.join(REPO_ROOT, ".matbaa-work", "library_path.txt")


def library_folder() -> str:
    """The reader's folder of PDF books: MATBAA_LIBRARY, else the folder the
    library run remembered, else ~/Kitaplar."""
    if os.environ.get("MATBAA_LIBRARY"):
        return os.environ["MATBAA_LIBRARY"]
    try:
        with open(LIBRARY_MEMO, encoding="utf-8") as fh:
            remembered = fh.read().strip()
        if remembered:
            return remembered
    except OSError:
        pass
    return os.path.join(os.path.expanduser("~"), "Kitaplar")


def projects_folder() -> str:
    return os.environ.get("MATBAA_PROJECTS") or os.path.join(os.path.expanduser("~"), "Matbaa", "projects")


def _pdf_words(path: str) -> Counter:
    import fitz

    name = os.path.splitext(os.path.basename(path))[0]
    copies = sorted(glob.glob(os.path.join(OCR_CACHE, glob.escape(name) + "-*.pdf")), key=os.path.getmtime)
    source = copies[-1] if copies else path
    counts: Counter = Counter()
    try:
        with fitz.open(source) as doc:
            for page in doc:
                counts.update(words(page.get_text()))
    except Exception:  # noqa: BLE001 - an unreadable PDF adds no forms
        pass
    return counts


def book_words() -> Counter:
    """Every word form of the reader's books, with how often it is printed:
    the library's PDFs (cached per path, size and date) and the books saved
    in Matbaa."""
    cache_path = os.path.join(dictionary.DATA_DIR, "book-words.json")
    try:
        with open(cache_path, encoding="utf-8") as f:
            cache = json.load(f)
    except (OSError, ValueError):
        cache = {}
    total: Counter = Counter()
    fresh = {}
    for pdf in sorted(glob.glob(os.path.join(library_folder(), "**", "*.pdf"), recursive=True)):
        st = os.stat(pdf)
        key = f"{pdf}|{st.st_size}|{int(st.st_mtime)}"
        counts = cache.get(key)
        if counts is None:
            counts = dict(_pdf_words(pdf))
        fresh[key] = counts
        total.update(counts)
    for p in glob.glob(os.path.join(projects_folder(), "*.json")):
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        for ch in data.get("chapters") or []:
            total.update(words(html.unescape(TAG.sub(" ", ch.get("html") or ""))))
    os.makedirs(dictionary.DATA_DIR, exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(fresh, f, ensure_ascii=False)
    return total


def books_since_built() -> int:
    """Books saved in Matbaa after the dictionary was last made: what a
    remake would bring in."""
    made = os.path.join(dictionary.DATA_DIR, dictionary.DEVICE_NAME)
    if not os.path.isfile(made):
        return 0
    since = os.path.getmtime(made)
    return sum(1 for p in glob.glob(os.path.join(projects_folder(), "*.json")) if os.path.getmtime(p) > since)


def rebuild(progress: Callable[[str], None] = lambda step: None) -> Dict:
    """The dictionary made again: tr.db for Matbaa and the Kindle's .mobi,
    each replaced only once the new one is complete."""
    source = os.path.join(dictionary.DATA_DIR, dictionary.SOURCE_FILE)
    if not os.path.isfile(source):
        raise FileNotFoundError(f"Vikisözlük verisi yok ({source}); kaynak: {dictionary.SOURCE_URL}")
    t0 = time.time()
    progress("Vikisözlük okunuyor")
    heads = dictionary.load_source(source)
    progress("Kitapların kelimeleri toplanıyor")
    counts = book_words()
    added = dictionary.add_book_forms(heads, counts)
    progress("Matbaa'nın kelime listesi yazılıyor")
    dictionary.save_db(heads, os.path.join(dictionary.DATA_DIR, dictionary.DB_FILE))
    progress("Kindle sözlüğü yazılıyor")
    build = os.path.join(dictionary.DATA_DIR, "build")
    shutil.rmtree(build, ignore_errors=True)
    dump = time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(source)))
    opf = dictionary.write_source(heads, build, dump=dump)
    progress("kindlegen derliyor (birkaç dakika sürer)")
    mobi, report = dictionary.compile_mobi(opf)
    if not mobi:
        tail = " ".join(line for line in report.splitlines() if line.strip())[-300:]
        raise RuntimeError(f"kindlegen sözlüğü yapamadı: {tail}")
    final = os.path.join(dictionary.DATA_DIR, dictionary.DEVICE_NAME)
    shutil.copyfile(mobi, final + ".part")
    os.replace(final + ".part", final)
    return {"headwords": len(heads), "book_forms": added, "size": os.path.getsize(final),
            "seconds": round(time.time() - t0)}
