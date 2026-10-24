"""From a Turkish word as a book prints it to its dictionary headword.

Turkish builds words by adding suffixes: "kitaplarımızdan" is "kitap" with
four of them, and a dictionary lists "kitap". The Kindle dictionary
(app/dictionary.py), the vocabulary of looked-up words (app/vocab.py), the
index and the search all need the headword, and they share this one
judgement:

1. the word itself is a headword ("karar", not "kar" + "ar");
2. the Turkish Wiktionary names it a form of one ("kitabı" → "kitap");
3. otherwise suffixes are taken off from the end, and the longest headword
   left over wins, the consonant a suffix softened put back ("kitab-ı" →
   "kitap", "çocuğ-u" → "çocuk"), a verb found by its stem ("geliyorum" →
   "gelmek"); a split is taken only where what is cut off reads as a run
   of Turkish suffixes ("-ları-mız-dan", not "-ektronik" off "el") whose
   first vowel harmonises with the stem's last ("saat-i" is a Wiktionary
   form instead).

A proper noun keeps its suffix behind an apostrophe ("Marx'ın"): the part
before it is the word.
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, Optional, Set

WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?", re.UNICODE)
APOSTROPHE = re.compile(r"['’]")
BACK, FRONT = set("aıou"), set("eiöü")
VOWELS = BACK | FRONT | set("âîû")
# a suffix whose vowel does not follow the stem's
INVARIANT = ("yor", "ken", "ki", "leyin", "daş", "gil")
SOFTENED = {"b": "p", "c": "ç", "d": "t", "g": "k", "ğ": "k"}
# the particles written apart that follow the word's vowels: a dictionary
# lists one form ("de", "mi")
PARTICLES = {"da": "de", "mı": "mi", "mu": "mi", "mü": "mi"}
MIN_STEM = 2
MAX_SUFFIX = 16


def _harmony(*shapes: str) -> Set[str]:
    """Every spelling of suffixes written with A (a/e) and I (ı/i/u/ü)
    standing for the vowel the stem calls for, D for d/t, C for c/ç, G for
    ğ/k (before a vowel / not)."""
    out: Set[str] = set()
    for shape in shapes:
        forms = [""]
        for ch in shape:
            options = {"A": "ae", "I": "ıiuü", "D": "dt", "C": "cç", "G": "ğk"}.get(ch, ch)
            forms = [f + o for f in forms for o in options]
        out.update(forms)
    return out


# the suffixes of Turkish, nominal and verbal, each in all its spellings: a
# split is taken only where what follows the stem is a run of these
MORPHEMES = _harmony(
    # case, number, possession
    "lAr", "I", "yI", "nI", "A", "yA", "nA", "DA", "nDA", "DAn", "nDAn", "In", "nIn", "yIn", "lA", "ylA",
    "CA", "ki", "m", "Im", "n", "In", "ImIz", "mIz", "InIz", "nIz", "sI", "lArI", "lArIn", "ken", "yken",
    # derivation
    "sIz", "lI", "lIG", "CI", "CIG", "sAl", "DAş", "CAsInA", "IncI", "ncI", "lAş", "lAn", "lA", "sA",
    "Imsı", "msı", "GIl", "Ca",
    # verbs
    "mAG", "mA", "yor", "Iyor", "AcAG", "yAcAG", "DI", "mIş", "Ar", "Ir", "r", "z", "sIn", "sInIz", "DIr",
    "Iz", "yIz", "yIm", "sA", "ysA", "mAz", "mAyA", "y", "Ip", "yIp", "ArAk", "yArAk", "IncA", "yIncA",
    "DIG", "An", "yAn", "Iş", "yIş", "Il", "t", "Ir", "Abil", "yAbil", "mAdAn", "AlI", "yAlI", "DIkçA",
    "mAlI", "AsI", "yAsI", "lIm", "yAlIm", "mAksIzIn", "DIkçA", "Ince", "mAktA", "Iver", "yIver",
)
_LONGEST = max(len(m) for m in MORPHEMES)


def suffix_chain(rest: str) -> bool:
    """Whether `rest` reads as Turkish suffixes, one after another."""
    ok = [False] * (len(rest) + 1)
    ok[0] = True
    for i in range(len(rest)):
        if not ok[i]:
            continue
        for k in range(1, min(_LONGEST, len(rest) - i) + 1):
            if rest[i:i + k] in MORPHEMES:
                ok[i + k] = True
    return ok[len(rest)]


def lower_tr(text: str) -> str:
    """Lower case by Turkish rules: I is ı, İ is i."""
    return (text or "").replace("I", "ı").replace("İ", "i").lower()


def words(text: str) -> Iterable[str]:
    """The words of a text, each lower-cased by Turkish rules, a proper
    noun's suffix after its apostrophe dropped."""
    for match in WORD.finditer(text or ""):
        w = APOSTROPHE.split(match.group(0))[0]
        if len(w) >= 2:
            yield lower_tr(w)


def _last_vowel(stem: str) -> Optional[str]:
    for c in reversed(stem):
        if c in VOWELS:
            return c
    return None


def _first_vowel(suffix: str) -> Optional[str]:
    for c in suffix:
        if c in VOWELS:
            return c
    return None


def _harmonises(stem: str, suffix: str) -> bool:
    if suffix.startswith(INVARIANT):
        return True
    last, first = _last_vowel(stem), _first_vowel(suffix)
    if last is None or first is None:
        return True
    if last in "âîû":            # a loanword's long vowel: either goes
        return True
    return (last in BACK) == (first in BACK)


class Lemmatizer:
    """`headwords`: every word the dictionary has an entry for; `forms`:
    inflected form -> headword, as Wiktionary lists them."""

    def __init__(self, headwords: Iterable[str], forms: Optional[Dict[str, str]] = None):
        self.headwords: Set[str] = set(headwords)
        self.forms: Dict[str, str] = dict(forms or {})
        self._cache: Dict[str, Optional[str]] = {}

    def lemma(self, word: str) -> Optional[str]:
        w = lower_tr(APOSTROPHE.split(word or "")[0]).strip()
        if len(w) < MIN_STEM:
            return None
        if w in self._cache:
            return self._cache[w]
        found = self._find(w)
        self._cache[w] = found
        return found

    def _find(self, w: str) -> Optional[str]:
        if w in self.headwords:
            return w
        if w in self.forms:
            return self.forms[w]
        if PARTICLES.get(w) in self.headwords:
            return PARTICLES[w]
        for cut in range(len(w) - 1, MIN_STEM - 1, -1):
            stem, suffix = w[:cut], w[cut:]
            if len(suffix) > MAX_SUFFIX:
                break
            if not _harmonises(stem, suffix) or not suffix_chain(suffix):
                continue
            for candidate in (stem, stem[:-1] + SOFTENED.get(stem[-1], stem[-1])):
                if candidate in self.headwords:
                    return candidate
                if candidate in self.forms and len(candidate) >= 3:
                    return self.forms[candidate]
            for infinitive in (stem + "mek", stem + "mak"):
                if infinitive in self.headwords:
                    return infinitive
        return None
