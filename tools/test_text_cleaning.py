"""Regression coverage for backend/app/utils/text_cleaning.py.

    python tools/test_text_cleaning.py

Pure unit tests, no PDF/EPUB machinery involved — fast enough to run on
every change to this module. Exit code is 1 if anything fails.
"""
from __future__ import annotations

import os
import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if os.path.join(REPO_ROOT, "backend") not in sys.path:
    sys.path.insert(0, os.path.join(REPO_ROOT, "backend"))

from app.utils.text_cleaning import clean_text, fix_broken_bracket_glyphs  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        failures.append(name)


print("-- fix_broken_bracket_glyphs: real corruption found in Tenin Gözleri --")
check(
    "opening-paren-as-< before a place name is repaired",
    fix_broken_bracket_glyphs("University of California Press <Berkeley ve Los Angelesl, 1993")
    .startswith("University of California Press (Berkeley"),
)
check(
    "opening-paren-as-< is repaired even where the matching close is a"
    " different broken glyph ('l') that isn't safe to auto-fix",
    fix_broken_bracket_glyphs("<Seattlel, 1993") == "(Seattlel, 1993",
)
check(
    "closing-paren-as-> is repaired",
    fix_broken_bracket_glyphs('(haz.>,') == "(haz.),",
)
check(
    "a year in broken parens is repaired",
    fix_broken_bracket_glyphs("Kearney <1994), s. 12") == "Kearney (1994), s. 12",
)

print("-- fix_broken_bracket_glyphs: must not touch real usage --")
check(
    "a lone < with nothing attached (end of string) is left alone",
    fix_broken_bracket_glyphs("bir sonuç <") == "bir sonuç <",
)
check(
    "a spaced-out comparison is left alone",
    fix_broken_bracket_glyphs("n < 5 ve m > 2") == "n < 5 ve m > 2",
)
check(
    "already-correct parentheses are untouched",
    fix_broken_bracket_glyphs("(Berkeley), 1994") == "(Berkeley), 1994",
)

print("-- clean_text: the repair runs as part of normal body-text cleanup --")
check(
    "clean_text repairs a broken citation inline",
    "<Berkeley ve Los Angelesl" not in clean_text("University of California Press <Berkeley ve Los Angelesl, 1993")
    and "(Berkeley ve Los Angeles" in clean_text("University of California Press <Berkeley ve Los Angelesl, 1993"),
)

# --- a scanner's misreadings, corrected from the book's own words ----------
from app.utils.vocab_repair import build_vocabulary, repair_text  # noqa: E402

_words = build_vocabulary(["Bookchin'in komünalizm üzerine yazdıkları. Deleuze ve Foucault. Bilim insanları."])
check("a bibliography entry's lost initial comes back from the book's own spelling",
      repair_text('<p class="page-aside">ookchin, M. (2007) Social Ecology</p>', _words)
      == '<p class="page-aside">Bookchin, M. (2007) Social Ecology</p>')
check("so does an initial read as another glyph",
      repair_text("<p>ıeleuze, G. (1988) Foucault</p>", _words) == "<p>Deleuze, G. (1988) Foucault</p>")
check("a paragraph that merely starts in lower case is left alone",
      repair_text("<p>ilim adamları geldi</p>", _words) == "<p>ilim adamları geldi</p>")
check("a year read as letters is read as digits, the twenties are not",
      repair_text("<p>Bu 20ll&#x27;den beri, 20lı yıllarda</p>", _words) == "<p>Bu 2011&#x27;den beri, 20lı yıllarda</p>")

if failures:
    print(f"\n{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("\nALL CHECKS PASSED")
