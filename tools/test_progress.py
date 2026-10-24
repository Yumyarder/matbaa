"""Where a conversion is (convert_pdf_to_chapters(progress=…), the API).

    python tools/test_progress.py

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

import fitz  # noqa: E402

from app.parsers.pdf_parser import convert_pdf_to_chapters  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        failures.append(name)


work = tempfile.mkdtemp()
path = os.path.join(work, "kitap.pdf")
doc = fitz.open()
for k in range(25):
    page = doc.new_page(width=400, height=640)
    page.insert_textbox(fitz.Rect(40, 40, 360, 600), f"Bölüm metni, sayfa {k + 1}. " * 40, fontsize=10)
doc.save(path)

told = []
result = convert_pdf_to_chapters(path, progress=lambda stage, done, total: told.append((stage, done, total)))
stages = [s for s, _, _ in told]
check("the pages read, then the structure, then the paragraphs", stages.index("Sayfalar okunuyor")
      < stages.index("Kitabın yapısı çıkarılıyor") < stages.index("Paragraflar diziliyor"))
check("with pages done of the book's pages", ("Paragraflar diziliyor", 20, 25) in told
      and all(done <= total for _, done, total in told if total))
check("and the conversion itself unchanged by being watched",
      [c.title for c in result.chapters] == [c.title for c in convert_pdf_to_chapters(path).chapters])

from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402

client = TestClient(main.app)
check("nothing running for an upload: no stage", client.get("/api/convert/yok/progress").json()["stage"] is None)
main._tell_progress("u1", "Paragraflar diziliyor", 40, 300)
check("a running one says where it is", client.get("/api/convert/u1/progress").json()
      == {"stage": "Paragraflar diziliyor", "done": 40, "total": 300})
main._tell_progress("u1", None)
check("and is forgotten when done", client.get("/api/convert/u1/progress").json()["stage"] is None)

if failures:
    print(f"\n{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("\nALL CHECKS PASSED")
