"""The Kelime Defteri: looked-up words from the Kindle into the vault
(backend/app/vocab.py, wordbook.py, the notebook's printed pages, the API).

    python tools/test_wordbook.py

Uses a vocab.db made here with the Kindle's own tables, a scratch vault and
a scratch Kindle folder. Exit code is 1 if anything fails.
"""
from __future__ import annotations

import gzip
import json
import os
import sqlite3
import sys
import tempfile
from types import SimpleNamespace

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "backend"))
os.environ["MATBAA_PROJECTS"] = tempfile.mkdtemp()
os.environ["MATBAA_NOTEBOOK"] = tempfile.mkdtemp()

from app import dictionary, notebook, vocab, wordbook  # noqa: E402
from app.models import ChapterOut  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        failures.append(name)


PAGE = '<span epub:type="pagebreak" role="doc-pagebreak" id="page-{0}" aria-label="{0}"></span>'


def make_vocab_db(path: str, lookups) -> None:
    con = sqlite3.connect(path)
    con.executescript("""
CREATE TABLE WORDS (id TEXT PRIMARY KEY NOT NULL, word TEXT, stem TEXT, lang TEXT, category INTEGER DEFAULT 0, timestamp INTEGER DEFAULT 0, profileid TEXT);
CREATE TABLE LOOKUPS (id TEXT PRIMARY KEY NOT NULL, word_key TEXT, book_key TEXT, dict_key TEXT, pos TEXT, usage TEXT, timestamp INTEGER DEFAULT 0);
CREATE TABLE BOOK_INFO (id TEXT PRIMARY KEY NOT NULL, asin TEXT, guid TEXT, lang TEXT, title TEXT, authors TEXT);
CREATE TABLE DICT_INFO (id TEXT PRIMARY KEY NOT NULL, asin TEXT, langin TEXT, langout TEXT);
""")
    con.execute("INSERT INTO BOOK_INFO VALUES ('CR!MM', 'CR!MM', 'G', '', 'Müşterek Mekan', 'Stavros Stavrides')")
    con.execute("INSERT INTO BOOK_INFO VALUES ('CR!WK', 'B01', 'G', 'en', 'The Way of Kings', 'Sanderson, Brandon')")
    for i, (word, lang, book, usage, ts, cat) in enumerate(lookups):
        con.execute("INSERT OR IGNORE INTO WORDS VALUES (?, ?, ?, ?, ?, ?, '')", (f"{lang}:{word}", word, word, lang, cat, ts))
        con.execute("INSERT INTO LOOKUPS VALUES (?, ?, ?, 'D', 'AZ:1', ?, ?)", (f"L{i}", f"{lang}:{word}", book, usage, ts))
    con.commit()
    con.close()


print("\nThe Kindle's list of looked-up words")
work = tempfile.mkdtemp()
db = os.path.join(work, "vocab.db")
make_vocab_db(db, [
    ("müştereklerin", "tr", "CR!MM", "Kentin ortak alanları üzerine. Şehrin müştereklerin ağı olarak düşünülmesi "
                                       "gerekir, der yazar. Başka bir cümle.", 1781124263000, 0),
    ("müstahsil", "tr", "CR!MM", "Ama müstahsil köylünün emeği burada görünmez.", 1781124300000, 100),
    ("windrunner", "en", "CR!WK", "He was a Windrunner of old.", 1781124400000, 0),
])
lookups = vocab.read_db(db)
check("each lookup with its word, sentence, book and time", len(lookups) == 3 and lookups[0].word == "müştereklerin"
      and lookups[0].book == "Müşterek Mekan" and lookups[0].added.startswith("2026-")
      and "müştereklerin ağı" in lookups[0].usage)
check("a word marked learnt on the Kindle", lookups[1].learnt and not lookups[0].learnt)
check("ids are the Kindle's, hashed, stable", vocab.read_db(db)[0].id == lookups[0].id and lookups[0].id.startswith("w-"))
check("kept once, however often it is imported", vocab.import_lookups(lookups) == 3 and vocab.import_lookups(lookups) == 0
      and len(vocab.load()) == 3)

