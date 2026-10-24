"""
OCR helper for the PDF Editor's bounding-box tool (Step 3).

Requires TWO separate things, not just one pip install:
  1. `pip install pytesseract Pillow` — the Python wrapper (in requirements.txt)
  2. The Tesseract OCR *engine itself* — a native system binary pytesseract
     shells out to. This is NOT a pip package:
       - Windows: https://github.com/UB-Mannheim/tesseract/wiki
       - macOS:   brew install tesseract tesseract-lang
       - Linux:   apt install tesseract-ocr tesseract-ocr-tur
     Turkish text specifically needs the "tur" language data — without it,
     Tesseract falls back to English and Turkish letters (ı ğ ş ö ü ç İ)
     will come out wrong.

Honesty note: I could not verify this end-to-end myself. This sandbox has
no network access to install the Tesseract binary, so this is implemented
correctly against the documented pytesseract/PyMuPDF APIs but genuinely
untested — please confirm it actually works after installing Tesseract
locally, and tell me the exact error if it doesn't.
"""

from __future__ import annotations

from typing import List

import fitz

from app.parsers.pdf_parser import get_text_in_region

try:
    import pytesseract
    from PIL import Image

    OCR_LIBS_AVAILABLE = True
except ImportError:
    OCR_LIBS_AVAILABLE = False


class OcrUnavailable(Exception):
    """Raised when OCR can't run — missing libs, missing Tesseract binary,
    missing language data, or a bad bbox. The message is written to be
    shown directly to the person, not just logged."""


def ocr_region(pdf_path: str, page_index: int, bbox: List[float], lang: str = "tur") -> dict:
    if not OCR_LIBS_AVAILABLE:
        raise OcrUnavailable(
            "OCR kütüphaneleri kurulu değil. Backend'de şunu çalıştırın: "
            "pip install pytesseract Pillow"
        )

    doc = fitz.open(pdf_path)
    try:
        if page_index < 0 or page_index >= doc.page_count:
            raise OcrUnavailable("Sayfa bulunamadı.")

        page = doc[page_index]
        if len(bbox) != 4:
            raise OcrUnavailable("Geçersiz seçim alanı (bbox 4 sayı içermeli).")
        x0, y0, x1, y1 = bbox
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        if x1 - x0 < 2 or y1 - y0 < 2:
            raise OcrUnavailable("Seçilen alan çok küçük — biraz daha büyük bir bölge çizin.")

        clip = fitz.Rect(x0, y0, x1, y1) & page.rect
        if clip.is_empty:
            raise OcrUnavailable("Seçilen alan sayfa sınırlarının dışında.")

        # High-resolution render — OCR accuracy improves a lot with more
        # pixels per character. 4x zoom ≈ 288 DPI for a 72-DPI-native PDF.
        matrix = fitz.Matrix(4.0, 4.0)
        pix = page.get_pixmap(matrix=matrix, clip=clip, colorspace=fitz.csRGB)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

        try:
            text = pytesseract.image_to_string(img, lang=lang).strip()
            # A second pass just for confidence — image_to_string doesn't
            # expose per-word scores, image_to_data doesn't preserve line
            # breaks as cleanly, so we use each for what it's good at.
            # Tesseract's own confidence is 0-100 per word (-1 for
            # non-text boxes, excluded here); industry-common practice is
            # to treat sub-~70 as "verify this by hand" rather than trust
            # it outright.
            data = pytesseract.image_to_data(img, lang=lang, output_type=pytesseract.Output.DICT)
            confidences = [
                int(c) for w, c in zip(data.get("text", []), data.get("conf", []))
                if w.strip() and str(c).lstrip("-").isdigit() and int(c) >= 0
            ]
            confidence = round(sum(confidences) / len(confidences)) if confidences else None
        except Exception as exc:  # noqa: BLE001 — pytesseract raises different
            # exception types depending on exactly what's missing (the binary
            # itself, the language data file, a bad PATH, ...); catching
            # broadly here and surfacing the real message is more useful
            # than guessing which specific exception class applies.
            raise OcrUnavailable(
                "Tesseract OCR çalıştırılamadı. Sistem PATH'inde Tesseract kurulu "
                f"ve '{lang}' dil paketi yüklü mü? Orijinal hata: {exc}"
            ) from exc

        # What extraction already produces here, shown next to the OCR
        # candidate so the person can judge whether OCR actually improves
        # on it — OCR must never silently override this; approving one
        # over the other is the person's call, made in the review step.
        source_text = get_text_in_region(pdf_path, page_index, bbox)
        return {"text": text, "confidence": confidence, "source_text": source_text}
    finally:
        doc.close()
