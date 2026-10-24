"""Reading back what was marked on the Kindle (backend/app/clippings.py).

    python tools/test_clippings.py

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

from app.clippings import block_id, fold, read_books  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        failures.append(name)


MY_CLIPPINGS = "﻿" + """Müşterek Mekan (Stavros Stavrides)
- Your Highlight on page 35 | Location 512-514 | Added on Saturday, 17 October 2026 20:21:03

Toplumsal ya da kentsel düzen, erişilmiş bir durum değil
==========
Müşterek Mekan (Stavros Stavrides)
- Your Highlight on page 35 | Location 512-516 | Added on Saturday, 17 October 2026 20:21:40

Toplumsal ya da kentsel düzen, erişilmiş bir durum değil bir projedir.
==========
Müşterek Mekan (Stavros Stavrides)
- Your Note on page 35 | Location 516 | Added on Saturday, 17 October 2026 20:22:10

Cok hos, proje fikri onemli
==========
Müşterek Mekan (Stavros Stavrides)
- Your Bookmark on page 40 | Location 600 | Added on Saturday, 17 October 2026 20:30:00


==========
Müşterek Mekan (Stavros Stavrides)
- Your Highlight on Location 700-01 | Added on Saturday, 17 October 2026 21:00:00

"Gigantomanya"
==========
İdeoloji ve Devletin İdeolojik Aygıtları (Kitap (1)) (Louis Althusser)
- Your Highlight at location 88-90 | Added on Sunday, 18 October 2026 10:00:00

İdeoloji katıksız rüya
==========
Müşterek Mekan (Stavros Stavrides)
- Your Note on Location 701 | Added on Saturday, 17 October 2026 21:00:30

Bu ne demek? Yapay zekaya sor
==========
"""

print("\nMy Clippings.txt, as the Kindle writes it")
books = {b.title: b for b in read_books(MY_CLIPPINGS.encode("utf-8"))}
check("one entry per book, the byte-order mark and author parenthesis read", set(books) == {
    "Müşterek Mekan", "İdeoloji ve Devletin İdeolojik Aygıtları (Kitap (1))"})
mm = books["Müşterek Mekan"]
check("the author comes from the last parenthesis", mm.author == "Stavros Stavrides")
check("an extended highlight replaces the shorter one it grew from",
      [h.text for h in mm.highlights if h.text][:1] == ["Toplumsal ya da kentsel düzen, erişilmiş bir durum değil bir projedir."])
check("bookmarks are not highlights", len([h for h in mm.highlights if h.text]) == 2)
check("a note goes with the highlight ending where it sits",
      mm.highlights[0].note == "Cok hos, proje fikri onemli")
gig = next(h for h in mm.highlights if "Gigantomanya" in h.text)
check("an abbreviated location range is read whole", (gig.loc_start, gig.loc_end) == (700, 701))
check("a note written after its highlight still finds it", gig.note == "Bu ne demek? Yapay zekaya sor")
check("page and location are kept", (mm.highlights[0].page, mm.highlights[0].loc_start) == ("35", 512))

LIMIT = """Kitap (Yazar)
- Your Highlight on page 84 | Location 1200-1201 | Added on Monday, January 26, 2026 10:00:00 PM

<You have reached the clipping limit for this item>
==========
Kitap (Yazar)
- Your Highlight on page 85 | Location 1210-1211 | Added on Monday, January 26, 2026 10:01:00 PM

Gerçek bir vurgu.
==========
"""
print("\nPast a book's clipping limit")
lim = read_books(LIMIT)[0]
check("the Kindle's placeholder is not a highlight, and is counted",
      [h.text for h in lim.highlights] == ["Gerçek bir vurgu."] and lim.limited == 1)

print("\nA title the Kindle wrote decomposed")
nfd = read_books("İdeoloji (Yazar)\n- Your Highlight on page 1 | Location 1-2 | Added on Monday, January 26, 2026\n\nBir vurgu.\n==========\n")[0]
check("is one form of the letters", nfd.title == "İdeoloji")

print("\nA highlight in a book Matbaa hyphenated")
shy = read_books("Kitap (Yazar)\n- Your Highlight on page 1 | Location 1-2 | Added on Monday, January 26, 2026\n\n"
                 "top\u00adlum\u00adsal bir mü\u00adca\u00addele\n==========\n")[0]
check("keeps no soft hyphens", shy.highlights[0].text == "toplumsal bir mücadele")

TYPING = """Felsefenin Başlangıç İlkeleri (Georges Politzer)
- Your Highlight on page 213 | Location 2863-2865 | Added on Monday, January 26, 2026 10:17:29 PM

