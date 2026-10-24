"""The book's cover: the PDF's own, cleaned, or a typographic one.

A cover rendered from a PDF page brings the page's margins with it, and a
scan brings the scanner's dark edges. `clean()` trims those bands around
the picture; it never cuts into the picture itself, nor changes a colour.

Some PDFs have no usable cover at all — a title page in plain type, a
library stamp, a photocopy. `typographic()` sets one in the manner of a
series: the author above, the title large in the middle, a rule, the
series mark below, on a pale ground that reads well in a Kindle's
grey-scale library. Faces come from the system (rendered into the picture,
never embedded in the book); without one, Pillow's own face is used.
"""
from __future__ import annotations

import base64
import io
import os
from typing import List, Optional

from PIL import Image, ImageDraw, ImageFont

from app.typography import set_text

COVER_SIZE = (1600, 2560)            # Kindle's own guidance: 1:1.6
PAPER = (245, 242, 234)
INK = (24, 22, 20)
MUTED = (96, 92, 86)
SERIES_MARK = "MATBAA"

# a band of the image counts as margin when it is this plain
PLAIN_WHITE = 242
PLAIN_DARK = 30
PLAIN_SPREAD = 10                    # grey levels of variation along the band
MAX_TRIM = 0.15                      # never more than this much of a side
MAX_DARK_TRIM = 0.04                 # a scanner's edge is a strip; a black cover is the design

_FONT_DIRS = [os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),
              "/usr/share/fonts/truetype/dejavu", "/Library/Fonts", "/System/Library/Fonts/Supplemental"]
# (regular, bold, italic) — the first family found is used
_FAMILIES = [
    ("georgia.ttf", "georgiab.ttf", "georgiai.ttf"),
    ("BOOKOS.TTF", "BOOKOSB.TTF", "BOOKOSI.TTF"),
    ("constan.ttf", "constanb.ttf", "constani.ttf"),
    ("DejaVuSerif.ttf", "DejaVuSerif-Bold.ttf", "DejaVuSerif-Italic.ttf"),
    ("Georgia.ttf", "Georgia Bold.ttf", "Georgia Italic.ttf"),
]


# --- the PDF's cover, cleaned -------------------------------------------------------------

def _plain(values: List[int], dark: bool) -> bool:
    lo, hi = min(values), max(values)
    return hi - lo <= PLAIN_SPREAD and (hi <= PLAIN_DARK if dark else lo >= PLAIN_WHITE)


