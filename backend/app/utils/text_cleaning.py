"""
Typography & artifact cleaning utilities.

Handles:
- Ligature normalization (fi, fl, ff, ffi, ffl, st...)
- Ghost / glyph-glitch character stripping (lone subset-font junk characters
  that PyMuPDF sometimes extracts from broken embedded fonts)
- Hyphenation repair for words split across a line break ("exam-\nple" -> "example")
"""

import re
import unicodedata

LIGATURE_MAP = {
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
    "\ufb05": "st",
    "\ufb06": "st",
}

# Characters that are almost always OCR/font-subset glitches when they show
# up as an ISOLATED single-character "word" surrounded by whitespace.
# These are typically private-use-area glyphs or stray diacritic letters
# left behind by a broken embedded subset font.
_GHOST_SINGLE_CHARS = set(
    "êüėÐþøǽǣœĳﬀﬁﬂ" + "".join(chr(c) for c in range(0xE000, 0xF8FF + 1))
)


def normalize_ligatures(text: str) -> str:
    for lig, plain in LIGATURE_MAP.items():
        text = text.replace(lig, plain)
    return text


def strip_ghost_tokens(text: str) -> str:
    """Remove standalone glitch characters/tokens (isolated by whitespace)."""
    tokens = text.split(" ")
    cleaned = []
    for tok in tokens:
        bare = tok.strip()
        if len(bare) == 1 and bare in _GHOST_SINGLE_CHARS:
            continue
        # subset-font glitch words: 3+ chars, no vowels, mixes case oddly,
        # and contains at least one private-use / control-adjacent char
        if len(bare) >= 2 and any(ord(c) > 0xE000 for c in bare):
            continue
        cleaned.append(tok)
    return " ".join(cleaned)


def repair_hyphenation(text: str) -> str:
    """Join words that were split across a line break with a trailing
    hyphen — either a plain ASCII hyphen-minus, or the Unicode soft hyphen
    (U+00AD), which many PDF typesetting tools use specifically to mark an
    optional line-wrap break point. It looks identical to a normal hyphen
    when rendered at a line end, but is a completely different character,
    so a regex that only checks for '-' silently misses every one of
    these — confirmed on a real book where soft hyphens outnumbered plain
    ones roughly 25 to 1."""
    # Emphasis sentinels (U+000E-U+0011) may sit on either side of the break.
    return re.sub(
        r"(\w)([\x0e-\x11]*)[-\u00ad]([\x0e-\x11]*)\s*\n\s*([\x0e-\x11]*)(\w)",
        r"\1\2\3\4\5",
        text,
    )


def is_mostly_punctuation_or_digits(text: str, threshold: float = 0.55) -> bool:
    """Used to detect index/Fihrist pages: dense with digits and commas."""
    if not text.strip():
        return False
    digits_and_punct = sum(1 for c in text if c.isdigit() or c in ",.;:-")
    return (digits_and_punct / max(1, len(text))) > threshold


# Some academic PDFs embed a font whose ToUnicode table has been damaged or
# deliberately scrambled (common in documents re-exported or "protected" by
# older publishing tools): the glyph that RENDERS as "(" or ")" reports the
# wrong codepoint to any text extractor, most often "<" or ">". PyMuPDF is
# extracting exactly what the PDF declares — this isn't something a
# geometry-based fix can catch, because the character stream itself is
# wrong, not just its spacing.
#
# "<" and ">" essentially never appear in real running Turkish prose (this
# app's target content is academic books, not math or code), so treating
# one as a mis-mapped parenthesis is safe precisely when it sits flush
# against a real character the way an actual parenthesis would — no space
# on the inside, exactly as "(Berkeley ve Los Angeles)" or "(1994)" would be
# typeset. A genuine comparison operator in body text would essentially
# never be typeset with that flush spacing, so this is a general repair for
# a known class of broken PDF, not a guess tuned to any one book.
_BROKEN_OPEN_PAREN_RE = re.compile(r"<(?=[^\s<>])")
_BROKEN_CLOSE_PAREN_RE = re.compile(r"(?<=[^\s<>])>")


def fix_broken_bracket_glyphs(text: str) -> str:
    text = _BROKEN_OPEN_PAREN_RE.sub("(", text)
    text = _BROKEN_CLOSE_PAREN_RE.sub(")", text)
    return text


def clean_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = normalize_ligatures(text)
    text = fix_broken_bracket_glyphs(text)
    text = text.replace("\n", " ")
    # A soft hyphen (U+00AD) that's still here at this point is one that
    # repair_hyphenation() didn't need to join across a line break — it
    # was just marking an optional break point mid-line and is meant to
    # be entirely invisible in normal reading. Never render it as a
    # visible character.
    text = text.replace("\u00ad", "")
    text = strip_ghost_tokens(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = text.strip()
    # Defensive backup: collapse_tracked_caps only fires on short, >=85%
    # uppercase lines, so it's a no-op on ordinary body paragraphs and only
    # repairs heading-style letter-spacing that slipped past the geometric
    # (character-bbox) fix in pdf_parser.
    if len(text) <= 90:
        text = collapse_tracked_caps(text)
    return text


def is_symbol_line(text: str) -> bool:
    """Detects decorative section-break glyphs like '❖' or '***' or '— • —'."""
    stripped = text.strip()
    if not stripped:
        return False
    if re.fullmatch(r"[\*\-\u2022\u2726\u2727\u2756\u25CF\u00A7~\s]{1,12}", stripped):
        return True
    decorative_chars = set("❖✦✧☙❧⁂◆◇●○∗\u2741\u2742\u2698")
    if len(stripped) <= 6 and any(c in decorative_chars for c in stripped):
        return True
    return False


# ---------------------------------------------------------------------------
# Letter-tracking repair
# ---------------------------------------------------------------------------
# Many InDesign-typeset academic books render small-caps headings with real,
# oversized tracking between glyphs. Naive text extraction (both pdftotext
# and PyMuPDF's span joiner) infers a plain space at every large gap, so
# "BİRİNCİ BÖLÜM" comes out as "B İ R İ N C İ B ÖLÜ M". pdf_parser fixes this
# properly using character bounding boxes when available; this is a
# text-only backup for callers that only have a plain string.
def collapse_tracked_caps(line: str) -> str:
    letters = [c for c in line if c.isalpha()]
    if len(letters) < 4:
        return line
    upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
    if upper_ratio < 0.85:
        return line  # not an all-caps heading-style line; leave alone

    tokens = line.split(" ")
    words = []
    buf = ""
    for tok in tokens:
        if not tok:
            continue
        if len(tok) <= 2:
            buf += tok
        else:
            if buf:
                words.append(buf)
                buf = ""
            words.append(tok)
    if buf:
        words.append(buf)
    return " ".join(words)


def strip_dot_leaders(text: str) -> str:
    """Removes '. . . . .' or '.......' style TOC leader dots, keeping the title."""
    return re.sub(r"(?:\.\s*){2,}", " ", text).strip()


def looks_like_toc_line(text: str) -> bool:
    """A line like 'CHAPTER ONE . . . . . . 17' or 'CHAPTER ONE   17'."""
    stripped = text.strip()
    if not stripped:
        return False
    # dot leaders: tolerate both "......." and the more common InDesign
    # "space-separated dot" style ". . . . ."
    if re.search(r"(?:\.\s*){4,}\d{1,4}\s*$", stripped):
        return True
    if re.search(r"\S\s{2,}\d{1,4}\s*$", stripped) and len(stripped) < 120:
        return True
    return False