yumurta, kendi kendisi ile uyumsuzluk içindedir
==========
Felsefenin Başlangıç İlkeleri (Georges Politzer)
- Your Note on page 213 | Location 2865 | Added on Monday, January 26, 2026 10:17:32 PM

he
==========
Felsefenin Başlangıç İlkeleri (Georges Politzer)
- Your Note on page 213 | Location 2865 | Added on Monday, January 26, 2026 10:17:34 PM

her sehy
==========
Felsefenin Başlangıç İlkeleri (Georges Politzer)
- Your Note on page 213 | Location 2865 | Added on Monday, January 26, 2026 10:17:36 PM

her sey celiskili
==========
"""
print("\nA note saved again and again while it was typed")
typed = read_books(TYPING)[0]
check("only the last version is the note", [h.note for h in typed.highlights] == ["her sey celiskili"])

TURKISH_UI = """Müşterek Mekan (Stavros Stavrides)
- Sayfa 12 üzerindeki Vurgulamanız | Konum 150-152 | Eklenme Tarihi: 17 Ekim 2026 Cumartesi 20:21:03

Metropol insan etkinliklerinin parçalı mahalli
==========
Müşterek Mekan (Stavros Stavrides)
- Sayfa 12 üzerindeki Notunuz | Konum 152 | Eklenme Tarihi: 17 Ekim 2026 Cumartesi 20:22:03

anlamadim
==========
"""
print("\nThe same file from a Kindle set to Turkish")
tr = read_books(TURKISH_UI)[0]
check("highlight and note are told apart in Turkish",
      len(tr.highlights) == 1 and tr.highlights[0].note == "anlamadim" and tr.highlights[0].page == "12")

NOTEBOOK = """<html><body>
<div class="bookTitle">Gençlerle Baş Başa Sosyalizm</div>
<div class="authors">Metin Çulhaoğlu</div>
<div class="sectionHeading">Başla</div>
<div class="noteHeading">Highlight (<span class="highlight_yellow">yellow</span>) - Location 120</div>
<div class="noteText">Hümanizm bir &quot;insan doğası&quot; belirler.</div>
<div class="noteHeading">Note - Location 120</div>
<div class="noteText">Psikanalize uygun bir durum</div>
<div class="sectionHeading">Mülkiyet</div>
<div class="noteHeading">Highlight (<span class="highlight_blue">blue</span>) - Location 340</div>
<div class="noteText">özel mülkiyetle</div>
</body></html>"""
print("\nThe HTML notebook from Amazon's Export notes")
nb = read_books(NOTEBOOK)[0]
check("title, author and the book's own sections are read",
      nb.title == "Gençlerle Baş Başa Sosyalizm" and nb.author == "Metin Çulhaoğlu"
      and [h.section for h in nb.highlights] == ["Başla", "Mülkiyet"])
check("entities are decoded and the note is paired",
      nb.highlights[0].text == 'Hümanizm bir "insan doğası" belirler.' and nb.highlights[0].note == "Psikanalize uygun bir durum")
check("the highlight colour is kept", [h.color for h in nb.highlights] == ["yellow", "blue"])

CSV = '''"Your Kindle Notes For:"
"Müşterek Mekan"
"by Stavros Stavrides"
"----------------------------------------------"
""
"Annotation Type","Location","Starred?","Annotation"
"Highlight (Yellow)","Location 512","","Toplumsal düzen bir projedir."
"Note","Location 512","","Bu ne demek?"
'''
print("\nThe CSV the Kindle apps export")
csvb = read_books(CSV)[0]
check("title, author, highlight and its note are read",
      csvb.title == "Müşterek Mekan" and csvb.author == "Stavros Stavrides"
      and [(h.text, h.note) for h in csvb.highlights] == [("Toplumsal düzen bir projedir.", "Bu ne demek?")])

print("\nThe key a passage is recognised by")
check("a line-end hyphen and Turkish capitals do not change a passage",
      fold("İdeoloji bil- ginin") == fold("ideoloji bilginin"))
check("block ids are stable and differ between passages",
      block_id("Bir metin.") == block_id("bir  METIN") and block_id("Bir metin.") != block_id("Başka metin."))

if failures:
    print(f"\n{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("\nALL CHECKS PASSED")