def _trim_box(gray: Image.Image) -> tuple:
    """Where the picture is. A scanner's dark edge is a thin strip and is
    always cut (MAX_DARK_TRIM); a white margin only when the picture has
    one on all four sides, a cover pasted on a page — a white cover that
    is white to one edge is the design, and stays as it is."""
    w, h = gray.size
    px = gray.load()
    step = max(1, min(w, h) // 300)

    def band(side: str, i: int) -> List[int]:
        if side in ("top", "bottom"):
            return [px[x, i] for x in range(0, w, step)]
        return [px[i, y] for y in range(0, h, step)]

    def inward(side: str, start: int, limit: float, dark: bool) -> int:
        length = h if side in ("top", "bottom") else w
        sign = 1 if side in ("top", "left") else -1
        i, moved = start, 0
        while 0 <= i < length and _plain(band(side, i), dark):
            if moved >= length * limit:
                # still plain at the limit: not a margin but the cover's own ground
                return start
            i += sign
            moved += 1
        return i

    edge = {"top": 0, "bottom": h - 1, "left": 0, "right": w - 1}
    dark_cut = {s: inward(s, i, MAX_DARK_TRIM, True) for s, i in edge.items()}
    white_cut = {s: inward(s, i, MAX_TRIM, False) for s, i in dark_cut.items()}
    framed = all(abs(white_cut[s] - dark_cut[s]) >= 0.01 * (h if s in ("top", "bottom") else w)
                 for s in edge)
    cut = white_cut if framed else dark_cut
    return cut["left"], cut["top"], cut["right"] + 1, cut["bottom"] + 1


def clean(image_bytes: bytes) -> bytes:
    """The cover without its blank or dark margins; a JPEG. Its colours are
    left alone: a flat red or orange cover has a grey range as narrow as a
    faded scan's, and stretching it turned red to magenta and orange to
    yellow on the library's own covers."""
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    box = _trim_box(img.convert("L"))
    if box == (0, 0, img.width, img.height):
        return image_bytes
    out = io.BytesIO()
    img.crop(box).save(out, "JPEG", quality=88, optimize=True)
    return out.getvalue()


def clean_base64(cover_b64: Optional[str]) -> Optional[str]:
    """clean() for a cover kept as base64 (a session's, a conversion's); the
    cover as it was if it cannot be read — a cover is never lost to this."""
    if not cover_b64:
        return cover_b64
    try:
        return base64.b64encode(clean(base64.b64decode(cover_b64))).decode("ascii")
    except Exception:  # noqa: BLE001
        return cover_b64


# --- a typographic cover -------------------------------------------------------------------

def _font_files() -> Optional[tuple]:
    for family in _FAMILIES:
        for folder in _FONT_DIRS:
            paths = tuple(os.path.join(folder, name) for name in family)
            if os.path.isfile(paths[0]):
                return tuple(p if os.path.isfile(p) else paths[0] for p in paths)
    return None


def _font(path: Optional[str], size: int) -> ImageFont.ImageFont:
    if path:
        return ImageFont.truetype(path, size)
    try:
        return ImageFont.load_default(size)
    except TypeError:                 # an older Pillow: one size only
        return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> List[str]:
    lines: List[str] = []
    for word in text.split():
        if lines and draw.textlength(lines[-1] + " " + word, font=font) <= width:
            lines[-1] += " " + word
        else:
            lines.append(word)
    return lines


def _fit(draw, text: str, path: Optional[str], width: int, sizes: range, max_lines: int):
    """The largest size at which `text` wraps into `max_lines` lines no
    wider than `width` (no word broken); the smallest size otherwise."""
    for size in sizes:
        font = _font(path, size)
        lines = _wrap(draw, text, font, width)
        if len(lines) <= max_lines and all(draw.textlength(l, font=font) <= width for l in lines):
            return font, lines, size
    font = _font(path, sizes[-1])
    return font, _wrap(draw, text, font, width), sizes[-1]


def _centered(draw, y: int, lines: List[str], font, fill, leading: float) -> int:
    size = font.size if hasattr(font, "size") else 40
    for line in lines:
        w = draw.textlength(line, font=font)
        draw.text(((COVER_SIZE[0] - w) / 2, y), line, font=font, fill=fill)
        y += round(size * leading)
    return y


def typographic(title: str, author: str = "") -> bytes:
    """A cover set in type: author, title, a rule, the series mark. A JPEG.
    The author is set as written, not in capitals: capitals would give a
    foreign name a Turkish dotted İ ("STAVRİDES")."""
    title = set_text(" ".join((title or "").split())) or "Adsız Kitap"
    author = set_text(" ".join((author or "").split()))
    if author.lower() in ("unknown", "bilinmiyor"):
        author = ""
    main, _, sub = title.partition(":")
    main, sub = main.strip(), sub.strip()

    files = _font_files()
    regular, bold, italic = files if files else (None, None, None)
    img = Image.new("RGB", COVER_SIZE, PAPER)
    draw = ImageDraw.Draw(img)
    w, h = COVER_SIZE
    margin = 150

    # a double frame, as a series' covers often have
    draw.rectangle([70, 70, w - 70, h - 70], outline=INK, width=6)
    draw.rectangle([92, 92, w - 92, h - 92], outline=INK, width=2)

    if author:
        font, lines, _ = _fit(draw, author, regular, w - 2 * margin, range(76, 43, -4), 2)
        _centered(draw, 430, lines, font, MUTED, 1.35)

    font, lines, size = _fit(draw, main, bold, w - 2 * margin, range(170, 79, -6), 5)
    block = len(lines) * round(size * 1.18)
    y = max(760, (h - block) // 2 - 120)
    y = _centered(draw, y, lines, font, INK, 1.18)

    if sub:
        font, sub_lines, _ = _fit(draw, sub, italic, w - 2 * margin, range(80, 47, -4), 3)
        y = _centered(draw, y + 40, sub_lines, font, MUTED, 1.3)

    draw.line([(w / 2 - 160, y + 70), (w / 2 + 160, y + 70)], fill=INK, width=4)

    mark = _font(regular, 46)
    spaced = " ".join(SERIES_MARK)
    draw.text(((w - draw.textlength(spaced, font=mark)) / 2, h - 300), spaced, font=mark, fill=MUTED)
    out = io.BytesIO()
    img.save(out, "JPEG", quality=90, optimize=True)
    return out.getvalue()


def typographic_base64(title: str, author: str = "") -> str:
    return base64.b64encode(typographic(title, author)).decode("ascii")
