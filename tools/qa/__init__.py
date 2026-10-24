"""Matbaa QA harness.

A small, dependency-free regression harness that drives the REAL conversion
pipeline (the same functions the FastAPI app calls) over a fixed corpus of
books and measures the result *semantically* — chapter boundaries, paragraph
continuity, footnote organisation, navigation, and above all whether the
book's actual text survived the trip.

Deliberately NOT a golden-file differ. Two of the three corpus books have a
historical EPUB that was hand-corrected after Matbaa produced it, so a
byte-level or text-level diff would flag the human's own fixes as
regressions. Everything here compares structure and measurable quality
counters instead, and treats small typographic differences as information
for a person to judge rather than as failures.

Run it with:  python tools/run_qa.py
"""
