"""Writing Kindle highlights into an Obsidian vault (backend/app/obsidian.py).

    python tools/test_obsidian.py

Every vault here is a scratch folder; the reader's own vault is never
touched. Exit code is 1 if anything fails.
"""
from __future__ import annotations

import os
import sys
import tempfile

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "backend"))

from app import obsidian  # noqa: E402
from app.clippings import read_books  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        failures.append(name)


def write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def read(path: str) -> str:
    return open(path, encoding="utf-8").read()


vault = tempfile.mkdtemp(prefix="vault-")
write(os.path.join(vault, "6 - Tags", "Özel Mülkiyet.md"), "---\ntags: []\n---\n")
write(os.path.join(vault, "6 - Tags", "Metanarrative.md"), "---\ntags: []\naliases:\n  - Büyük Anlatı\n---\n")
write(os.path.join(vault, "5 - Template", "Basic Template.md"), "---\ntags: []\n---\n")
os.makedirs(os.path.join(vault, "2 - Kaynak", "Kitap"))

CLIPS = """Müşterek Mekan (Stavros Stavrides)
- Your Highlight on page 35 | Location 512-516 | Added on Saturday, 17 October 2026 20:21:40

Toplumsal ya da kentsel düzen, erişilmiş bir durum değil bir projedir.
==========
Müşterek Mekan (Stavros Stavrides)
- Your Note on page 35 | Location 516 | Added on Saturday, 17 October 2026 20:22:10

Bu ne demek? Yapay zekaya sor
==========
Müşterek Mekan (Stavros Stavrides)
- Your Highlight on page 36 | Location 530-530 | Added on Saturday, 17 October 2026 20:25:00

özel mülkiyetle
==========
Müşterek Mekan (Stavros Stavrides)
- Your Highlight on page 37 | Location 540-540 | Added on Saturday, 17 October 2026 20:26:00

"büyük anlatı"
==========
Müşterek Mekan (Stavros Stavrides)
- Your Highlight on page 38 | Location 550-550 | Added on Saturday, 17 October 2026 20:27:00

"Gigantomanya"
==========
Müşterek Mekan (Stavros Stavrides)
- Your Highlight on page 39 | Location 560-561 | Added on Saturday, 17 October 2026 20:28:00

Beklenti nesnesini çağırır
==========
"""

print("\nA book met for the first time becomes a note in the reader's format")
book = read_books(CLIPS)[0]
plan = obsidian.plan_book(book, {}, vault, today="2026-10-18")
text = plan.note.text
check("it goes to 2 - Kaynak/Kitap under the book's name",
      plan.note.path.endswith(os.path.join("2 - Kaynak", "Kitap", "Müşterek Mekan.md")) and not plan.note.exists)
check("with the Basic Template's fields and the author",
      text.startswith("---\ntags:\n  - Kitap\nCreated: 2026-10-18\nSource:\nAuthor: Stavros Stavrides\naliases:\nDiscovered via:\n---"))
check("a highlight is the quote with its page and a block id",
      "Toplumsal ya da kentsel düzen, erişilmiş bir durum değil bir projedir. (s. 35) ^h-" in text)
check("the reader's note follows as ==…==", "==Bu ne demek? Yapay zekaya sor==" in text)
check("their question is gathered at the top, linked to its passage",
      "## Sorularım" in text and "- [ ] Bu ne demek? Yapay zekaya sor — [[#^h-" in text
      and text.index("## Sorularım") < text.index("Toplumsal ya da"))
check("an inflected word finds the vault's existing note", "özel mülkiyetle [[Özel Mülkiyet]]" in text)
check("an alias counts as the note", '"büyük anlatı" [[Metanarrative]]' in text)
check("a quoted new term becomes a link", '"[[Gigantomanya]]"' in text)
check("a sentence's opening words do not", "[[Beklenti" not in text)
check("a placeholder only for the new term, in 6 - Tags, in the vault's AI box",
      [os.path.basename(p.path) for p in plan.placeholders] == ["Gigantomanya.md"]
      and "> [!quote]- *Yardımcı bağlam · AI*" in plan.placeholders[0].text
      and "İlk karşılaşma: [[Müşterek Mekan]]" in plan.placeholders[0].text)
