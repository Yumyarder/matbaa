"""Aggressive text normalisation, used only for *comparison* — never for
anything that reaches the reader.

Both sides of every comparison in this harness go through normalize(). That
matters because the things we want to ignore are exactly the things that
differ innocently between a PDF, a freshly-converted EPUB, and a
hand-corrected historical EPUB: apostrophe style ('/’/ʼ), quote style,
dash style, soft hyphens, ligatures, letter case, Turkish dotted/dotless i
folding, and run of whitespace.

What normalize() must NOT do is hide missing words. It keeps every letter
and digit it is given.
"""

from __future__ import annotations

import re
import unicodedata

_LIGATURES = {
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl",
    "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st",
}

# Turkish casefolding is a trap: str.lower() maps 'I' -> 'i' but the Turkish
# dotless 'ı' and dotted 'İ' need to collapse onto the same bucket as their
# ASCII neighbours or a probe drawn from the PDF will never match the EPUB.
# Since this is comparison-only, folding both onto 'i' is exactly right.
_FOLD = str.maketrans({
    "İ": "i", "I": "i", "ı": "i", "i": "i",
    "Ş": "s", "ş": "s", "Ğ": "g", "ğ": "g",
    "Ü": "u", "ü": "u", "Ö": "o", "ö": "o", "Ç": "c", "ç": "c",
})

_NON_ALNUM = re.compile(r"[^0-9a-z ]+")
_WS = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Fold text down to lowercase ASCII alphanumerics and single spaces."""
    if not text:
        return ""
    for lig, plain in _LIGATURES.items():
        text = text.replace(lig, plain)
    text = text.replace("­", "")          # soft hyphen: invisible by definition
    text = text.translate(_FOLD)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = _NON_ALNUM.sub(" ", text)
    return _WS.sub(" ", text).strip()


def words(text: str) -> list:
    return normalize(text).split()
