"""Find Tesseract's language data and tell PyMuPDF where it is.

Kept in its own module, imported by `app/__init__.py`, because it has to
run before `import fitz` — see the note there. It imports nothing from the
rest of the app so the ordering stays obvious.
"""

from __future__ import annotations

import os
import shutil
from typing import Optional

# Where Tesseract keeps its language files, relative to the binary, and the
# places Windows/macOS/Linux installers put them when the binary is not on
# PATH at all.
_FALLBACK_DIRS = [
    r"C:\Program Files\Tesseract-OCR\tessdata",
    r"C:\Program Files (x86)\Tesseract-OCR\tessdata",
    "/usr/share/tesseract-ocr/5/tessdata",
    "/usr/share/tesseract-ocr/4.00/tessdata",
    "/usr/share/tessdata",
    "/opt/homebrew/share/tessdata",
    "/usr/local/share/tessdata",
]


def _looks_like_tessdata(path: str) -> bool:
    return bool(path) and os.path.isdir(path) and any(
        name.endswith(".traineddata") for name in os.listdir(path)
    )


def find_tessdata() -> Optional[str]:
    """The directory holding *.traineddata, or None if OCR can't work here."""
    env = os.environ.get("TESSDATA_PREFIX")
    if _looks_like_tessdata(env or ""):
        return env
    # TESSDATA_PREFIX is documented both ways — as the tessdata directory
    # itself and as its parent. Accept either.
    if env and _looks_like_tessdata(os.path.join(env, "tessdata")):
        return os.path.join(env, "tessdata")

    binary = shutil.which("tesseract")
    if binary:
        candidate = os.path.join(os.path.dirname(binary), "tessdata")
        if _looks_like_tessdata(candidate):
            return candidate

    for candidate in _FALLBACK_DIRS:
        if _looks_like_tessdata(candidate):
            return candidate
    return None


def configure_tessdata() -> Optional[str]:
    """Point TESSDATA_PREFIX at the language data, and return where it is."""
    found = find_tessdata()
    if found:
        os.environ["TESSDATA_PREFIX"] = found
    return found


def installed_languages() -> set:
    directory = find_tessdata()
    if not directory:
        return set()
    return {
        name[: -len(".traineddata")]
        for name in os.listdir(directory)
        if name.endswith(".traineddata")
    }
