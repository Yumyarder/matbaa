"""Soft hyphens at Turkish syllable breaks.

Justified text on a narrow screen needs words that can break; a Kindle has
no Turkish hyphenation dictionary, so long words jump to the next line
whole and leave gaps in the line above. Turkish syllables follow a regular
rule, so no dictionary is needed: between two vowels, the consonants that
separate them divide so that the next syllable starts with exactly one
consonant —

    V-V      sa-at          one consonant:   ka-pı
    VC-CV    kap-ta         three:           Türk-çe, kork-mak

A soft hyphen (U+00AD) is invisible unless the line breaks there. Short
words, words in capitals (abbreviations) and anything with a digit are left
whole, and no break leaves fewer than two letters on either side.

Turkish rules break other languages' words wrongly ("Stre-et", "Blo-oms-
bury"), and a Turkish book cites them all through its notes and
bibliography: a word spelt with letters or pairs Turkish does not use (q, w,
x, th, ch, oo, ou, ie …) is left whole, and so is a paragraph written in
English.
"""
from __future__ import annotations

import html
import re

SHY = "\u00ad"
VOWELS = set("aeıioöuüâîûAEIİOÖUÜÂÎÛ")
MIN_WORD = 6
MIN_PART = 2
_WORD = re.compile(r"[^\W\d_]{%d,}" % MIN_WORD)
_TAG = re.compile(r"(<[^>]+>)")
_HEADING = re.compile(r"<(/?)h[1-6]\b", re.I)
_BLOCK = re.compile(r"</?(?:p|div|h[1-6]|li|blockquote|aside|section|td|th|figcaption|dt|dd)\b", re.I)
_URL = re.compile(r"(?:https?://|www\.)\S+")
_FOREIGN = re.compile(r"[qwx]|th|ph|ck|sh|ch|gh|ee|oo|ou|ea|ie|ei|io|ia|ae|oe|au|eu", re.I)
_EN_WORDS = {"the", "and", "of", "to", "for", "with", "from", "by", "is", "are", "was", "an"}
_TR_WORDS = {"ve", "bir", "bu", "için", "ile", "da", "de", "ki", "gibi", "daha", "çok", "olarak", "olan"}


def breaks(word: str) -> list:
    """Indexes in `word` before which a syllable starts."""
    vowels = [i for i, c in enumerate(word) if c in VOWELS]
    points = []
    for a, b in zip(vowels, vowels[1:]):
        consonants = b - a - 1
        if consonants == 0:
            cut = b
        elif consonants <= 2:
            cut = b - 1
        else:
            cut = a + 3          # keep two consonants with the syllable before
        if MIN_PART <= cut <= len(word) - MIN_PART:
            points.append(cut)
    return points


def _english(text: str) -> bool:
    words = re.findall(r"[^\W\d_]+", text.lower())
    en = sum(w in _EN_WORDS for w in words)
    return en >= 2 and en > sum(w in _TR_WORDS for w in words)


def hyphenate_word(word: str) -> str:
    if len(word) < MIN_WORD or word.isupper() or SHY in word or _FOREIGN.search(word):
        return word
    pts = breaks(word)
    if not pts:
        return word
    out, last = [], 0
    for p in pts:
        out.append(word[last:p])
        last = p
    out.append(word[last:])
    return SHY.join(out)


def hyphenate_text(text: str) -> str:
    pieces, pos = [], 0
    for m in _URL.finditer(text):
        pieces.append(_WORD.sub(lambda w: hyphenate_word(w.group(0)), text[pos:m.start()]))
        pieces.append(m.group(0))
        pos = m.end()
    pieces.append(_WORD.sub(lambda w: hyphenate_word(w.group(0)), text[pos:]))
    return "".join(pieces)


def hyphenate_html(fragment: str) -> str:
    """Soft hyphens in every text node of an HTML fragment; tags untouched.
    A heading is set whole: a centred title broken mid-word reads as a typo."""
    if not fragment:
        return fragment
    parts = _TAG.split(fragment)
    block, in_heading = 0, False
    owner = {}                     # text node -> the block (paragraph, note …) it is in
    texts: dict = {}
    for k in range(0, len(parts), 2):
        if k:
            if _BLOCK.match(parts[k - 1]):
                block += 1
            tag = _HEADING.match(parts[k - 1])
            if tag:
                in_heading = not tag.group(1)
        if parts[k] and not in_heading:
            owner[k] = block
            texts.setdefault(block, []).append(parts[k])
    english = {b for b, t in texts.items() if _english(html.unescape("".join(t)))}
    for k, b in owner.items():
        if b not in english:
            parts[k] = html.escape(hyphenate_text(html.unescape(parts[k])), quote=False)
    return "".join(parts)