print("\nThe sentence, and the printed page")
check("the sentence that holds the word", wordbook.sentence_with(lookups[0].usage, "müştereklerin")
      == "Şehrin müştereklerin ağı olarak düşünülmesi gerekir, der yazar.")
long = " ".join(f"kelime{i}" for i in range(60)) + " aranan " + " ".join(f"söz{i}" for i in range(60))
cut = wordbook.sentence_with(long, "aranan")
check("a very long one is cut around the word", cut.startswith("…") and cut.endswith("…") and "aranan" in cut
      and len(cut.split()) <= 41)
chapters = [
    ChapterOut(id="ch_0001", index=0, title="Giriş", html=f"<p>Kentin ortak alanları üzerine.{PAGE.format(41)} Şehrin "
               "müştereklerin ağı olarak düşünülmesi gerekir, der yazar.</p>"),
    ChapterOut(id="ch_0002", index=1, title="Köy", html=f"<p>{PAGE.format(87)}</p><p>Ama müstahsil köylünün emeği "
               "burada görünmez.</p>"),
]
session = SimpleNamespace(chapters=chapters)
blocks = notebook.book_blocks(session)
check("a block knows the page it begins on and where the next begins", blocks[0].page is None
      and blocks[0].marks and blocks[0].page_at(40) == "41" and blocks[0].page_at(3) is None)
check("a page mark alone in a paragraph carries to the next", blocks[1].page == "87")
placed = notebook.BookText(blocks).find("Şehrin müştereklerin ağı olarak düşünülmesi gerekir")
check("a passage placed in the book knows its printed page", placed is not None and placed.page == "41")
check("and the text stays exactly the book's words", "alanları üzerine. Şehrin" in blocks[0].text)

print("\nMeanings, from a dictionary made here")
src = os.path.join(work, "raw.jsonl.gz")
with gzip.open(src, "wt", encoding="utf-8") as f:
    for row in ({"word": "müşterek", "lang_code": "tr", "pos": "adj", "senses": [{"glosses": ["ortak"]}, {"glosses": ["birlik"]}]},
                {"word": "müstahsil", "lang_code": "tr", "pos": "noun", "senses": [{"glosses": ["Üretici, yetiştirici"]}]}):
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
trdb = os.path.join(work, "tr.db")
dictionary.save_db(dictionary.load_source(src), trdb)
d = dictionary.Dictionary(trdb)

print("\nInto the vault")
vault = tempfile.mkdtemp()
os.makedirs(os.path.join(vault, "2 - Kaynak", "Kitap"))
with open(os.path.join(vault, "Açık Sorular.md"), "w", encoding="utf-8") as f:
    f.write("sorular\n")
with open(os.path.join(vault, "2 - Kaynak", "Kitap", "Müşterek Mekan.md"), "w", encoding="utf-8") as f:
    f.write("---\ntags:\n  - Kitap\n---\n")
projects = [{"session_id": "s1", "book_title": "Müşterek Mekan"}]
words = wordbook.entries(lookups, projects, lambda sid: session if sid == "s1" else None, d, vault, {})
mm = words[0]
check("headword, meaning, sentence and page", mm.headword == "müşterek" and mm.meaning == "ortak; birlik"
      and mm.page == "41" and mm.book_note == "Müşterek Mekan")
check("an English word gets no Turkish meaning", words[2].meaning is None and words[2].book == "The Way of Kings")
plan = wordbook.plan(words, vault, {}, today="2026-10-18")
fp = plan["file"]
check("the note goes beside Açık Sorular", fp.path == os.path.join(vault, "Kelime Defteri.md") and not fp.exists)
check("one line per word, under its book", "## [[Müşterek Mekan]]" in fp.text and "## The Way of Kings" in fp.text
      and fp.text.count(wordbook.MARK) == 3)
line = next(ln for ln in fp.text.splitlines() if mm.id in ln)
check("the line: word, headword, meaning (labelled), sentence with the word, page",
      line.startswith("- **müştereklerin** (müşterek) — *ortak; birlik* (Vikisözlük) · “Şehrin **müştereklerin** ağı")
      and "(s. 41)" in line)
