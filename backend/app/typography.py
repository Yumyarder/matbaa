"""Typesetting the text the way a printed Turkish book sets it.

A PDF's text layer — a scan's above all — gives typewriter marks: straight
quotes, an apostrophe that is a straight quote, three full stops for an
ellipsis, a hyphen where the book printed a dash, and an ordinary space
between "s." and its page number, so a Kindle can break the line between
them. This pass sets them as a printer would, in text nodes only:

- "…" -> “…”, '…' -> ‘…’, and the apostrophe of a suffix -> ’ ("Simmel’in");
- "..." and ". . ." -> …;
- "--" -> —; a hyphen with a space on each side -> –; a range of numbers
  ("1990-1995", "s. 12-15") -> en dash;
- a no-break space after "s.", "ss.", "bkz.", "vb." before a number, and
  inside "M.Ö." / "M.S." before the year.

Nothing inside a tag, an attribute or a web address is touched.
"""
from __future__ import annotations

import html
import re

NBSP = "\u00a0"
_TAG = re.compile(r"(<[^>]+>)")
_URL = re.compile(r"(?:https?://|www\.)\S+")

# opening position: start of text, after whitespace or an opening bracket or a dash
_OPENS_BEFORE = set(" \t\n\u00a0([{—–-/“‘«")

# exactly three: a contents page's leader dots ("Giriş ........ 5") stay as printed
_ELLIPSIS = re.compile(r"(?<!\.)(?<!\.\s)\.\s?\.\s?\.(?!\s?\.)")
# a quote at the start of a paragraph, a heading or a note opens it, whatever
# the paragraph before ended with
_BLOCK_TAG = re.compile(r"</?(?:p|div|h[1-6]|li|ul|ol|blockquote|aside|section|td|th|tr|table|figure|figcaption|dt|dd)\b|<br\b",
                        re.I)
_EM_DASH = re.compile(r"\s*--\s*")
_SPACED_HYPHEN = re.compile(r"(?<=\S) - (?=\S)")
_NUMBER_RANGE = re.compile(r"(?<![\w./-])(\d{1,4})-(\d{1,4})(?![\w/-])")
_ABBREV_NUMBER = re.compile(r"\b(s|ss|sf|syf|bkz|Bkz|vb|vs|no|No|nr|cilt|Cilt|c)\.\s+(?=\d)")
_ERA = re.compile(r"\b(M\.Ö\.|M\.S\.|MÖ|MS)\s+(?=\d)|(?<=\d)\s+(M\.Ö\.|M\.S\.|MÖ|MS)\b")


def _quotes(text: str, prev: str) -> str:
    """Straight quotes to curly ones, deciding open or close by what stands
    before; `prev` is the character just before this text (from the
    previous text node)."""
    # two single quotes typed for a double one (a scanner's favourite)
    text = text.replace("''", '"')
    out = []
    before = prev
    for i, c in enumerate(text):
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if c == '"':
            out.append("“" if (not before or before in _OPENS_BEFORE) else "”")
        elif c == "'":
            if before and before.isalnum() and nxt.isalpha():
                out.append("’")                 # apostrophe: Simmel'in, 1980'ler
            elif (not before or before in _OPENS_BEFORE) and nxt and not nxt.isspace():
                out.append("‘")
            else:
                out.append("’")
        else:
            out.append(c)
        # what was set, so a quote inside an opening one opens too: "'…
        before = out[-1]
    return "".join(out)


def _plain_segment(text: str, prev: str) -> str:
    # web addresses keep every character as typed
    pieces = []
    pos = 0
    for m in _URL.finditer(text):
        pieces.append((text[pos:m.start()], True))
        pieces.append((m.group(0), False))
        pos = m.end()
    pieces.append((text[pos:], True))
    out = []
    for piece, setting in pieces:
        if setting and piece:
            piece = _ELLIPSIS.sub("…", piece)
            piece = _EM_DASH.sub("—", piece)
            piece = _SPACED_HYPHEN.sub(" – ", piece)
            piece = _NUMBER_RANGE.sub(lambda m: f"{m.group(1)}–{m.group(2)}", piece)
            piece = _ABBREV_NUMBER.sub(lambda m: m.group(1) + "." + NBSP, piece)
            piece = _ERA.sub(lambda m: (m.group(1) + NBSP) if m.group(1) else (NBSP + m.group(2)), piece)
            piece = _quotes(piece, prev)
        out.append(piece)
        if piece:
            prev = piece[-1]
    return "".join(out)


def set_text(text: str, prev: str = "") -> str:
    """One run of plain text, typeset."""
    return _plain_segment(text, prev)


def set_html(fragment: str) -> str:
    """An HTML fragment with every text node typeset; tags and attributes
    are left exactly as they are."""
    if not fragment:
        return fragment
    parts = _TAG.split(fragment)
    prev = ""
    for k in range(0, len(parts), 2):
        if k and _BLOCK_TAG.match(parts[k - 1]):
            prev = ""
        raw = parts[k]
        if not raw:
            continue
        plain = html.unescape(raw)
        done = _plain_segment(plain, prev)
        parts[k] = html.escape(done, quote=False)
        prev = done[-1] if done else prev
    return "".join(parts)