check("the note ends with the reader's Final Notes", text.rstrip().endswith("# Final Notes"))

res = obsidian.apply_plan(plan)
check("applying writes the note, the placeholder and the Açık Sorular page", len(res["written"]) == 3 and not res["conflicts"])

print("\nA later sync adds only what is new, and touches nothing the reader wrote")
note_path = plan.note.path
mine = read(note_path).replace("# Final Notes\n", "# Final Notes\n\nKendi düşüncem: proje fikri önemli.\n")
mine = mine.replace("==Bu ne demek? Yapay zekaya sor==", "==Bu ne demek? Yapay zekaya sor==\n\nBen: sonra baktım, anladım.")
write(note_path, mine)
again = obsidian.plan_book(book, {}, vault, today="2026-10-19")
check("nothing is added twice", again.added == 0 and again.already == len(book.highlights))
check("and the note is left exactly as the reader left it", again.note.text == mine and not again.note.diff)

MORE = CLIPS + """Müşterek Mekan (Stavros Stavrides)
- Your Highlight on page 80 | Location 900-902 | Added on Monday, 19 October 2026 21:00:00

Müşterekleşme, paylaşımın kurallarını birlikte koymaktır.
==========
"""
book2 = read_books(MORE)[0]
plan2 = obsidian.plan_book(book2, {}, vault, today="2026-10-20")
check("a new highlight is added", plan2.added == 1 and "Müşterekleşme, paylaşımın kurallarını" in plan2.note.text)
check("the reader's own lines survive",
      "Kendi düşüncem: proje fikri önemli." in plan2.note.text and "Ben: sonra baktım, anladım." in plan2.note.text)
check("the new highlight goes before Final Notes",
      plan2.note.text.index("Müşterekleşme, paylaşımın") < plan2.note.text.index("# Final Notes"))
check("the questions region is refreshed, not duplicated", plan2.note.text.count("## Sorularım") == 1)

print("\nA question the reader ticked off stays ticked")
dash_path = os.path.join(vault, "2 - Kaynak", "Açık Sorular.md")
check("the Açık Sorular page was made, gathering open boxes with Obsidian's own search",
      os.path.exists(dash_path) and 'task-todo:"" path:"2 - Kaynak/Kitap"' in read(dash_path))
ticked = read(note_path).replace("- [ ] Bu ne demek?", "- [x] Bu ne demek?")
write(note_path, ticked)
plan_t = obsidian.plan_book(book2, {}, vault, today="2026-10-20")
check("after the next sync the box is still ticked", "- [x] Bu ne demek?" in plan_t.note.text)
check("and the Açık Sorular page is not made again", not plan_t.pages)
plan2 = plan_t

print("\nA note the reader edits after the plan is not overwritten")
write(note_path, read(note_path) + "\nSon dakika eklemem.\n")
res = obsidian.apply_plan(plan2)
check("the write is refused and reported", res["conflicts"] == [note_path] and "Son dakika eklemem." in read(note_path))

print("\nHighlights from before the note was started that it does not hold")
QUOTED_NOTE = """---
tags:
  - Kitap
Created: 2025-11-15
---
## Front Matter

"ekonomizm".
Highlight (yellow)
"""
write(os.path.join(vault, "2 - Kaynak", "Kitap", "Althusser Denemesi.md"), QUOTED_NOTE)
quoted_book = read_books("Althusser Denemesi (Louis Althusser)\n- Your Highlight on page 4 | Location 41-41 | "
                         "Added on Saturday, November 1, 2025 10:00:00 PM\n\n\"ekonomizm\".\n==========\n")[0]
pq = obsidian.plan_book(quoted_book, {}, vault, today="2026-10-18")
check("a word the note holds in quotes is recognised as already there", pq.already == 1 and not pq.held_back)

