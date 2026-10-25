"""Regression coverage for automatic in-page figure detection.

    python tools/test_auto_figures.py

Companion to tools/test_regions.py, which pins the *hand-drawn* region
path. This one pins the automatic one: which embedded images become
figures, which are correctly refused, and that detection never costs the
page its text. Exit code is 1 if anything fails.

Note for anyone extending this: page.draw_rect() is a VECTOR drawing and
is invisible to get_image_info(), so it cannot stand in for a figure here.
Every image has to go in through page.insert_image() with a real pixmap.
"""
from __future__ import annotations

import os
import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if os.path.join(REPO_ROOT, "backend") not in sys.path:
    sys.path.insert(0, os.path.join(REPO_ROOT, "backend"))

import pymupdf as fitz  # noqa: E402

from app.parsers.pdf_parser import convert_pdf_to_chapters  # noqa: E402

OUT_DIR = os.path.join(REPO_ROOT, ".matbaa-work", "qa")
os.makedirs(OUT_DIR, exist_ok=True)

PAGE_W, PAGE_H = 400, 600
BODY_SIZE = 10
BODY = (
    "Bu paragraf sayfanin gercek govde metnidir ve figur bulunsa da "
    "bulunmasa da eksiksiz kalmalidir. Ikinci cumle de burada durur."
)

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        failures.append(name)


def pixmap(w: int, h: int, value: int) -> fitz.Pixmap:
    """A distinct pixmap per `value` — distinct pixels mean a distinct
    digest, which is what the repeated-furniture filter keys on."""
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, w, h))
    pix.clear_with(value)
    return pix


def convert(path: str, **kwargs):
    result = convert_pdf_to_chapters(path, **kwargs)
    figures = sum(p.count("region-figure") for ch in result.chapters for p in ch.paragraphs)
    images = sum(len(ch.images) for ch in result.chapters)
    text = " ".join(p for ch in result.chapters for p in ch.paragraphs)
    return result, figures, images, text


def write(doc: fitz.Document, name: str) -> str:
    path = os.path.join(OUT_DIR, name)
    doc.save(path)
    doc.close()
    return path


print("-- a real figure alongside body text --")
doc = fitz.open()
page = doc.new_page(width=PAGE_W, height=PAGE_H)
page.insert_text((50, 80), BODY, fontsize=BODY_SIZE)
page.insert_image(fitz.Rect(60, 200, 220, 320), pixmap=pixmap(200, 150, 90))
page.insert_text((50, 360), "Sekil 1: bir aciklama satiri.", fontsize=7)
page.insert_text((50, 420), BODY, fontsize=BODY_SIZE)
_r, figs, imgs, text = convert(write(doc, "auto_fig_basic.pdf"))
check("the figure is embedded", figs == 1)
check("exactly one image file is carried", imgs == 1)
check("body text above the figure survives", "gercek govde metnidir" in text)
# insert_text() does not wrap, so only the part that fits the page width is
# ever in the PDF — assert on a phrase that is actually rendered, and on it
# appearing once above the figure and once below it.
check("body text below the figure also survives", text.count("gercek govde metnidir") == 2)
check("the figure sits between the two paragraphs, in reading order",
      text.index("region-figure") > text.index("gercek govde metnidir")
      and text.rindex("gercek govde metnidir") > text.index("region-figure"))
check("the caption line is not swallowed", "Sekil 1" in text)

print("-- hairlines and icons are not figures --")
doc = fitz.open()
page = doc.new_page(width=PAGE_W, height=PAGE_H)
page.insert_text((50, 80), BODY, fontsize=BODY_SIZE)
page.insert_image(fitz.Rect(50, 200, 250, 206), pixmap=pixmap(600, 30, 40))   # 6pt tall rule
page.insert_image(fitz.Rect(50, 260, 58, 268), pixmap=pixmap(100, 100, 70))   # 8pt icon
_r, figs, imgs, text = convert(write(doc, "auto_fig_rules.pdf"))
check("no figure is emitted for a rule or an icon", figs == 0)
check("the page keeps its text", "gercek govde metnidir" in text)

