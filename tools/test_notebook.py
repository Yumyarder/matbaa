"""Placing Kindle highlights in the book (backend/app/notebook.py).

    python tools/test_notebook.py

Exit code is 1 if anything fails.
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "backend"))

from app.clippings import read_books  # noqa: E402
from app.models import ChapterOut, Footnote  # noqa: E402
from app.notebook import best_project, place_book, same_book, tidy_quote  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        failures.append(name)


body1 = ("<p>Toplumsal formasyon var olmak için üretirken üretim koşullarını da yeniden üretmesi gerekir. "
         "Bu yeniden üretim süreci her gün yeniden kurulur.</p>"
         '<h2 class="subheading">Altyapı ve Üstyapı</h2>'
         "<p>Altyapı ya da ekonomik temel ile üstyapı arasındaki ilişki yeniden düşünülmelidir. "
         "Devletin ideolojik aygıtları burada devreye girer.</p>")
body2 = ("<p>İdeoloji katıksız rüya değildir; ideoloji maddi bir varoluşa sahiptir ve aygıtlarda yaşar.</p>"
         "<p>Okul, kilisenin yerini almıştır ve devletin ideolojik aygıtları arasında egemen olandır.</p>")
session = SimpleNamespace(book_title="İdeoloji ve Devletin İdeolojik Aygıtları", chapters=[
    ChapterOut(id="ch_0001", index=0, title="Üretim Koşullarının Yeniden Üretimi", html=body1,
               footnotes=[Footnote(id="fn1", marker="1", text="Marx, Kapital, cilt II.")]),
    ChapterOut(id="ch_0002", index=1, title="İdeoloji Üzerine", html=body2),
])

CLIPS = """İdeoloji ve Devletin İdeolojik Aygıtları (Louis Althusser)
- Your Highlight on page 10 | Location 100-102 | Added on Monday, January 26, 2026 10:00:00 PM

üretim koşullarını da yemden üretmesi gerekir.
==========
İdeoloji ve Devletin İdeolojik Aygıtları (Louis Althusser)
- Your Highlight on page 12 | Location 120-121 | Added on Monday, January 26, 2026 10:01:00 PM

Altyapı ya da ekonomik temel ile üstyapı arasındaki ilişki
==========
İdeoloji ve Devletin İdeolojik Aygıtları (Louis Althusser)
- Your Highlight on page 12 | Location 125-125 | Added on Monday, January 26, 2026 10:02:00 PM

ideolojik aygıtları
==========
İdeoloji ve Devletin İdeolojik Aygıtları (Louis Althusser)
- Your Highlight on page 14 | Location 140-141 | Added on Monday, January 26, 2026 10:03:00 PM

İdeoloji katıksız rüya değil- dir; ideoloji maddi bir varoluşa sahiptir
==========
İdeoloji ve Devletin İdeolojik Aygıtları (Louis Althusser)
- Your Highlight on page 15 | Location 150-151 | Added on Monday, January 26, 2026 10:04:00 PM

Bu kitapta hiç geçmeyen bambaşka bir cümle burada duruyor.
==========
"""
book = read_books(CLIPS)[0]
places = place_book(book, session)
by_text = {h.text[:20]: places[h.id] for h in book.highlights}

print("\nA highlight is found in its chapter and section")
p = by_text["Altyapı ya da ekonom"]
check("chapter, sub-heading and the whole paragraph are given",
      p is not None and p.chapter_id == "ch_0001" and p.subheading == "Altyapı ve Üstyapı"
      and p.paragraph.startswith("Altyapı ya da ekonomik temel"))
check("word for word it is an exact match", p.exact)

print("\nA scanner's misreading in the clipping")
p = by_text["üretim koşullarını d"]
check("the passage is still found", p is not None and p.chapter_id == "ch_0001")
check("and the book's spelling replaces the damaged word",
      p.quote_source == "kitap" and "yeniden üretmesi" in p.quote and "yemden" not in p.quote)

print("\nA word or two highlighted alone")
p = by_text["ideolojik aygıtları"]
check("is placed between the highlights around it, not at its first occurrence elsewhere",
      p is not None and p.chapter_id == "ch_0001" and "Devletin ideolojik aygıtları burada" in p.paragraph)

print("\nA line-end hyphen carried into the clipping")
p = by_text["İdeoloji katıksız rü"]
check("is joined again in the kept quote", p is not None and "değildir;" in p.quote and "değil- dir" not in p.quote)
check("tidy_quote leaves real dashes alone",
      tidy_quote("Marksizm-öncesi bir - iki") == "Marksizm-öncesi bir - iki"
      and tidy_quote("Althusser’- den önce bil- ginin") == "Althusser’den önce bilginin")

print("\nWhat is not in the book")
check("is left unplaced, never forced somewhere", by_text["Bu kitapta hiç geçmeye"[:20]] is None)

print("\nWhich saved book a Kindle title is")
check("a file-name-like Kindle title still names the book",
      same_book("georges-politzer-felsefenin-baslangic-ilkeleri", "Felsefenin Başlangıç İlkeleri") >= 0.8)
projects = [{"session_id": "a", "book_title": "Müşterek Mekan"},
            {"session_id": "b", "book_title": "İdeoloji ve Devletin İdeolojik Aygıtları"}]
check("the matching project is chosen", (best_project(book, projects) or {}).get("session_id") == "b")
check("and none when nothing is alike",
      best_project(read_books(CLIPS.replace("İdeoloji ve Devletin İdeolojik Aygıtları", "The Way of Kings"))[0],
                   projects) is None)

print("\nThe last reading session")
from app.notebook import last_session  # noqa: E402

session_info = last_session(book)
check("the latest day the book was marked, with what was marked",
      session_info == {"date": "2026-01-26", "highlights": 5, "notes": 0})

if failures:
    print(f"\n{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("\nALL CHECKS PASSED")