OLD_NOTE = """---
tags:
  - Kitap
Created: 2025-11-01
Source:
Author: Metin Çulhaoğlu
aliases:
Discovered via:
---
## Highlights and Notes

Hümanizm bir "insan doğası" belirler.
**Highlight (yellow)**

# Final Notes

Çok ufuk açan bir kitap olmadı.
"""
write(os.path.join(vault, "2 - Kaynak", "Kitap", "Gençlerle Baş Başa Sosyalizm.md"), OLD_NOTE)
OLD = """Metin Çulhapğlu Gençlerle Baş Başa Sosyalizm Yordam Kitap - Bilinmiyor (Bilinmiyor)
- Your Highlight on page 3 | Location 40-41 | Added on Saturday, October 25, 2025 10:00:00 PM

Hümanizm bir "insan doğası" belirler.
==========
Metin Çulhapğlu Gençlerle Baş Başa Sosyalizm Yordam Kitap - Bilinmiyor (Bilinmiyor)
- Your Highlight on page 5 | Location 60-61 | Added on Sunday, October 26, 2025 10:00:00 PM

Bu vurguyu okur Kindle'da silmişti ama My Clippings hâlâ tutuyor.
==========
Metin Çulhapğlu Gençlerle Baş Başa Sosyalizm Yordam Kitap - Bilinmiyor (Bilinmiyor)
- Your Highlight on page 9 | Location 90-91 | Added on Monday, November 10, 2025 10:00:00 PM

Not açıldıktan sonra yapılan yeni bir vurgu burada duruyor.
==========
"""
old_book = read_books(OLD)[0]
p3 = obsidian.plan_book(old_book, {}, vault, today="2026-10-18")
check("the Kindle's messy title still finds the reader's note",
      os.path.basename(p3.note.path) == "Gençlerle Baş Başa Sosyalizm.md" and p3.note.exists)
check("what the note already holds is recognised", p3.already == 1)
check("an older highlight it lacks is held back, not added",
      [h["text"][:20] for h in p3.held_back] == ["Bu vurguyu okur Kind"] and "Bu vurguyu okur" not in p3.note.text)
check("a newer one is added", p3.added == 1 and "Not açıldıktan sonra yapılan" in p3.note.text)
check("the pasted export and Final Notes are untouched",
      "Hümanizm bir \"insan doğası\" belirler.\n**Highlight (yellow)**" in p3.note.text
      and "Çok ufuk açan bir kitap olmadı." in p3.note.text)
check("offered unticked", [h["included"] for h in p3.held_back] == [False])
p4 = obsidian.plan_book(old_book, {}, vault, include={p3.held_back[0]["id"]}, today="2026-10-18")
check("and the reader can choose to add it after all", p4.added == 2 and "Bu vurguyu okur" in p4.note.text)
check("ticked, it stays in the list, ticked", [(h["id"], h["included"]) for h in p4.held_back]
      == [(p3.held_back[0]["id"], True)])

print("\nWhat the note already holds")
from app.clippings import Highlight  # noqa: E402

note_text = ("> Not açıldıktan sonra ilk çizdiğim yer burada duruyor ve uzunca bir cümle oluyor.\n"
             "> Kapitalizm mekanı yeniden üretirken kendi çelişkilerini de gerek tiğine inanır.\n")


def held(text: str) -> bool:
    e = obsidian.Entry(highlight=Highlight(id="h-test01", text=text), placement=None, quote=text,
                       chapter="Vurgular", subheading=None)
    return not obsidian.missing_from(note_text, [e])


check("a passage beginning like one in the note is not taken for it",
      not held("Not açıldıktan sonra çizilen ve henüz notta olmayan başka bir yer var burada."))
check("a passage spelled a little differently is still recognised",
      held("Kapitalizm mekânı yeniden üretirken kendi çelişkilerini de gerektiğine inanır."))
check("and the same passage, of course", held("Not açıldıktan sonra ilk çizdiğim yer burada duruyor ve uzunca bir cümle oluyor."))

print("\nThe Kindle sign language: a note's first character says what it is")
check("? is a question, the sign left out", obsidian.classify_note("? kent hakkı ne demek").kind == "question"
      and obsidian.classify_note("? kent hakkı ne demek").text == "kent hakkı ne demek")
check("! is the reader's idea", obsidian.classify_note("!Bu Lefebvre'yle konuşuyor").kind == "idea")
check("> names links, split at commas and 've'",
      obsidian.classify_note("> Gramsci, Hegemonya ve Mevzi").names == ["Gramsci", "Hegemonya", "Mevzi"])
