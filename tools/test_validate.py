"""The EPUB check (backend/app/validate.py) and the export it guards.

    python tools/test_validate.py

Exit code is 1 if anything fails.
"""
from __future__ import annotations

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

from app.builders.css_template import MATBAA_CSS  # noqa: E402
from app.builders.epub_builder import build_epub  # noqa: E402
from app.models import ChapterOut, Footnote  # noqa: E402
from app.validate import check_epub  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        failures.append(name)


tmp = tempfile.mkdtemp()

print("\nA book the builder writes is a valid EPUB")
linked = ('<p>Metin<sup class="footnote-ref" id="fnref_fn_ch_0001_1">'
          '<a epub:type="noteref" href="#fn_ch_0001_1">1</a></sup>.</p>')
good = build_epub(
    "Müşterek Mekan", "Stavros Stavrides",
    [ChapterOut(id="ch_0001", index=0, title="Giriş", html=linked,
                footnotes=[Footnote(id="fn_ch_0001_1", marker="1", text="Bağlı not."),
                           Footnote(id="fn_ch_0001_2", marker="2", text="Metinde atfı olmayan not.")])],
    MATBAA_CSS, os.path.join(tmp, "good.epub"), language="tr",
)
errors = [f for f in check_epub(good) if f.severity == "error"]
check("no errors, though one note has nothing in the text pointing to it", errors == [])
check("the stylesheet uses nothing a Kindle ignores",
      not [f for f in check_epub(good) if f.code == "kindle-css"])
check("it carries accessibility metadata", not [f for f in check_epub(good) if f.code == "a11y-metadata"])

print("\nA broken EPUB is caught")
bad = os.path.join(tmp, "bad.epub")
with zipfile.ZipFile(good) as src, zipfile.ZipFile(bad, "w", zipfile.ZIP_DEFLATED) as dst:
    for item in src.infolist():
        data = src.read(item.filename)
        if item.filename.endswith("ch_0001.xhtml"):
            data = data.replace(b'href="#fn_ch_0001_1"', b'href="#nereye"').replace(b"</body>", b"<p>kapanmayan</body>")
        dst.writestr(item.filename, data)          # mimetype compressed, too
codes = {f.code for f in check_epub(bad) if f.severity == "error"}
check("a compressed mimetype", "mimetype-stored" in codes)
check("malformed XHTML", "xhtml-malformed" in codes)

print("\nImages are named and declared by what they are")
import base64  # noqa: E402
import io  # noqa: E402

from PIL import Image  # noqa: E402

from app.models import ChapterImage  # noqa: E402

buf = io.BytesIO()
Image.new("RGB", (60, 90), "white").save(buf, "JPEG")
jpeg_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
pictured = build_epub(
    "Müşterek Mekan", "Stavros Stavrides",
    [ChapterOut(id="ch_0001", index=0, title="Görsel Sayfa 1", kind="image", image_base64=jpeg_b64, html=""),
     ChapterOut(id="ch_0002", index=1, title="Giriş",
                html='<p>Metin.</p><figure class="region-figure"><img src="images/ch_0002_img1.png" alt="Görsel"/></figure>',
                images=[ChapterImage(id="ch_0002_img1", base64=jpeg_b64)])],
    MATBAA_CSS, os.path.join(tmp, "pictured.epub"), language="tr",
)
with zipfile.ZipFile(pictured) as z:
    names = z.namelist()
    opf = z.read("EPUB/content.opf").decode("utf-8")
    body = z.read("EPUB/ch_0002.xhtml").decode("utf-8")
check("a JPEG page image is a .jpg declared image/jpeg",
      "EPUB/images/ch_0001.jpg" in names and 'href="images/ch_0001.jpg"' in opf and "image/png" not in opf)
check("an in-chapter JPEG figure is renamed, and the text points at the new name",
      "EPUB/images/ch_0002_img1.jpg" in names and 'src="images/ch_0002_img1.jpg"' in body)
check("and the book has no errors", not [f for f in check_epub(pictured) if f.severity == "error"])
mislabelled = os.path.join(tmp, "mislabelled.epub")
with zipfile.ZipFile(pictured) as src, zipfile.ZipFile(mislabelled, "w") as dst:
    for item in src.infolist():
        data = src.read(item.filename)
        if item.filename.endswith(".opf"):
            data = data.replace(b'media-type="image/jpeg"', b'media-type="image/png"')
        dst.writestr(item, data)
hidden_nav = os.path.join(tmp, "hidden_nav.epub")
with zipfile.ZipFile(pictured) as src, zipfile.ZipFile(hidden_nav, "w") as dst:
    for item in src.infolist():
        data = src.read(item.filename)
        if item.filename.endswith(".opf"):
            data = data.replace(b"<spine toc=\"ncx\">", b"<spine toc=\"ncx\"><itemref idref=\"nav\" linear=\"no\"/>")
        dst.writestr(item, data)
check("the builder keeps the generated nav out of the spine",
      'idref="nav"' not in opf)
check("a non-linear page nothing links to is an error (EPUBCheck OPF-096)",
      "spine-unreachable" in {f.code for f in check_epub(hidden_nav) if f.severity == "error"})
check("a JPEG declared as PNG is an error (Send to Kindle rejects the book)",
      "image-type" in {f.code for f in check_epub(mislabelled) if f.severity == "error"})

if failures:
    print(f"\n{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("\nALL CHECKS PASSED")
