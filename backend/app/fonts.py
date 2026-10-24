"""Typefaces embedded in the book.

A Kindle sets a book in the reader's chosen font; when the book carries its
own faces, the Aa menu offers them as "Yayıncı yazı tipi" (Publisher Font).
Matbaa ships Literata (SIL Open Font License; designed for long reading on
screens, with every Turkish letter) as four static faces made by
tools/make_fonts.py, and gives each book only the letters it uses, so a
face adds tens of kilobytes rather than hundreds.

A Kindle also takes typefaces of its own: files put in the fonts/ folder at
its root are offered in the Aa menu for every book, the reader's choice
like Bookerly. That is how Matbaa's faces reach the reader by default
(Literata, and Charis, SIL's Charter for small screens); kindle_files()
names them, kindle_usb puts them there.
"""
from __future__ import annotations

import io
import os
import string
from typing import Dict, List, Tuple

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")

# family id -> (label, folder, [(file, font-style, font-weight)])
FAMILIES: Dict[str, Tuple[str, str, List[Tuple[str, str, str]]]] = {
    "literata": ("Literata", "literata", [
        ("Literata-Regular.ttf", "normal", "normal"),
        ("Literata-Italic.ttf", "italic", "normal"),
        ("Literata-Bold.ttf", "normal", "bold"),
        ("Literata-BoldItalic.ttf", "italic", "bold"),
    ]),
}
# the faces put on the Kindle itself, whole: family folder -> four files
# named Family-Style, the way the Kindle's fonts/Readme.txt asks
KINDLE_FAMILIES: Dict[str, List[str]] = {
    "literata": ["Literata-Regular.ttf", "Literata-Italic.ttf", "Literata-Bold.ttf", "Literata-BoldItalic.ttf"],
    "charis": ["Charis-Regular.ttf", "Charis-Italic.ttf", "Charis-Bold.ttf", "Charis-BoldItalic.ttf"],
}
NO_FONT = "kindle"          # the reader's own font, nothing embedded
# Bookerly, the Kindle's default, was drawn for its screen (Dalton Maag,
# 2015); Literata for Google Play Books on phones and tablets. Neither has
# independent evidence of reading better on e-ink, and a Kindle shows a
# book's own face only when the reader picks "Yayıncı yazı tipi": the
# embedded face is the reader's choice, not the default.
DEFAULT_FONT = NO_FONT

# kept whatever the book's text: letters an edit may add, and the
# typesetting's own marks (curly quotes, dashes, no-break space, soft hyphen)
ALWAYS = (string.ascii_letters + string.digits + string.punctuation + " "
          + "çÇğĞıİöÖşŞüÜâÂîÎûÛêÊ“”‘’–—…«»•·" + chr(0xA0) + chr(0xAD))


def kindle_files() -> List[Tuple[str, str]]:
    """(file name on the Kindle, path here) for every face the Kindle's
    fonts/ folder gets."""
    return [(name, os.path.join(FONT_DIR, folder, name))
            for folder, names in KINDLE_FAMILIES.items() for name in names]


def font_list() -> List[Dict[str, str]]:
    return ([{"id": NO_FONT, "label": "Kindle'ın yazı tipi"}]
            + [{"id": k, "label": v[0]} for k, v in FAMILIES.items()])


def _subset(path: str, text: str) -> bytes:
    from fontTools import subset

    options = subset.Options()
    options.hinting = False              # e-ink renders unhinted outlines well, at half the size
    options.layout_features = ["kern", "liga", "clig", "calt", "ccmp", "locl", "mark", "mkmk"]
    options.name_IDs = ["*"]
    options.notdef_outline = True
    font = subset.load_font(path, options)
    subsetter = subset.Subsetter(options)
    subsetter.populate(text="".join(sorted(set(text + ALWAYS))))
    subsetter.subset(font)
    out = io.BytesIO()
    subset.save_font(font, out, options)
    return out.getvalue()


def faces(family: str, text: str) -> List[Tuple[str, bytes]]:
    """(file name, subset font) for each face of `family`, holding the
    letters of `text`."""
    if family not in FAMILIES:
        return []
    _, folder, files = FAMILIES[family]
    return [(name, _subset(os.path.join(FONT_DIR, folder, name), text)) for name, _, _ in files]


def font_css(family: str, folder: str = "../fonts") -> str:
    """The @font-face rules for `family`, the faces at `folder` (relative to
    the stylesheet)."""
    if family not in FAMILIES:
        return ""
    label, _, files = FAMILIES[family]
    rules = [f'@font-face {{ font-family: "{label}"; font-style: {style}; font-weight: {weight}; '
             f'src: url("{folder}/{name}"); }}' for name, style, weight in files]
    return "/* embedded faces (app/fonts.py) */\n" + "\n".join(rules) + "\n\n"


def with_family(css: str, family: str) -> str:
    """`css` with `family` set for the text and the titles: after the base
    stylesheet, which names Bookerly, and before a theme's block, so a
    theme that sets its titles in another face (Modern) keeps them."""
    if family not in FAMILIES:
        return css
    label = FAMILIES[family][0]
    rule = (f'\n/* the book\'s own face */\nbody, h1, h2, h3, .drop-cap::first-letter '
            f'{{ font-family: "{label}", "Bookerly", "Georgia", serif; }}\n')
    at = (css or "").find("/* matbaa-theme:")
    return css + rule if at < 0 else css[:at] + rule.lstrip("\n") + "\n" + css[at:]