check("* marks it important", obsidian.classify_note("* tam da bu").kind == "important")
check("'?!' alone is a reaction, not a sign", obsidian.classify_note("?!").kind != "question"
      or obsidian.classify_note("?!").text == "?!")
check("without a sign, a note that asks is still a question", obsidian.classify_note("bu nedir").kind == "question")
check("and a plain remark stays plain", obsidian.classify_note("Cok hos").kind == "plain")
check("Kindle-typed questions without a question mark are questions",
      all(obsidian.classify_note(n).kind == "question" for n in
          ("bu ney", "o nasi bisi", "bi bak bakalim kimmis neciymis", "başka eserleri bakilabilir")))
check("but 'kimlik' or 'nasıl da güzel' alone are not",
      obsidian.classify_note("kimlik meselesi").kind == "plain")

SIGNS = """Kent Defteri (Yazar)
- Your Highlight on page 10 | Location 100-101 | Added on Monday, 19 October 2026 10:00:00

Müşterekleşme, paylaşımın kurallarını birlikte koymaktır.
==========
Kent Defteri (Yazar)
- Your Note on page 10 | Location 101 | Added on Monday, 19 October 2026 10:00:10

!Bu, kooperatif deneyimimizle birebir örtüşüyor
==========
Kent Defteri (Yazar)
- Your Highlight on page 12 | Location 120-121 | Added on Monday, 19 October 2026 10:01:00

Kentsel çitlemeler ortak alanı parçalar.
==========
Kent Defteri (Yazar)
- Your Note on page 12 | Location 121 | Added on Monday, 19 October 2026 10:01:10

> özel mülkiyetin, Mekansal Adalet
==========
Kent Defteri (Yazar)
- Your Highlight on page 14 | Location 140-141 | Added on Monday, 19 October 2026 10:02:00

Eşik, hem ayıran hem birleştiren yerdir.
==========
Kent Defteri (Yazar)
- Your Note on page 14 | Location 141 | Added on Monday, 19 October 2026 10:02:10

*
==========
"""
sign_book = read_books(SIGNS)[0]
ps = obsidian.plan_book(sign_book, {}, vault, today="2026-10-19")
st = ps.note.text
check("an idea is written as the vault writes the reader's own words", "**Ben:** Bu, kooperatif deneyimimizle" in st)
check("and listed under Fikirlerim with a link to its passage",
      "## Fikirlerim" in st and "- Bu, kooperatif deneyimimizle birebir örtüşüyor — [[#^h-" in st)
check("names after > become links, an inflected one to the existing note",
      "→ [[Özel Mülkiyet]] · [[Mekansal Adalet]]" in st)
check("a new name gets its placeholder", any(p.path.endswith("Mekansal Adalet.md") for p in ps.placeholders))
check("* makes the passage stand out", "**Eşik, hem ayıran hem birleştiren yerdir.**" in st)
check("the Fikirlerim page is offered once, by Obsidian's own search",
      any(p.path.endswith("Fikirlerim.md") and '"**Ben:**"' in p.text for p in ps.pages))

print("\nAn idea grown into its own note in 3 - Gelişen Notlar")
idea_h = next(h for h in sign_book.highlights if h.note and h.note.startswith("!"))
dp = obsidian.develop_plan(sign_book, idea_h, "Kent Defteri", vault, today="2026-10-19", note_has_block=True)
check("it goes to 3 - Gelişen Notlar, named after the idea's first words",
      os.path.join("3 - Gelişen Notlar", "Bu, kooperatif deneyimimizle birebir örtüşüyor.md") in dp.path)
check("with the reader's words, the passage, and a link to the passage's block",
      "Bu, kooperatif deneyimimizle birebir örtüşüyor" in dp.text
      and "> Müşterekleşme, paylaşımın kurallarını birlikte koymaktır." in dp.text
      and f"[[Kent Defteri#^{idea_h.id}|Kent Defteri, s. 10]]" in dp.text
      and 'Source: "[[Kent Defteri]]"' in dp.text)
