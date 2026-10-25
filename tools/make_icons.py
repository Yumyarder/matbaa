"""Matbaa's icon (the seal, brand/muhur*.svg) in every place it is needed.

  backend/matbaa.ico            Matbaa.exe (Matbaa.spec): 16 to 256 px
  site/favicon.svg, .ico        the site's tab
  site/apple-touch-icon.png     a phone's home screen
  frontend/public/…             the same three for the app (desktop and browser)

Each size is drawn from the cut made for it: 16 px from muhur-16.svg, 24 and
32 from muhur-32.svg, larger from the 256 master — an icon has to change
below 48 px, not merely shrink.

    backend/.venv/Scripts/python tools/make_icons.py
"""
import io
import os
import shutil

import pymupdf
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRAND = os.path.join(ROOT, "brand")
PAPER = (243, 238, 227, 255)


def render(name: str, size: int) -> Image.Image:
    doc = pymupdf.open(os.path.join(BRAND, name))
    page = doc[0]
    zoom = size / page.rect.width
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=True)
    return Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGBA")


def cut(size: int) -> Image.Image:
    if size <= 16:
        return render("muhur-16.svg", size)
    if size <= 32:
        return render("muhur-32.svg", size)
    return render("muhur.svg", size)


def ico(path: str, sizes) -> None:
    images = [cut(s) for s in sizes]
    largest = images[-1]
    largest.save(path, format="ICO", sizes=[(s, s) for s in sizes], append_images=images[:-1])


def touch_icon(path: str) -> None:
    # iOS fills transparency with black and rounds the corners itself
    canvas = Image.new("RGBA", (180, 180), PAPER)
    seal = cut(148)
    canvas.alpha_composite(seal, (16, 16))
    canvas.convert("RGB").save(path, format="PNG")


def main() -> None:
    ico(os.path.join(ROOT, "backend", "matbaa.ico"), [16, 24, 32, 48, 64, 128, 256])
    for folder in (os.path.join(ROOT, "site"), os.path.join(ROOT, "frontend", "public")):
        os.makedirs(folder, exist_ok=True)
        # the 32 px cut scales best across a tab's 16 to 32 device pixels
        shutil.copyfile(os.path.join(BRAND, "muhur-32.svg"), os.path.join(folder, "favicon.svg"))
        ico(os.path.join(folder, "favicon.ico"), [16, 32, 48])
        touch_icon(os.path.join(folder, "apple-touch-icon.png"))
    print("icons written")


if __name__ == "__main__":
    main()
