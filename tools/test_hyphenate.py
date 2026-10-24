"""Soft hyphens at Turkish syllable breaks (backend/app/hyphenate.py).

    python tools/test_hyphenate.py

Exit code is 1 if anything fails.
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
sys.path.insert(0, os.path.join(REPO_ROOT, "backend"))

from app.hyphenate import SHY, hyphenate_html, hyphenate_text, hyphenate_word  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        failures.append(name)


def shown(word: str) -> str:
    return hyphenate_word(word).replace(SHY, "-")


print("\nSyllables")
check("one consonant goes with the next vowel", shown("kapitalizmin") == "ka-pi-ta-liz-min")
check("two consonants divide", shown("toplumsal") == "top-lum-sal")
check("three consonants keep two before the break", shown("Türkçesi") == "Türk-çe-si")
check("two vowels side by side divide", shown("saatler") == "sa-at-ler")
check("Turkish letters count as letters", shown("müşterekleşme") == "müş-te-rek-leş-me")
check("no break leaves one letter alone", shown("ideolojik") == "ide-o-lo-jik")

print("\nLeft whole")
check("a short word", hyphenate_word("kitap") == "kitap")
check("a word in capitals (an abbreviation or a heading)", hyphenate_word("İNSANLIK") == "İNSANLIK")
check("a word already carrying soft hyphens", hyphenate_word("ka" + SHY + "pita") == "ka" + SHY + "pita")
check("a web address", hyphenate_text("bkz. http://example.org/kapitalizmin") == "bkz. http://example.org/kapitalizmin")
check("a number with a suffix", hyphenate_text("1980'lerde") == "1980'lerde")
check("a word spelt the way Turkish does not spell", all(hyphenate_word(w) == w for w in
      ("Bloomsbury", "Street", "Navarinou", "Heidegger", "Nietzsche", "Kowalski", "Matthews")))
check("a Turkish word next to them still is", shown("kapitalizmin") == "ka-pi-ta-liz-min")

print("\nA paragraph in English")
english = "<p>Code of the Street: Decency, Violence and the Moral Life of the Inner City</p>"
check("is left whole", hyphenate_html(english) == english)
turkish = "<p>Anderson'un Code of the Street kitabı toplumsal şiddeti anlatır ve bir klasiktir</p>"
check("an English title inside Turkish prose does not stop the Turkish words",
      "top" + SHY + "lum" + SHY + "sal" in hyphenate_html(turkish))

print("\nHTML: text nodes only")
out = hyphenate_html('<p class="toplumsal"><a href="#kapitalizmin">toplumsal</a> &amp; kentsel</p>')
check("tags and attributes are untouched", '<p class="toplumsal"><a href="#kapitalizmin">' in out)
check("text inside a link is hyphenated", ">top" + SHY + "lum" + SHY + "sal</a>" in out)
check("an ampersand stays escaped", "&amp; kent" + SHY + "sel" in out)
check("a heading is set whole", hyphenate_html("<h2>Toplumsal <em>Kapitalizm</em></h2><p>toplumsal</p>") ==
      "<h2>Toplumsal <em>Kapitalizm</em></h2><p>top" + SHY + "lum" + SHY + "sal</p>")
check("the visible text is unchanged once soft hyphens are removed",
      out.replace(SHY, "") == '<p class="toplumsal"><a href="#kapitalizmin">toplumsal</a> &amp; kentsel</p>')

if failures:
    print(f"\n{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("\nALL CHECKS PASSED")