write(dp.path, dp.text)
dp2 = obsidian.develop_plan(sign_book, idea_h, "Kent Defteri", vault, today="2026-10-19")
check("a second time it never takes the existing note's name", dp2.path.endswith("örtüşüyor (2).md"))

print("\nWhere a concept was met before")
met = obsidian.encounters(vault)
check("book notes linking to a concept are found, by the concept's folded name",
      "Müşterek Mekan" in met.get(obsidian.fold_ascii("Özel Mülkiyet"), []))

print("\nAn answer brought back from ChatGPT goes under its passage, in the vault's AI box")
ans_vault = tempfile.mkdtemp(prefix="vault-")
os.makedirs(os.path.join(ans_vault, "2 - Kaynak", "Kitap"))
os.makedirs(os.path.join(ans_vault, "6 - Tags"))
q_book = read_books(CLIPS)[0]
q = next(h for h in q_book.highlights if h.note and "ne demek" in h.note)
first = obsidian.plan_book(q_book, {}, ans_vault, today="2026-10-19")
obsidian.apply_plan(first)
qa_path = first.note.path
answered_plan = obsidian.plan_book(q_book, {}, ans_vault, today="2026-10-19",
                                   answers={q.id: "Yazar burada düzeni bir süreç olarak görüyor.\n\n- birinci nokta"})
at = answered_plan.note.text
box = obsidian.answer_block(q.id, "Yazar burada düzeni bir süreç olarak görüyor.\n\n- birinci nokta")
check("the answer is a collapsed 'Yardımcı bağlam · AI' box, italic where it can be",
      "> [!quote]- *Yardımcı bağlam · AI*\n> *Yazar burada düzeni bir süreç olarak görüyor.*" in box
      and "> - birinci nokta" in box and f"%% matbaa:yanit {q.id} %%" in box)
check("it sits right under the passage and the reader's note",
      at.index("==Bu ne demek? Yapay zekaya sor==") < at.index(box)
      < at.index("özel mülkiyetle"))
check("the plan counts it", answered_plan.answers == 1)
obsidian.apply_plan(answered_plan)
again_plan = obsidian.plan_book(q_book, {}, ans_vault, today="2026-10-19",
                                answers={q.id: "Yazar burada düzeni bir süreç olarak görüyor.\n\n- birinci nokta"})
check("the next sync recognises it and adds nothing", not again_plan.note.diff)
changed = obsidian.plan_book(q_book, {}, ans_vault, today="2026-10-19", answers={q.id: "Daha iyi bir yanıt."})
check("a changed answer replaces its box, not a second one",
      changed.note.text.count(f"matbaa:yanit {q.id}") == 1 and "*Daha iyi bir yanıt.*" in changed.note.text)

PASTED = """---
tags:
  - Kitap
Created: 2025-11-01
---
## Highlights and Notes

Hümanizm bir "insan doğası" belirler.
**Highlight (yellow)**

==Bu ne demek acaba==
==**Note**==

Bir sonraki vurgu.
**Highlight (yellow)**
"""
write(os.path.join(ans_vault, "2 - Kaynak", "Kitap", "Eski Kitap.md"), PASTED)
old_q = read_books("Eski Kitap (Yazar)\n- Your Highlight on page 3 | Location 40-41 | Added on Saturday, October 25, 2025\n\n"
                   "Hümanizm bir \"insan doğası\" belirler.\n==========\n"
                   "Eski Kitap (Yazar)\n- Your Note on page 3 | Location 41 | Added on Saturday, October 25, 2025\n\n"
                   "Bu ne demek acaba\n==========\n")[0]
hq = next(h for h in old_q.highlights if h.note)
pp = obsidian.plan_book(old_q, {}, ans_vault, today="2026-10-19", answers={hq.id: "Aydınlanma'nın insan anlayışı."})
pt = pp.note.text
check("in a pasted-in note without block ids it goes after the reader's note and its label",
      pt.index("==**Note**==") < pt.index("*Aydınlanma'nın insan anlayışı.*") < pt.index("Bir sonraki vurgu."))
check("and nothing of the pasted note is lost", all(l in pt for l in PASTED.splitlines() if l.strip()))

if failures:
    print(f"\n{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("\nALL CHECKS PASSED")
