"""The typeface embedded in the book (backend/app/fonts.py, the builder, the API).

    python tools/test_fonts.py

Exit code is 1 if anything fails.
"""
from __future__ import annotations

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
os.environ["MATBAA_PROJECTS"] = tempfile.mkdtemp()

from fontTools.ttLib import TTFont  # noqa: E402

from app import fonts  # noqa: E402
from app.builders.css_template import MATBAA_CSS  # noqa: E402
from app.builders.epub_builder import build_epub  # noqa: E402
from app.builders.themes import apply_theme  # noqa: E402
from app.models import ChapterOut  # noqa: E402
from app.validate import check_epub  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        failures.append(name)


print("\nThe faces, cut to the book's letters")
faces = fonts.faces("literata", "Kent hakkı: ŞEHİR, ığüşöç — “alıntı”")
check("four faces: regular, italic, bold, bold italic", [n for n, _ in faces] == [
    "Literata-Regular.ttf", "Literata-Italic.ttf", "Literata-Bold.ttf", "Literata-BoldItalic.ttf"])
full = os.path.getsize(os.path.join(fonts.FONT_DIR, "literata", "Literata-Regular.ttf"))
check("each a fraction of the whole face", all(len(data) < full / 4 for _, data in faces))
cmap = TTFont(io.BytesIO(faces[0][1])).getBestCmap()
check("every Turkish letter, the typesetting's marks and the soft hyphen kept",
      all(ord(c) in cmap for c in "çÇğĞıİöÖşŞüÜ“”‘’–—…") and 0xAD in cmap and 0xA0 in cmap)
check("an unknown family gives nothing", fonts.faces("comic", "x") == [] and fonts.font_css("comic") == "")

print("\nIn the book")
chapter = ChapterOut(id="ch_0001", index=0, title="Giriş",
                     html="<p>Şehir <em>italik</em> ve <strong>kalın</strong> yazılır.</p>")
work = tempfile.mkdtemp()


def built(css: str, font):
    out = os.path.join(work, f"b{len(os.listdir(work))}.epub")
    build_epub(book_title="Yazı", author="Yazar", chapters=[chapter], css=css, output_path=out,
               language="tr", font=font)
    with zipfile.ZipFile(out) as z:
        return out, z.read("EPUB/style/matbaa.css").decode("utf-8"), [n for n in z.namelist() if "/fonts/" in n], \
            z.read("EPUB/content.opf").decode("utf-8")


out, css, files, opf = built(MATBAA_CSS, "literata")
check("the faces are in the book, declared as fonts", len(files) == 4 and opf.count('media-type="font/ttf"') == 4)
check("the stylesheet names them before anything else", css.startswith("/* embedded faces")
      and 'src: url("../fonts/Literata-Italic.ttf")' in css)
check("and sets the text in them after the base, which names Bookerly",
      css.rindex('"Literata", "Bookerly"') > css.index('font-family: "Bookerly", "Georgia", "Palatino Linotype"'))
check("a valid book a Kindle reads", not [f for f in check_epub(out) if f.severity == "error" or f.code == "kindle-css"])
_, css, _, _ = built(apply_theme(MATBAA_CSS, "modern"), "literata")
check("a theme's own title face still wins (its block comes after)",
      css.index('"Literata", "Bookerly"') < css.index("/* matbaa-theme:modern */"))
_, css, files, _ = built(MATBAA_CSS, None)
check("no face asked for, none embedded", not files and "@font-face" not in css)

print("\nIn the app")
from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402
from app.models import ConversionSession  # noqa: E402
from app.session_store import save_session  # noqa: E402

client = TestClient(main.app)
listed = client.get("/api/fonts").json()
check("the app is told the faces, the reader's own first",
      [f["id"] for f in listed] == ["kindle", "literata"] and "@font-face" in listed[1]["faces_css"])
r = client.get("/api/fonts/literata/Literata-Regular.ttf")
check("the preview can fetch a face", r.status_code == 200 and r.headers.get("access-control-allow-origin") == "*")
check("and nothing else from there", client.get("/api/fonts/literata/..%2F..%2Fmain.py").status_code == 404)
save_session(ConversionSession(session_id="test-font", book_title="Yazı", author="Yazar", language="tr",
                               css=MATBAA_CSS, chapters=[chapter]))
check("a book is left to the Kindle's own fonts unless told otherwise",
      client.get("/api/session/test-font").json()["font"] == "kindle")
with zipfile.ZipFile(main._build_session_epub(main.get_session("test-font"))) as z:
    check("and nothing is embedded", not any("/fonts/" in n for n in z.namelist()))
r = client.put("/api/session/test-font/meta", json={"font": "literata"})
check("Literata chosen, it is kept", r.json()["font"] == "literata")
with zipfile.ZipFile(main._build_session_epub(main.get_session("test-font"))) as z:
    check("and its EPUB has the faces", any("/fonts/" in n for n in z.namelist()))
check("an unknown face is refused", client.put("/api/session/test-font/meta", json={"font": "comic"}).status_code == 400)

if failures:
    print(f"\n{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("\nALL CHECKS PASSED")
