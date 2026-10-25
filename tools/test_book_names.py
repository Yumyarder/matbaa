"""A book's title and author when the PDF hides them: a title page set in the
body size, a cover shown as a picture, and the file's own name
(backend/app/parsers/pdf_parser.py, backend/app/book_names.py).

    python tools/test_book_names.py

Exit code is 1 if anything fails.
"""
from __future__ import annotations

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

import pymupdf as fitz  # noqa: E402

from app.book_names import fill, from_filename  # noqa: E402
from app.parsers.pdf_parser import convert_pdf_to_chapters  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        failures.append(name)


print("\nThe file's own name")
check("Author - Title", from_filename("Stavros Stavrides - Müşterek Mekan.pdf") == ("Müşterek Mekan", "Stavros Stavrides"))
check("Title - Author", from_filename("Teori ve Pratik - Mao Zedung.pdf") == ("Teori ve Pratik", "Mao Zedung"))
check("initials, and a publisher in brackets left out",
      from_filename("V. İ. Lenin - Devlet ve Devrim (Yordam Kitap).pdf") == ("Devlet ve Devrim", "V. İ. Lenin"))
check("a download site's tags and number left out",
      from_filename("Atomik Alışkanlıklar (James Clear) (ornek-site.com, 2021).pdf")[0] == "Atomik Alışkanlıklar")
check("Turkish letters given back to a name typed without them",
      from_filename("butun-yazilar.pdf") == ("Bütün Yazılar", None))
check("capitals set as a title", from_filename("DEVLET VE İHTİLAL.pdf")[0] == "Devlet ve İhtilal")
check("an underscore standing for a colon", from_filename("Four Thousand Weeks _ Time Management - Oliver Burkeman.pdf")
      == ("Four Thousand Weeks: Time Management", "Oliver Burkeman"))
check("a name that is a code gives nothing",
      from_filename("Mir.az-00dc7b00-29da-41c7-ac39-0ee218b7cb51_Mir.az_.pdf") == (None, None))
check("only what the PDF did not give is taken",
      fill("Pür Dikkat", "Unknown", "Cal Newport - Derin Çalışma.pdf") == ("Pür Dikkat", "Cal Newport")
      and fill("Untitled Book", "Unknown", "x.pdf")[1] == "Unknown")

work = tempfile.mkdtemp()
BODY = ("The city is made of shared spaces and of the practices that open them to all who pass through, "
        "and every square holds the memory of an assembly. ")


def word_processor_book(path: str) -> None:
    """A title page in the body size under a running head naming author and title."""
    d = fitz.open()
    for n in range(1, 13):
        pg = d.new_page(width=420, height=595)
        pg.insert_text((60, 30), f"Ayse Yilmaz - Kentin Hafizasi {n}", fontsize=8)
        if n == 1:
            for k, line in enumerate(["Ayse Yilmaz", "Kentin Hafizasi", "Bir Deneme", "Yayinevi"]):
                pg.insert_text((60, 120 + 22 * k), line, fontsize=11)
        else:
            pg.insert_textbox(fitz.Rect(60, 60, 360, 540), BODY * 8, fontsize=11)
    d.save(path)
    d.close()


print("\nA title page set in the body size")
path = os.path.join(work, "word.pdf")
word_processor_book(path)
r = convert_pdf_to_chapters(path)
check("the running head names title and author", (r.detected_title, r.detected_author)
      == ("Kentin Hafizasi", "Ayse Yilmaz"))

print("\nA cover shown as a picture")
path = os.path.join(work, "scan.pdf")
d = fitz.open()
cover = d.new_page(width=420, height=595)
cover.insert_text((60, 200), "KENTIN HAFIZASI", fontsize=30)
cover.insert_text((60, 260), "Ayse Yilmaz", fontsize=16)
for n in range(2, 12):
    d.new_page(width=420, height=595).insert_textbox(fitz.Rect(60, 60, 360, 540), BODY * 8, fontsize=11)
d.save(path)
d.close()
r = convert_pdf_to_chapters(path, image_pages={0})
folded = r.detected_title.replace("ı", "i").replace("İ", "i").lower()
check("its text layer names the book", folded == "kentin hafizasi")
check("and the page is still a picture", r.chapters and any(c.kind == "image" for c in r.chapters))

print("\nIn the app: the file's name where the PDF says nothing")
from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402

path = os.path.join(work, "plain.pdf")
d = fitz.open()
for n in range(10):
    d.new_page(width=420, height=595).insert_textbox(fitz.Rect(60, 60, 360, 540), BODY * 8, fontsize=11)
d.save(path)
d.close()
client = TestClient(main.app)
with open(path, "rb") as fh:
    up = client.post("/api/upload", files={"file": ("Ayşe Yılmaz - Boş Sokaklar.pdf", fh, "application/pdf")}).json()
s = client.post(f"/api/convert/{up['upload_id']}", json={"excluded_pages": [], "image_pages": [], "toc_pages": []}).json()
check("title and author from the file's name", (s.get("book_title"), s.get("author")) == ("Boş Sokaklar", "Ayşe Yılmaz"))
check("and the name's note is cleared with the upload", not os.path.exists(main._upload_name_path(up["upload_id"])))

if failures:
    print(f"\n{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("\nALL CHECKS PASSED")
