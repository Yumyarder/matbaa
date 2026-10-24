"""OCR a share of a book's pages in a process of its own.

    python -m app.ocr_worker <src.pdf> <out_dir> <lang> <tessdata> <page,page,...>

Writes one searchable single-page PDF per page as <out_dir>/<page>.pdf.
ocr_layer.build_searchable_copy runs several of these side by side and
assembles the result; a separate process per share is what lets the pages
be read in parallel, and it keeps a Tesseract crash from taking the app
down with it.
"""
from __future__ import annotations

import os
import sys

# Tesseract would otherwise start a thread per core in every worker.
os.environ.setdefault("OMP_THREAD_LIMIT", "1")


def ocr_page_pdf(page, lang: str, tessdata: str, zoom: float, dpi: int) -> bytes:
    import fitz

    pix = page.get_pixmap(
        matrix=fitz.Matrix(zoom, zoom),
        colorspace=fitz.csRGB,  # pdfocr silently returns no text for greyscale
    )
    pix.set_dpi(dpi, dpi)  # keeps the page its printed size
    # The directory is passed explicitly rather than left to TESSDATA_PREFIX:
    # PyMuPDF reads that variable when it is imported, so whether OCR worked
    # would otherwise depend on which module happened to be imported first.
    return pix.pdfocr_tobytes(language=lang, tessdata=tessdata)


def main(argv) -> int:
    import fitz

    from app.ocr_layer import OCR_DPI, OCR_RENDER_ZOOM

    src, out_dir, lang, tessdata, pages = argv
    doc = fitz.open(src)
    try:
        for number in (int(p) for p in pages.split(",") if p):
            data = ocr_page_pdf(doc[number], lang, tessdata, OCR_RENDER_ZOOM, OCR_DPI)
            partial = os.path.join(out_dir, f"{number}.part")
            with open(partial, "wb") as f:
                f.write(data)
            os.replace(partial, os.path.join(out_dir, f"{number}.pdf"))
    finally:
        doc.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
