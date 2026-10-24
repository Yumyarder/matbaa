"""Pictures readied for an e-ink screen.

A scanned page shown as a picture brings its paper with it: yellowed, or
grey under the scanner's light. On a Kindle that paper turns into a grey
ground the text sits on. A picture without colour of its own (a scan, a
diagram, a photograph in black and white) is made grey-scale and its paper
set to white, the darkest tones left as they are. A picture in colour (a
cover, a designed back cover, a chart) is left exactly as it is: its colour
is the design, and a Kindle in colour, or the reader's phone, shows it.
"""
from __future__ import annotations

import io
from typing import Optional

from PIL import Image, ImageStat

COLOURFUL = 30          # mean saturation (0-255), paper balanced to white, above which a picture is in colour
JPEG_QUALITY = 75       # grey-scale scans of type: enough for e-ink, no larger than the colour original
PAPER_SHARE = 0.4       # the paper is the level the brightest 40% of the picture reaches
PAPER_MIN, PAPER_MAX = 150, 246     # paper this light and not already white is levelled


def _paper_level(gray: Image.Image) -> int:
    hist = gray.histogram()
    total, seen = sum(hist), 0
    for level in range(255, -1, -1):
        seen += hist[level]
        if seen >= total * PAPER_SHARE:
            return level
    return 255


def prepare(image_bytes: bytes) -> Optional[bytes]:
    """The picture readied for e-ink — a PNG stays a PNG, anything else
    becomes a JPEG — or None where it is best left alone (in colour,
    already white, or unreadable)."""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img.load()
    except Exception:  # noqa: BLE001
        return None
    rgb = img.convert("RGB")
    gray = rgb.convert("L")
    paper = _paper_level(gray)
    if not PAPER_MIN <= paper <= PAPER_MAX:
        return None
    # judged after the paper's own tint is taken out: yellowed paper is a
    # colour, but a yellowed scan balanced to white paper has none left
    mask = gray.point(lambda v: 255 if v >= paper else 0)
    tint = ImageStat.Stat(rgb, mask).mean
    if min(tint) <= 0:
        return None
    balanced = Image.merge("RGB", [band.point(lambda v, k=255 / t: min(255, round(v * k)))
                                   for band, t in zip(rgb.split(), tint)])
    if ImageStat.Stat(balanced.convert("HSV")).mean[1] > COLOURFUL:
        return None
    ink = gray.getextrema()[0]
    span = max(1, paper - ink)
    levelled = gray.point(lambda v: 255 if v >= paper else max(0, round((v - ink) * 255 / span)))
    out = io.BytesIO()
    if img.format == "PNG":
        levelled.save(out, "PNG", optimize=True)    # a drawing keeps its sharp lines
    else:
        levelled.save(out, "JPEG", quality=JPEG_QUALITY, optimize=True)
    return out.getvalue()
