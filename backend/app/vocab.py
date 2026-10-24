"""Words looked up on the Kindle, for the Kelime Defteri.

A Kindle keeps every word the reader looks up in a dictionary in
system/vocabulary/vocab.db (its Vocabulary Builder, SQLite): the word as
the book prints it, its stem, the sentence it stood in, the book, when it
was looked up, and whether the reader marked it learnt. The tables, as a
2024–2026 Kindle has them:

    WORDS     (id "tr:kelime", word, stem, lang, category 0|100, timestamp, profileid)
    LOOKUPS   (id, word_key -> WORDS.id, book_key -> BOOK_INFO.id, dict_key, pos, usage, timestamp)
    BOOK_INFO (id, asin, guid, lang, title, authors)

The file is copied off the device and opened read-only. What was imported is
kept in the notebook folder (lookups.json) like the clippings: the reader may
clear the Kindle's list, the notebook keeps the words.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Dict, List

from app import kindle_usb
from app.notebook import notebook_dir

DEVICE_PATH = "system/vocabulary/vocab.db"


@dataclass
class Lookup:
    id: str              # "w-" + a short hash of the Kindle's own id
    word: str            # as the book prints it
    stem: str            # the Kindle's stem (for Turkish: often the word itself)
    lang: str
    usage: str           # the sentence it stood in
    book: str            # the Kindle's title of the book
    authors: str
    added: str           # ISO date and time
    learnt: bool


def _id(kindle_id: str) -> str:
    return "w-" + hashlib.sha1(kindle_id.encode("utf-8")).hexdigest()[:10]


def _nfc(text) -> str:
    return unicodedata.normalize("NFC", text or "")


def read_db(path: str) -> List[Lookup]:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT l.id, w.word, w.stem, w.lang, l.usage, b.title, b.authors, l.timestamp, w.category "
            "FROM LOOKUPS l JOIN WORDS w ON w.id = l.word_key LEFT JOIN BOOK_INFO b ON b.id = l.book_key "
            "ORDER BY l.timestamp").fetchall()
    finally:
        con.close()
    out = []
    for kid, word, stem, lang, usage, title, authors, ts, category in rows:
        try:
            added = datetime.fromtimestamp((ts or 0) / 1000).isoformat(timespec="seconds")
        except (OverflowError, OSError, ValueError):
            added = ""
        out.append(Lookup(_id(kid), _nfc(word), _nfc(stem or word), (lang or "").strip(),
                          " ".join(_nfc(usage).split()), _nfc(title), _nfc(authors), added, (category or 0) >= 100))
    return out


def from_kindle() -> List[Lookup]:
    """The plugged-in Kindle's looked-up words (kindle_usb errors pass
    through: KindleNotFound, FileNotFoundError for a Kindle that never
    looked a word up)."""
    return read_db(kindle_usb.fetch_file(DEVICE_PATH))


# --- kept between sessions -------------------------------------------------------

def _file() -> str:
    return os.path.join(notebook_dir(), "lookups.json")


def load() -> List[Lookup]:
    try:
        with open(_file(), encoding="utf-8") as f:
            return [Lookup(**d) for d in json.load(f)]
    except (OSError, ValueError, TypeError):
        return []


def import_lookups(new: List[Lookup]) -> int:
    """Add looked-up words to what is kept, each once (the Kindle's id);
    a word marked learnt on the Kindle since is updated. Returns how many
    were new."""
    kept = {lk.id: lk for lk in load()}
    added = 0
    for lk in new:
        if lk.id not in kept:
            added += 1
        kept[lk.id] = lk
    os.makedirs(notebook_dir(), exist_ok=True)
    tmp = _file() + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump([asdict(lk) for lk in sorted(kept.values(), key=lambda x: x.added)], f, ensure_ascii=False)
    os.replace(tmp, _file())
    return added


def by_book(lookups: List[Lookup]) -> Dict[str, List[Lookup]]:
    books: Dict[str, List[Lookup]] = {}
    for lk in lookups:
        books.setdefault(lk.book or "", []).append(lk)
    return books
