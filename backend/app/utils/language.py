"""Work out what language a book is written in, from the book's own text.

Why this exists: the builder hard-coded `dc:language="en"` on every EPUB it
has ever produced. That is not a metadata nicety. A reader uses the language
tag to pick a hyphenation dictionary, to choose a text-to-speech voice, and
to decide which font fallbacks and line-breaking rules apply, so a Turkish
book declared as English gets hyphenated by English rules and read aloud in
an English voice.

Method
------
Two independent kinds of evidence, combined — never one number:

1. **Function words.** Every language has a small closed class of words
   (articles, conjunctions, prepositions) that appear at enormous frequency
   and almost nowhere else. Measuring what share of a sample's words are a
   given language's function words separates languages robustly, and it
   degrades gracefully: a mixed-language book scores middling everywhere
   instead of confidently wrong.

2. **Orthography.** Characters that one language uses and its neighbours do
   not — 'ğ' and 'ı' for Turkish, 'ß' for German, 'ñ' for Spanish. This is
   what breaks the ties function words cannot: Spanish and Italian share a
   great many short words, and 'ñ' settles it.

Neither signal decides alone. Function-word share sets the ranking and
orthography adjusts it, and when the top two candidates finish close the
result is reported as low-confidence so the caller can say so rather than
quietly asserting something it does not know.

The list of languages is deliberately small and covers what this tool is
actually used for. An unlisted language yields a low-confidence guess, which
is the honest answer — better than a confident wrong one, and the tag stays
editable either way.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional

# Closed-class words, the highest-frequency ones for each language. Kept
# short on purpose: rare words add noise, not discrimination.
FUNCTION_WORDS: Dict[str, frozenset] = {
    "tr": frozenset("""ve bir bu için ile de da olarak daha çok gibi ama en ne
        o kadar sonra her olan olduğu değil ise mi ki veya ancak yani hem
        şey bütün kendi böyle onun bende""".split()),
    "en": frozenset("""the of and to in that is was it for as with his on be
        at by not this but from are have had they which you an or we their
        been has would there""".split()),
    "de": frozenset("""der die und den von zu das mit sich des auf für ist im
        dem nicht ein eine als auch es an werden aus er hat dass sie nach
        wird bei einer""".split()),
    "fr": frozenset("""le la les de des et un une du en que qui dans pour sur
        est il au plus ce par ne pas se sont avec son ses comme mais ou
        cette nous""".split()),
    "es": frozenset("""de la que el en y los del se las por un para con no
        una su al lo como más pero sus le ya o este porque esta entre
        cuando""".split()),
    "it": frozenset("""di che e la il un per in non una sono come ma si lo ha
        le da più al del con nel alla dei se gli anche io sulla nella""".split()),
}

# Characters a language uses that its nearest competitors do not. Presence is
# weak evidence on its own (a quotation can contain anything), which is why it
# only adjusts the function-word ranking instead of overriding it.
MARKER_CHARS: Dict[str, str] = {
    "tr": "ğışĞİŞ",
    "en": "",
    "de": "ß",
    "fr": "çàèêôœ",
    "es": "ñ¿¡",
    "it": "àèìòù",
}

SAMPLE_WORDS = 4000
MARKER_BONUS = 0.35
CONFIDENT_MARGIN = 0.25  # top must beat runner-up by this share to be "confident"

_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)

DEFAULT_LANGUAGE = "en"


@dataclass
class LanguageGuess:
    code: str
    confident: bool
    scores: Dict[str, float]

    @property
    def runner_up(self) -> Optional[str]:
        ranked = sorted(self.scores, key=lambda k: self.scores[k], reverse=True)
        return ranked[1] if len(ranked) > 1 else None


def detect_language(text: str, sample_words: int = SAMPLE_WORDS) -> LanguageGuess:
    """Best guess at the language of `text`, with an honest confidence flag."""
    words: List[str] = _WORD_RE.findall((text or "").lower())[:sample_words]
    if len(words) < 30:
        # Too little to say anything. Report the fallback, not confidently.
        return LanguageGuess(DEFAULT_LANGUAGE, False, {})

    sample = " ".join(words)
    scores: Dict[str, float] = {}
    for code, stopwords in FUNCTION_WORDS.items():
        share = sum(1 for w in words if w in stopwords) / len(words)
        markers = MARKER_CHARS[code]
        has_marker = any(c in sample for c in markers) if markers else False
        scores[code] = share * (1.0 + MARKER_BONUS) if has_marker else share

    ranked = sorted(scores, key=lambda k: scores[k], reverse=True)
    best, second = ranked[0], ranked[1]
    top = scores[best]
    if top < 0.06:
        # Nothing looks like a language we know. Say so.
        return LanguageGuess(DEFAULT_LANGUAGE, False, scores)
    confident = (top - scores[second]) >= top * CONFIDENT_MARGIN
    return LanguageGuess(best, confident, scores)
