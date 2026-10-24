"""Package init — runs before anything else under `app.` is imported.

PyMuPDF decides whether it has OCR support *at import time*, by reading
TESSDATA_PREFIX. A machine can have Tesseract installed and still fail with
"No OCR support: TESSDATA_PREFIX not set", because installers do not set
that variable. Pointing it at the installed language data here, before
`fitz` is imported anywhere, is what makes a scanned PDF readable at all.
"""

from app.ocr_env import configure_tessdata

configure_tessdata()
