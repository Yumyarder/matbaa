"""Correct a scanner's misreadings from the book's own vocabulary.

A scanned page's text layer loses letters a clean page keeps: the drop
initial of a bibliography entry ("ookchin, M." for "Bookchin, M."), a
capital read as another glyph ("ıeleuze" for "Deleuze"), the ones of a
year read as letters ("20ll'den" for "2011'den"). The book itself usually
prints the word whole somewhere else — Bookchin is quoted in the running
text — and that is the only dictionary trusted here: a word is replaced
only by a form the same book spells, and only when the misread form is
not itself a word the book uses.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Dict, Iterable, Optional

WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
# glyphs a scanner reads in place of a lost or unclear capital
CAPITAL_STAND_INS = set("ıl1|iI!")
# a year whose digits were read as letters: "20ll", "l989", "201O" — but not
# "20lı yıllar", the twenties
YEAR_MISREAD = re.compile(r"(?<![\w])((?:1[5-9]|20|l[5-9]|ı[5-9])[0-9lIoO]{2})(?![\w])")
MIN_WORD = 4
ENTRY_HEAD = re.compile(r",\s*[A-ZÇĞİÖŞÜ]")


def build_vocabulary(texts: Iterable[str]) -> Counter:
    vocab: Counter = Counter()
    for t in texts:
        vocab.update(WORD.findall(t or ""))
    return vocab


def capitalised_forms(vocab: Counter) -> Dict[str, str]:
    """tail (lower-cased, without its first letter) -> the capitalised word
    the book spells, where only one such word has that tail."""
    seen: Dict[str, Optional[str]] = {}
    for w in vocab:
        if len(w) >= MIN_WORD + 1 and w[0].isupper() and w[1:].islower():
            key = w[1:]
            seen[key] = w if key not in seen or seen[key] == w else None
    return {k: v for k, v in seen.items() if v}


def repair_word(word: str, vocab: Counter, forms: Dict[str, str]) -> str:
    if len(word) < MIN_WORD or not word.islower() or vocab.get(word, 0) > 1:
        return word
    # the first letter lost: "ookchin" -> "Bookchin"
    whole = forms.get(word)
    if whole and vocab.get(word, 0) <= 1:
        return whole
    # the first letter misread: "ıeleuze" -> "Deleuze"
    if word[0] in CAPITAL_STAND_INS:
        whole = forms.get(word[1:])
        if whole:
            return whole
    return word


def repair_text(text: str, vocab: Counter, forms: Optional[Dict[str, str]] = None) -> str:
    """`text` one paragraph, plain or HTML; only words outside tags are
    touched. A lost capital is restored only on the paragraph's first word —
    where a capital is expected, and where a scan drops one (a bibliography
    entry's initial) — so a real lower-case word elsewhere ("ilim" in a book
    that also prints "Bilim") is never touched."""
    if forms is None:
        forms = capitalised_forms(vocab)
    parts = re.split(r"(<[^>]+>|&#?\w+;)", text)
    first_done = False
    for k in range(0, len(parts), 2):
        piece = parts[k]
        if not first_done and piece.strip():
            m = WORD.search(piece)
            # a bibliography or index entry: "Surname, N." — a paragraph that
            # merely begins in lower case is a sentence's second half
            if m and not piece[:m.start()].strip() and ENTRY_HEAD.match(piece[m.end():]):
                piece = piece[:m.start()] + repair_word(m.group(0), vocab, forms) + piece[m.end():]
            first_done = True
        piece = YEAR_MISREAD.sub(lambda m: m.group(1).translate(str.maketrans("lıIoO", "11100")), piece)
        parts[k] = piece
    return "".join(parts)