print("-- an image repeating on every page is furniture, not a figure --")
doc = fitz.open()
for _ in range(6):
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    page.insert_text((50, 80), BODY, fontsize=BODY_SIZE)
    page.insert_image(fitz.Rect(60, 200, 200, 330), pixmap=pixmap(220, 200, 120))
_r, figs, imgs, text = convert(write(doc, "auto_fig_repeat.pdf"))
check("the repeated mark is refused on every page", figs == 0)

print("-- an image with prose inside it is a background panel, not a figure --")
doc = fitz.open()
page = doc.new_page(width=PAGE_W, height=PAGE_H)
page.insert_image(fitz.Rect(40, 150, 360, 450), pixmap=pixmap(400, 380, 200))
page.insert_textbox(fitz.Rect(60, 180, 340, 430), BODY + " " + BODY, fontsize=BODY_SIZE)
_r, figs, imgs, text = convert(write(doc, "auto_fig_panel.pdf"))
check("the panel is not embedded as a figure", figs == 0)
check("the prose printed over it is NOT suppressed", "gercek govde metnidir" in text)

print("-- a hand-drawn region wins over the detected one --")
doc = fitz.open()
page = doc.new_page(width=PAGE_W, height=PAGE_H)
page.insert_text((50, 80), BODY, fontsize=BODY_SIZE)
page.insert_image(fitz.Rect(60, 200, 220, 320), pixmap=pixmap(200, 150, 160))
path = write(doc, "auto_fig_manual.pdf")
_r, figs, imgs, text = convert(
    path, image_regions=[{"page_index": 0, "bbox": [50, 190, 230, 330]}]
)
check("the figure is embedded exactly once, not twice", figs == 1)
check("only one image file is carried", imgs == 1)

print("-- a page marked Görsel is shown as printed, and nothing is read off it --")
# The owner marks a designed page (title page, back cover) Görsel to see it
# exactly as printed; reading its words put a back-cover blurb into the last
# chapter.
doc = fitz.open()
page = doc.new_page(width=PAGE_W, height=PAGE_H)
page.insert_text((50, 80), "ARKA KAPAK YAZISI burada duruyor ve metne girmemeli.", fontsize=BODY_SIZE)
page.insert_image(fitz.Rect(60, 200, 340, 480), pixmap=pixmap(300, 280, 180))
page = doc.new_page(width=PAGE_W, height=PAGE_H)
page.insert_text((50, 80), BODY, fontsize=BODY_SIZE)
path = write(doc, "auto_fig_imagemode.pdf")
result, figs, imgs, text = convert(path, image_pages={0})
check("the marked page becomes a full-page image",
      any(ch.kind == "image" and ch.image_base64 for ch in result.chapters))
check("none of its words reach the text", "ARKA KAPAK" not in text)
check("the other page's text is still there", "gercek govde metnidir" in text)

print("-- a genuine plate with no prose stays a full-page image --")
doc = fitz.open()
page = doc.new_page(width=PAGE_W, height=PAGE_H)
page.insert_image(fitz.Rect(20, 20, 380, 580), pixmap=pixmap(360, 560, 210))
path = write(doc, "auto_fig_plate.pdf")
result, figs, imgs, text = convert(path, image_pages={0})
check("a wordless plate is still its own image chapter",
      any(ch.kind == "image" and ch.image_base64 for ch in result.chapters))

print("-- the feature can be switched off --")
_r, figs, imgs, text = convert(
    os.path.join(OUT_DIR, "auto_fig_basic.pdf"), auto_figures=False
)
check("no figure is detected when auto_figures is off", figs == 0)
check("the page still keeps all of its text", "gercek govde metnidir" in text)

if failures:
    print(f"\n{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("\nALL CHECKS PASSED")
