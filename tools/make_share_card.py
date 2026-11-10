"""The site's share card: the picture a chat or social app shows under a
shared link (og:image), 1200x630. It is set as a page from the site's own
parts (brand/kart.html: the site's stylesheet, its Garamond, its red block
and cloth-bound books) and photographed by the computer's Edge, headless.

    backend/.venv/Scripts/python tools/make_share_card.py [brand/kart.html] [site/kart.png]

Shot at twice the size and brought down, so the hairlines stay crisp; kept
under 300 KB, above which WhatsApp is known to drop a preview.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
WIDTH, HEIGHT, SCALE = 1200, 630, 2
LIMIT = 300 * 1024
BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
]


def browser() -> str:
    for path in BROWSERS + [shutil.which("msedge") or "", shutil.which("chrome") or ""]:
        if path and os.path.exists(path):
            return path
    raise SystemExit("Edge or Chrome is needed to photograph the card")


def shoot(page: Path, shot: Path) -> Image.Image:
    # The window is larger than the card (a headless window keeps a margin of
    # its own); the card sits at the page's top left and is cut out after.
    with tempfile.TemporaryDirectory() as profile:
        subprocess.run([browser(), "--headless", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                        f"--user-data-dir={profile}", f"--force-device-scale-factor={SCALE}",
                        f"--window-size={WIDTH + 200},{HEIGHT + 200}", "--virtual-time-budget=4000",
                        f"--screenshot={shot}", page.as_uri()],
                       check=True, timeout=180, capture_output=True)
    image = Image.open(shot)
    if image.width < WIDTH * SCALE or image.height < HEIGHT * SCALE:
        raise SystemExit(f"the shot is {image.size}, smaller than the card")
    return image.crop((0, 0, WIDTH * SCALE, HEIGHT * SCALE)).resize((WIDTH, HEIGHT), Image.LANCZOS).convert("RGB")


def save(card: Image.Image, out: Path) -> None:
    card.save(out, optimize=True)
    if out.stat().st_size > LIMIT:
        # the card is drawn in a few flat colours; a palette loses nothing seen
        card.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.FLOYDSTEINBERG) \
            .save(out, optimize=True)
    if out.stat().st_size > LIMIT:
        raise SystemExit(f"{out} is {out.stat().st_size // 1024} KB, over {LIMIT // 1024} KB")


def main() -> None:
    page = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "brand" / "kart.html"
    out = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else ROOT / "site" / "kart.png"
    with tempfile.TemporaryDirectory() as tmp:
        card = shoot(page, Path(tmp) / "shot.png")
    save(card, out)
    print(f"{out}: {card.width}x{card.height}, {out.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