check("the vault's template fields", fp.text.startswith("---\ntags: []\nCreated: 2026-10-18\n"))
os.makedirs(os.path.dirname(fp.path), exist_ok=True)
mine = fp.text.replace(line, line + "\n  - benim açıklamam: kentin ortak kullanımı")
with open(fp.path, "w", encoding="utf-8") as f:
    f.write(mine)
again = wordbook.plan(words, vault, {})
check("written once: nothing added twice", again["added"] == 0 and again["already"] == 3 and not again["file"].diff)
new = vocab.Lookup("w-new0000001", "müstahsilin", "müstahsilin", "tr", "Müstahsilin payı küçüldü.", "Müşterek Mekan",
                   "", "2026-10-19T10:00:00", False)
more = wordbook.entries([new], projects, lambda sid: session, d, vault, {})
later = wordbook.plan(words + more, vault, {})
text = later["file"].text
check("a new word joins its book's section, after the others", later["added"] == 1
      and text.index("w-new0000001") > text.index(mm.id) and text.index("w-new0000001") < text.index("## The Way of Kings"))
check("the reader's own line under a word is kept", "  - benim açıklamam: kentin ortak kullanımı" in text
      and all(ln in text.splitlines() for ln in mine.splitlines()))
only = wordbook.plan(words + more, vault, {}, include=set())
check("nothing chosen, nothing changed", only["added"] == 0 and not only["file"].diff)

print("\nThe API")
from fastapi.testclient import TestClient  # noqa: E402

from app import kindle_usb, main, obsidian  # noqa: E402

kindle = tempfile.mkdtemp()
os.makedirs(os.path.join(kindle, "documents"))
os.makedirs(os.path.join(kindle, "system", "vocabulary"))
import shutil  # noqa: E402

shutil.copyfile(db, os.path.join(kindle, "system", "vocabulary", "vocab.db"))
os.environ[kindle_usb.LOCAL_ENV] = kindle
os.environ["MATBAA_NOTEBOOK"] = tempfile.mkdtemp()
vault2 = tempfile.mkdtemp()
os.makedirs(os.path.join(vault2, "2 - Kaynak", "Kitap"))
real_settings = obsidian.load_settings
obsidian.load_settings = lambda: {"vault": vault2}
real_dict = main._word_dictionary
main._word_dictionary = lambda: d
try:
    client = TestClient(main.app)
    r = client.post("/api/notebook/words/kindle")
    check("the words come off the Kindle", r.status_code == 200 and r.json()["imported"] == 3
          and len(r.json()["words"]) == 3)
    check("asked again, nothing new", client.post("/api/notebook/words/kindle").json()["imported"] == 0)
    listed = client.get("/api/notebook/words").json()
    check("each with its meaning, nothing written yet", listed["words"][-1]["meaning"] == "ortak; birlik"
          and not any(w["in_note"] for w in listed["words"]))
    plan = client.post("/api/notebook/words/plan", json={"include": [listed["words"][0]["id"]]}).json()
    check("a plan for the chosen word only", plan["added"] == 1 and plan["file"]["name"] == "Kelime Defteri.md")
    stale = client.post("/api/notebook/words/write", json={"include": [listed["words"][0]["id"]], "token": "x"})
    check("a write that is not the plan the reader saw is refused", stale.status_code == 409)
    w = client.post("/api/notebook/words/write", json={"include": [listed["words"][0]["id"]], "token": plan["token"]})
    check("the plan is written", w.status_code == 200 and len(w.json()["written"]) == 1
          and os.path.isfile(os.path.join(vault2, "2 - Kaynak", "Kelime Defteri.md")))
    listed = client.get("/api/notebook/words").json()
    check("and the word is shown as in the note", listed["words"][0]["in_note"])
    os.environ[kindle_usb.LOCAL_ENV] = os.path.join(kindle, "gone")
    check("no Kindle: said so", client.post("/api/notebook/words/kindle").status_code == 404)
finally:
    obsidian.load_settings = real_settings
    main._word_dictionary = real_dict

if failures:
    print(f"\n{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("\nALL CHECKS PASSED")
