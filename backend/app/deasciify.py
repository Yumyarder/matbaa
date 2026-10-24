"""Turkish letters for a note typed without them.

A note typed on a Kindle keyboard comes out as "Cok hos, isci sinifi
kendi icin bir sinif mi": readable, but Obsidian's search for "işçi" or
"sınıf" will never find it. The words are restored from how the reader's
own books spell them (backend/app/data/tr_words.tsv, built by
tools/build_tr_words.py from the library's text): a letter-less word is
given Turkish letters only when one spelling clearly dominates — "cok" is
"çok" — and left alone when the books are split ("aci": acı or açı?) or
when the word is common as it is.

This only ever proposes. The reader's voice is theirs: the screen shows
the suggestion and applies it on their click.
"""
from __future__ import annotations

import os
import re
from collections import Counter
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

DATA = os.path.join(os.path.dirname(__file__), "data", "tr_words.tsv")
_ASCII = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
MIN_SHARE = 0.8      # the winning spelling's share of all the ways the word is written
MIN_SEEN = 3         # and it must have been seen this often


def asciify(text: str) -> str:
    return text.translate(_ASCII)


def tr_lower(text: str) -> str:
    return text.replace("I", "ı").replace("İ", "i").lower()


def tr_upper(text: str) -> str:
    return text.replace("i", "İ").replace("ı", "I").upper()


def words(text: str) -> List[str]:
    return WORD.findall(text or "")


@lru_cache(maxsize=1)
def table() -> Dict[str, str]:
    """ascii word -> the Turkish spelling it stands for, where one dominates."""
    out: Dict[str, str] = {}
    try:
        with open(DATA, encoding="utf-8") as f:
            for line in f:
                if line.startswith("#") or not line.strip():
                    continue
                ascii_form, spelled, plain = line.rstrip("\n").split("\t")
                forms = Counter({w: int(n) for w, n in (p.rsplit(":", 1) for p in spelled.split(","))})
                best, n = forms.most_common(1)[0]
                total = sum(forms.values()) + int(plain)
                if n >= MIN_SEEN and n / total >= MIN_SHARE:
                    out[ascii_form] = best
    except OSError:
        pass
    return out


def _cased_like(word: str, spelled: str) -> str:
    if word.isupper() and len(word) > 1:
        return tr_upper(spelled)
    if word[:1].isupper():
        return tr_upper(spelled[:1]) + spelled[1:]
    return spelled


def restore(text: Optional[str]) -> Tuple[str, List[Tuple[str, str]]]:
    """The text with Turkish letters restored where the books are sure, and
    the (was, now) pairs changed. A word that already has a Turkish letter
    is the reader's own spelling and is never touched."""
    if not text:
        return text or "", []
    t = table()
    changes: List[Tuple[str, str]] = []

    def fix(m: "re.Match") -> str:
        w = m.group(0)
        if asciify(w) != w:
            return w
        spelled = t.get(w.lower())        # an ASCII word: its I is an i or a ı, the table knows which
        if not spelled:
            return w
        new = _cased_like(w, spelled)
        if new != w:
            changes.append((w, new))
        return new

    return WORD.sub(fix, text), changes
