"""A PDF its publisher closed to copying, or locked with a password, is not
converted (backend/app/copy_control.py): not by the app's upload, not by
the batch converter, and its words do not go into the dictionary.

    python tools/test_copy_control.py

The PDFs are made here. Exit code is 1 if anything fails.
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
from fastapi.testclient import TestClient  # noqa: E402

from app import copy_control, dictionary_build, main, pipeline  # noqa: E402

failures: list[str] = []
scratch = tempfile.mkdtemp()


def check(name: str, cond: bool) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        failures.append(name)


def book(name: str, **save) -> str:
    path = os.path.join(scratch, name)
    doc = fitz.open()
    for n in range(2):
        doc.new_page().insert_text((72, 100), f"Kitabın {n + 1}. sayfası: kelimeler, cümleler.")
    doc.save(path, **save)
    return path


READ_ONLY = fitz.PDF_PERM_PRINT | fitz.PDF_PERM_ACCESSIBILITY
plain = book("acik.pdf")
# what seven of the reader's library books are: an owner password whose flags still allow copying
copy_allowed = book("izinli.pdf", encryption=fitz.PDF_ENCRYPT_RC4_40, owner_pw="yayinci",
                    permissions=READ_ONLY | fitz.PDF_PERM_COPY)
copy_closed = book("kapali.pdf", encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="yayinci", permissions=READ_ONLY)
password = book("parolali.pdf", encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="yayinci", user_pw="okur")

print("Which PDFs are refused")
check("a plain PDF is converted", copy_control.refusal(plain) is None)
check("an owner password that still allows copying is no reason to refuse", copy_control.refusal(copy_allowed) is None)
check("a PDF whose publisher switched copying off is refused", copy_control.refusal(copy_closed) == copy_control.COPY_CLOSED)
check("a PDF that asks for a password to open is refused", copy_control.refusal(password) == copy_control.LOCKED)
check("a file that is not a PDF is left to the readers that say so",
      copy_control.refusal(os.path.join(scratch, "yok.pdf")) is None)

print("\nThe app's upload")
client = TestClient(main.app)
before = set(os.listdir(main.TEMP_DIR))
with open(copy_closed, "rb") as f:
    r = client.post("/api/upload", files={"file": ("kapali.pdf", f.read(), "application/pdf")})
check("the upload is refused with the reason, in Turkish",
      r.status_code == 422 and r.json().get("detail") == copy_control.COPY_CLOSED)
check("and nothing of it is kept", not {n for n in set(os.listdir(main.TEMP_DIR)) - before if n.startswith("upload_")})
with open(password, "rb") as f:
    r = client.post("/api/upload", files={"file": ("parolali.pdf", f.read(), "application/pdf")})
check("a password-locked upload is refused", r.status_code == 422 and r.json().get("detail") == copy_control.LOCKED)
with open(copy_allowed, "rb") as f:
    r = client.post("/api/upload", files={"file": ("izinli.pdf", f.read(), "application/pdf")})
check("a PDF that allows copying uploads as before", r.status_code == 200 and r.json().get("page_count") == 2)

print("\nThe batch converter")
try:
    pipeline.convert_file(copy_closed, os.path.join(scratch, "kapali.epub"), scratch, use_ocr=False, log=lambda _m: None)
    refused = False
except copy_control.CopyControlled as exc:
    refused = str(exc) == copy_control.COPY_CLOSED
check("a PDF closed to copying is not converted", refused)
check("and no EPUB is written", not os.path.exists(os.path.join(scratch, "kapali.epub")))

print("\nThe dictionary")
check("a book closed to copying adds no word forms", not dictionary_build._pdf_words(copy_closed))
check("an open book still does", dictionary_build._pdf_words(plain)["kelimeler"] == 2)

if failures:
    print(f"\n{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("\nALL CHECKS PASSED")
