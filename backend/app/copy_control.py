"""A PDF its publisher has closed to copying is not converted.

A PDF can carry permission flags under an owner password: it opens for
reading, but copying its text out is switched off. PyMuPDF reads the text
regardless, so Matbaa honours the flag itself: a converter that ignored it
would be a tool for getting round a copy-control measure, which Turkish
copyright law forbids making or distributing (FSEK md. 72). A PDF that
asks for a password to open at all is refused too; Matbaa takes none.
OCR is no way round it either, so the check comes before anything else
reads the file.
"""
from __future__ import annotations

import pymupdf as fitz

COPY_CLOSED = ("Bu PDF'in yayıncısı metnin kopyalanmasını kapatmış. Matbaa bu kısıtlamayı aşmaz; "
               "kitabı dönüştüremez.")
LOCKED = "Bu PDF açılmak için parola istiyor. Matbaa parolalı PDF'leri açmaz."


class CopyControlled(Exception):
    """A PDF closed to copying, or locked with a password."""


def refusal(pdf_path: str) -> str | None:
    """Why this PDF must not be converted, or None when it may be. A file
    that does not open at all is left to the readers that report that."""
    try:
        doc = fitz.open(pdf_path)
    except Exception:  # noqa: BLE001
        return None
    with doc:
        if doc.needs_pass:
            return LOCKED
        if not doc.permissions & fitz.PDF_PERM_COPY:
            return COPY_CLOSED
    return None


def check(pdf_path: str) -> None:
    reason = refusal(pdf_path)
    if reason:
        raise CopyControlled(reason)
