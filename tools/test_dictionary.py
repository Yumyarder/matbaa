"""The Turkish dictionary (backend/app/dictionary.py, turkish_words.py).

    python tools/test_dictionary.py

A small Wiktionary extract made here stands in for the real one. Exit code
is 1 if anything fails.
"""
from __future__ import annotations

import gzip
import json
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

from app import dictionary  # noqa: E402
from app.turkish_words import Lemmatizer, lower_tr, words  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        failures.append(name)


print("\nFrom a printed word to its headword")
lem = Lemmatizer({"kitap", "çocuk", "karar", "kar", "gelmek", "müşterek", "ağaç", "de", "mi", "ev"},
                 {"kitabı": "kitap", "geliyor": "gelmek"})
for word, want in (("karar", "karar"), ("kitabı", "kitap"), ("kitaplarımızdan", "kitap"),
                   ("Kitapları", "kitap"), ("çocuğu", "çocuk"), ("ağacın", "ağaç"), ("geliyorum", "gelmek"),
                   ("gelirken", "gelmek"), ("müştereklerin", "müşterek"), ("Marx'ın", None), ("da", "de"),
                   ("mı", "mi"), ("evlerimizde", "ev"), ("xyzt", None)):
    check(f"{word} → {want}", lem.lemma(word) == want)
check("a suffix out of harmony is not one", Lemmatizer({"kitap"}).lemma("kitapler") is None)
check("Turkish lower case: I is ı, İ is i", lower_tr("IŞIK İzmir") == "ışık izmir")
check("a proper noun's suffix is dropped", list(words("Gramsci'nin ve Lenin’e göre")) == ["gramsci", "ve", "lenin", "göre"])

print("\nThe Wiktionary extract")
work = tempfile.mkdtemp()
source = os.path.join(work, "raw.jsonl.gz")
rows = [
    {"word": "kitap", "lang_code": "tr", "pos": "noun",
     "senses": [{"glosses": ["Ciltli veya ciltsiz olarak bir araya getirilmiş, basılı yapraklar"]},
                {"glosses": ["Herhangi bir konuda yazılmış eser:"]}],
     "forms": [{"form": "kitabı", "tags": ["accusative"]}, {"form": "kitaplar", "tags": ["plural"]},
               {"form": "kitap", "tags": ["nominative"]}, {"form": "-", "tags": []}]},
    {"word": "kitapçı", "lang_code": "tr", "pos": "noun", "senses": [{"glosses": ["Kitap satan kimse"]}]},
    {"word": "kitapta", "lang_code": "tr", "pos": "noun",
     "senses": [{"glosses": ["kitap sözcüğünün çekimi:"], "tags": ["form-of"], "form_of": [{"word": "kitap"}]}]},
    {"word": "müşterek", "lang_code": "tr", "pos": "adj", "senses": [{"glosses": ["ortak"]}, {"glosses": ["birlik"]}]},
    {"word": "book", "lang_code": "en", "pos": "noun", "senses": [{"glosses": ["kitap"]}]},
    {"word": "iki kelime", "lang_code": "tr", "pos": "phrase", "senses": [{"glosses": ["söz öbeği"]}]},
]
with gzip.open(source, "wt", encoding="utf-8") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
heads = dictionary.load_source(source)
check("Turkish headwords only, single words", sorted(heads) == ["kitap", "kitapçı", "müşterek"])
check("senses kept with their part of speech, a closing colon dropped",
      heads["kitap"].senses == [("ad", ["Ciltli veya ciltsiz olarak bir araya getirilmiş, basılı yapraklar",
                                        "Herhangi bir konuda yazılmış eser"])])
check("forms from the table and from \"form of\" entries", heads["kitap"].forms == {"kitabı", "kitaplar", "kitapta"})
added = dictionary.add_book_forms(heads, ["kitaplarımızdan", "müştereklerin", "kitapçılar", "kitap", "zzz"])
check("the books' own forms join their headwords", added == 3 and "kitaplarımızdan" in heads["kitap"].forms
      and "müştereklerin" in heads["müşterek"].forms and "kitapçılar" in heads["kitapçı"].forms)

print("\nWhat Matbaa reads itself (tr.db)")
db = os.path.join(work, "tr.db")
dictionary.save_db(heads, db)
d = dictionary.Dictionary(db)
check("a printed word finds its headword and meaning", d.look_up("Kitaplarımızdan") ==
      ("kitap", [("ad", ["Ciltli veya ciltsiz olarak bir araya getirilmiş, basılı yapraklar",
                         "Herhangi bir konuda yazılmış eser"])]))
check("and one the books never printed, by its suffixes", (d.look_up("müşterekler") or ("",))[0] == "müşterek")
check("a word it does not know is None", d.look_up("qwerty") is None)

print("\nThe Kindle dictionary")
build = os.path.join(work, "build")
many = dictionary.Headword("gelmek", [("eylem", ["Ulaşmak, varmak"])], {f"gel{i:04d}" for i in range(600)})
heads["gelmek"] = many
opf = dictionary.write_source(heads, build, dump="2026-10-02")
content = open(os.path.join(build, "content001.html"), encoding="utf-8").read()
opf_text = open(opf, encoding="utf-8").read()
check("Turkish in and out", "<DictionaryInLanguage>tr</DictionaryInLanguage>" in opf_text
      and "<DictionaryOutLanguage>tr</DictionaryOutLanguage>" in opf_text)
check("each headword an entry with its forms", '<idx:orth value="kitap">' in content
      and '<idx:iform value="kitaplarımızdan"/>' in content)
check("a long table of forms is spread over entries the Kindle reads", content.count('<idx:orth value="gelmek">') == 3
      and all(content.count(f'value="gel{i:04d}"') == 1 for i in (0, 299, 599)))
check("the licence on the first page", "CC BY-SA" in open(os.path.join(build, "front.html"), encoding="utf-8").read())
if dictionary.find_kindlegen():
    mobi, report = dictionary.compile_mobi(opf, "deneme.mobi", timeout=600)
    check("kindlegen makes it", mobi is not None and os.path.getsize(mobi) > 1000 and "Error" not in report)
else:
    print("  (kindlegen yok; derleme denenmedi)")

if failures:
    print(f"\n{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("\nALL CHECKS PASSED")
