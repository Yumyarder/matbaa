"""The book's cover: the PDF's own, cleaned, or one set in type (backend/app/cover.py).

    python tools/test_cover.py

Exit code is 1 if anything fails.
"""
from __future__ import annotations

import base64
import io
import os
import sys
import tempfile

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "backend"))
os.environ["MATBAA_PROJECTS"] = tempfile.mkdtemp()

from PIL import Image, ImageDraw  # noqa: E402

from app import cover  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        failures.append(name)


def jpeg(img: Image.Image) -> bytes:
    out = io.BytesIO()
    img.save(out, "JPEG", quality=95)
    return out.getvalue()


def picture(w=600, h=900, fill=(40, 90, 140)) -> Image.Image:
    img = Image.new("RGB", (w, h), fill)
    d = ImageDraw.Draw(img)
    d.rectangle([60, 120, w - 60, 300], fill=(230, 210, 120))
    d.ellipse([150, 400, w - 150, h - 150], fill=(200, 60, 50))
    return img


print("\nThe PDF's cover, cleaned")
page = Image.new("RGB", (700, 1000), (255, 255, 255))
page.paste(picture(), (50, 50))                       # white margins round the picture
out = Image.open(io.BytesIO(cover.clean(jpeg(page))))
check("blank margins are trimmed", abs(out.width - 600) <= 6 and abs(out.height - 900) <= 6)
scan = Image.new("RGB", (640, 960), (12, 12, 12))      # a scanner's dark edges
scan.paste(picture(), (20, 30))
out = Image.open(io.BytesIO(cover.clean(jpeg(scan))))
check("a scanner's dark edges are trimmed", abs(out.width - 600) <= 6 and abs(out.height - 900) <= 6)
whole = picture()
out = Image.open(io.BytesIO(cover.clean(jpeg(whole))))
check("a picture without margins is left whole", out.size == whole.size)
black = picture(fill=(5, 5, 5))                        # a black cover: its dark is the design
out = Image.open(io.BytesIO(cover.clean(jpeg(black))))
check("a black cover is not cut into", out.size[0] >= 0.95 * 600 and out.size[1] >= 0.95 * 900)
white_design = Image.new("RGB", (600, 900), (255, 255, 255))
ImageDraw.Draw(white_design).rectangle([0, 600, 599, 899], fill=(180, 30, 30))   # white to the top, colour below
out = Image.open(io.BytesIO(cover.clean(jpeg(white_design))))
check("a white cover that is white to an edge stays as it is", out.size == white_design.size)
flat = picture(fill=(220, 0, 30))                      # a flat red cover keeps its red
out = Image.open(io.BytesIO(cover.clean(jpeg(flat)))).convert("RGB")
r, g, b = out.getpixel((10, 10))
check("a colour is never changed", r > 180 and g < 50 and b < 80)
check("an unreadable cover is kept as it was", cover.clean_base64("bm90IGFuIGltYWdl") == "bm90IGFuIGltYWdl")

print("\nA cover set in type")
img = Image.open(io.BytesIO(cover.typographic("Müşterek Mekan: Müşterekler Olarak Şehir", "Stavros Stavrides")))
check("Kindle's size, a JPEG", img.size == cover.COVER_SIZE and img.format == "JPEG")
check("ink on a pale ground", img.convert("L").getextrema()[0] < 60 and img.getpixel((800, 1900))[0] > 200)
long_title = " ".join(["Uzunca"] * 40)
img = Image.open(io.BytesIO(cover.typographic(long_title, "")))
check("a very long title still makes a cover", img.size == cover.COVER_SIZE)

print("\nChoosing the cover in the app")
from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402
from app.builders.css_template import MATBAA_CSS  # noqa: E402
from app.models import ChapterOut, ConversionSession  # noqa: E402
from app.session_store import save_session  # noqa: E402
from app.validate import check_epub  # noqa: E402

pdf_cover = base64.b64encode(jpeg(picture())).decode("ascii")
save_session(ConversionSession(
    session_id="test-cover", book_title="Kent Hakkı", author="Henri Lefebvre", language="tr", css=MATBAA_CSS,
    chapters=[ChapterOut(id="ch_0001", index=0, title="Giriş", html="<p>Metin.</p>")],
    cover_image_base64=pdf_cover))
client = TestClient(main.app)
s = client.post("/api/session/test-cover/cover", json={"kind": "matbaa"}).json()
check("a cover set in type replaces the PDF's", s["cover_kind"] == "matbaa"
      and s["cover_image_base64"] != pdf_cover and s["pdf_cover_base64"] == pdf_cover)
before = s["cover_image_base64"]
s = client.put("/api/session/test-cover/meta", json={"book_title": "Şehir Hakkı"}).json()
check("it follows a corrected title", s["cover_image_base64"] != before)
epub = main._build_session_epub(main.get_session("test-cover"))
check("the book with it is valid", not [f for f in check_epub(epub) if f.severity == "error"])
s = client.post("/api/session/test-cover/cover", json={"kind": "pdf"}).json()
check("the PDF's own comes back as it was", s["cover_kind"] == "pdf" and s["cover_image_base64"] == pdf_cover
      and s["pdf_cover_base64"] is None)
check("an unknown kind is refused", client.post("/api/session/test-cover/cover", json={"kind": "x"}).status_code == 400)

if failures:
    print(f"\n{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("\nALL CHECKS PASSED")
