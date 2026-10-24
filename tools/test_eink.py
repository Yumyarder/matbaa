"""Pictures readied for e-ink (backend/app/eink.py, the builder).

    python tools/test_eink.py

Exit code is 1 if anything fails.
"""
from __future__ import annotations

import base64
import io
import os
import sys
import tempfile
import zipfile

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "backend"))

from PIL import Image, ImageDraw  # noqa: E402

from app.builders.css_template import MATBAA_CSS  # noqa: E402
from app.builders.epub_builder import build_epub  # noqa: E402
from app.eink import prepare  # noqa: E402
from app.models import ChapterOut  # noqa: E402
from app.validate import check_epub  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        failures.append(name)


def jpeg(img: Image.Image) -> bytes:
    out = io.BytesIO()
    img.save(out, "JPEG", quality=92)
    return out.getvalue()


def scan(paper=(226, 214, 180)) -> Image.Image:
    """A page of type on yellowed paper."""
    img = Image.new("RGB", (400, 600), paper)
    d = ImageDraw.Draw(img)
    for y in range(60, 540, 18):
        d.rectangle([40, y, 360, y + 8], fill=(40, 34, 30))
    return img


print("\nA scan on yellowed paper")
out = prepare(jpeg(scan()))
img = Image.open(io.BytesIO(out)) if out else None
check("is made grey-scale", img is not None and img.mode == "L")
check("its paper white", img is not None and img.getpixel((20, 20)) >= 250)
check("its type still dark", img is not None and img.getpixel((200, 64)) <= 40)
png = io.BytesIO()
scan().save(png, "PNG")
out = prepare(png.getvalue())
check("a drawing given as PNG stays a PNG (sharp lines)", out is not None and Image.open(io.BytesIO(out)).format == "PNG")

print("\nLeft as they are")
cover = Image.new("RGB", (400, 600), (200, 20, 30))
ImageDraw.Draw(cover).rectangle([50, 200, 350, 260], fill=(250, 220, 0))
check("a picture in colour (a cover, a back cover)", prepare(jpeg(cover)) is None)
check("a scan already on white paper", prepare(jpeg(scan(paper=(255, 255, 255)))) is None)
check("something that is not a picture", prepare(b"not an image") is None)

print("\nIn the book")
page = base64.b64encode(jpeg(scan())).decode("ascii")
cover_b64 = base64.b64encode(jpeg(cover)).decode("ascii")
chapters = [ChapterOut(id="ch_0001", index=0, title="Görsel Sayfa 2", kind="image", html="", image_base64=page),
            ChapterOut(id="ch_0002", index=1, title="Giriş", html="<p>Metin.</p>")]
work = tempfile.mkdtemp()
path = os.path.join(work, "eink.epub")
build_epub(book_title="E", author="A", chapters=chapters, css=MATBAA_CSS, output_path=path, language="tr",
           cover_image_base64=cover_b64)
with zipfile.ZipFile(path) as z:
    plate = Image.open(io.BytesIO(z.read("EPUB/images/ch_0001.jpg")))
    cover_in_book = Image.open(io.BytesIO(z.read("EPUB/images/cover.jpg"))).convert("RGB")
check("a picture page is readied", plate.mode == "L" and plate.getpixel((20, 20)) >= 250)
check("the cover keeps its colour", cover_in_book.getpixel((20, 20))[0] > 150 and cover_in_book.getpixel((20, 20))[1] < 80)
check("the book is valid", not [f for f in check_epub(path) if f.severity == "error"])
path2 = os.path.join(work, "colour.epub")
build_epub(book_title="E", author="A", chapters=chapters, css=MATBAA_CSS, output_path=path2, language="tr",
           eink_images=False)
with zipfile.ZipFile(path2) as z:
    check("and it can be left off", Image.open(io.BytesIO(z.read("EPUB/images/ch_0001.jpg"))).mode == "RGB")

if failures:
    print(f"\n{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("\nALL CHECKS PASSED")
