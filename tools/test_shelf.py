"""The shelf on the start screen (GET /api/projects, the covers).

    python tools/test_shelf.py

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
os.environ["MATBAA_NOTEBOOK"] = tempfile.mkdtemp()

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app import main, notebook, vocab  # noqa: E402
from app.builders.css_template import MATBAA_CSS  # noqa: E402
from app.clippings import parse_any  # noqa: E402
from app.models import ChapterOut, ConversionSession  # noqa: E402
from app.session_store import save_session  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        failures.append(name)


def jpeg(w: int, h: int) -> str:
    out = io.BytesIO()
    Image.new("RGB", (w, h), (150, 40, 40)).save(out, "JPEG")
    return base64.b64encode(out.getvalue()).decode("ascii")


chapters = [ChapterOut(id="ch_0001", index=0, title="Giriş", html="<p>Metin.</p>")]
save_session(ConversionSession(session_id="kapakli", book_title="Müşterek Mekan", author="Stavros Stavrides",
                               language="tr", chapters=chapters, css=MATBAA_CSS, cover_image_base64=jpeg(1600, 2400)))
save_session(ConversionSession(session_id="kapaksiz", book_title="Devlet ve Devrim", author="Lenin", language="tr",
                               chapters=chapters, css=MATBAA_CSS))
clips = ("Müşterek Mekan (Stavros Stavrides)\n- Your Highlight on page 4 | Location 40-41 | Added on Sunday, 18 October "
         "2026 11:00:00\n\nKentin ortak alanları.\n==========\n"
         "Müşterek Mekan (Stavros Stavrides)\n- Your Highlight on page 5 | Location 50-51 | Added on Sunday, 18 October "
         "2026 11:05:00\n\nBir başka vurgu.\n==========\n")
notebook.import_clips(parse_any(clips.encode("utf-8")))
vocab.import_lookups([vocab.Lookup("w-1", "müştereklerin", "müştereklerin", "tr", "…", "Müşterek Mekan", "", "2026-10-18", False)])

client = TestClient(main.app)
books = {p["session_id"]: p for p in client.get("/api/projects").json()}
check("each book with whether it has a cover", books["kapakli"]["has_cover"] and not books["kapaksiz"]["has_cover"])
check("and what the reader marked in it on the Kindle", books["kapakli"]["highlights"] == 2
      and books["kapakli"]["words"] == 1 and books["kapaksiz"]["highlights"] == 0)
r = client.get("/api/projects/kapakli/cover.jpg")
img = Image.open(io.BytesIO(r.content)) if r.status_code == 200 else None
check("the cover, small enough for a shelf", img is not None and img.format == "JPEG" and img.size[1] <= 360
      and img.size[0] <= 240)
check("a book without a cover has none to give", client.get("/api/projects/kapaksiz/cover.jpg").status_code == 404)

if failures:
    print(f"\n{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("\nALL CHECKS PASSED")
