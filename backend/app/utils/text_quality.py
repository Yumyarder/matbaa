"""Is a text layer words, or noise?

A PDF can carry a text layer that is not text: a font whose character map
is broken returns control characters for every glyph (seven books of the
library survey, Acrobat Distiller 4), and a scanner's OCR can return
shards of symbols. Both look like text to an extractor — characters, on a
page — and both went into books as gibberish. These measures tell them
apart from the book's own words, so such pages can be read again by OCR.
"""
from __future__ import annotations

import re
import unicodedata

_EDGE_PUNCT = ".,;:!?\"'()[]«»“”‘’-–—…*"


def _reads_as_word(token: str) -> bool:
    letters = "".join(c for c in token if c.isalpha())
    if len(letters) < 2:
        return True
    core = token.strip(_EDGE_PUNCT)
    # A compound joined by a dash ("Savaş-Evrensel", "Tefeci-Bezirgan") is
    # words when each part is one; read whole, its inner capital looked
    # like noise and failed titles that were perfectly sound.
    parts = [p for p in re.split(r"[-–—/]", core) if p]
    if len(parts) > 1:
        return all(_reads_as_word(p) for p in parts)
    if any(c.isdigit() for c in token) or len(letters) < len(core) - 2:
        return False
    return (letters == letters.lower() or letters == letters.upper()
            or letters == letters[0].upper() + letters[1:].lower())


def garbage_share(text: str) -> float:
    """Share of the text that is not words.

    Control and private-use characters count against it, and so do tokens
    that switch case inside themselves or mix symbols in among letters.
    Measured per page on the 47-book library: the broken books score over
    0.3 on every page, the sound ones at most 0.17 except for one or two
    pages of decoration or tables.
    """
    if not text:
        return 0.0
    control = sum(1 for c in text if unicodedata.category(c) in ("Cc", "Co") and c not in "\n\t\r")
    tokens = [t for t in text.split() if any(c.isalpha() for c in t)]
    bad = sum(1 for t in tokens if not _reads_as_word(t))
    return round(max(control / max(1, len(text)), bad / max(1, len(tokens))), 3)
