"""A Turkish dictionary for the Kindle, made from the Turkish Wiktionary.

None of Amazon's Kindle dictionaries is Turkish, and a Kindle looks a word
up in the dictionary of the book's language: in a Turkish book a word held
under the finger finds nothing, and nothing reaches the Kindle's list of
looked-up words. A dictionary put in documents/dictionaries/ whose
languages are Turkish fills that place (the reader picks it once, in
Ayarlar → Dil ve Sözlükler).

The words come from the Turkish Wiktionary (tr.wiktionary.org) as
extracted by wiktextract (kaikki.org/trwiktionary): every Turkish headword
with its senses, and the inflected forms Wiktionary lists for it. Its
licence, CC BY-SA, is Wiktionary's; the dictionary says so on its first
page. The forms the reader's own books use are added to their headwords
(app/turkish_words.py), so "kitaplarımızdan" opens "kitap".

A Kindle dictionary is a book (Amazon's Kindle Publishing Guidelines):
an OPF naming its input and output language, and HTML in which
idx:entry / idx:orth / idx:iform mark each headword and its forms,
compiled by kindlegen, which Kindle Previewer carries. The same words go
to a small SQLite file (tr.db) Matbaa reads itself: a looked-up word's
meaning for the Kelime Defteri, headwords for the index and the search.
"""
from __future__ import annotations

import gzip
import html
import json
import os
import re
import sqlite3
import subprocess
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

from app.turkish_words import Lemmatizer, lower_tr

DATA_DIR = os.environ.get("MATBAA_SOZLUK") or os.path.join(os.path.expanduser("~"), ".matbaa", "sozluk")
SOURCE_FILE = "raw-wiktextract-data.jsonl.gz"
SOURCE_URL = "https://kaikki.org/trwiktionary/raw-wiktextract-data.jsonl.gz"
DB_FILE = "tr.db"
DEVICE_NAME = "Matbaa-Turkce-Sozluk.mobi"
TITLE = "Matbaa Türkçe Sözlük"

MAX_SENSES = 4          # per part of speech
MAX_IFORMS = 250        # the Kindle stops reading an orth's forms not far beyond this
ENTRIES_PER_FILE = 4000
FORM = re.compile(r"^[a-zçğıöşüâîû]+$")

POS_TR = {
    "noun": "ad", "verb": "eylem", "adj": "sıfat", "adv": "zarf", "name": "özel ad", "phrase": "söz öbeği",
    "proverb": "atasözü", "abbrev": "kısaltma", "pron": "zamir", "intj": "ünlem", "suffix": "ek",
    "prefix": "ön ek", "num": "sayı", "conj": "bağlaç", "postp": "edat", "det": "belirteç", "particle": "edat",
    "idiom": "deyim", "character": "harf", "symbol": "simge",
}


@dataclass
class Headword:
    word: str
    senses: List[Tuple[str, List[str]]] = field(default_factory=list)     # (part of speech, glosses)
    forms: set = field(default_factory=set)


def _gloss(sense: Dict) -> Optional[str]:
    glosses = [g.strip() for g in sense.get("glosses") or [] if g and g.strip()]
    if not glosses or "form-of" in (sense.get("tags") or []) or sense.get("form_of"):
        return None
    text = " ".join(g if g.endswith((":", ".", ";")) or i == len(glosses) - 1 else g + ":"
                    for i, g in enumerate(glosses))
    return text.rstrip(":").strip() or None


def load_source(path: str, words_wanted: Optional[set] = None) -> Dict[str, Headword]:
    """Turkish headwords from the wiktextract file: senses, and the forms
    Wiktionary lists (in the headword's table, or as "form of" entries).
    `words_wanted` keeps only those headwords (a small test dictionary)."""
    heads: Dict[str, Headword] = {}
    form_of: List[Tuple[str, str]] = []
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("lang_code") != "tr":
                continue
            word = lower_tr((d.get("word") or "").strip())
            if not word or " " in word:
                continue
            pos = POS_TR.get(d.get("pos") or "", d.get("pos") or "")
            glosses = [g for g in (_gloss(s) for s in d.get("senses") or []) if g]
            for s in d.get("senses") or []:
                for target in s.get("form_of") or []:
                    t = lower_tr((target.get("word") or "").strip())
                    if t and t != word:
                        form_of.append((word, t))
            forms = {lower_tr(f.get("form") or "") for f in d.get("forms") or []}
            if not glosses and not forms:
                continue
            h = heads.setdefault(word, Headword(word))
            if glosses:
                h.senses.append((pos, glosses[:MAX_SENSES]))
            h.forms |= {f for f in forms if FORM.match(f) and f != word}
    for form, target in form_of:
        if target in heads:
            heads[target].forms.add(form)
    for word in [w for w, h in heads.items() if not h.senses]:
        del heads[word]         # a table of forms with no meaning of its own
    if words_wanted is not None:
        heads = {w: h for w, h in heads.items() if w in words_wanted}
    return heads


def lemmatizer(heads: Dict[str, Headword]) -> Lemmatizer:
    forms: Dict[str, str] = {}
    for h in heads.values():
        for f in h.forms:
            if f not in heads:
                forms.setdefault(f, h.word)
    return Lemmatizer(heads.keys(), forms)


def add_book_forms(heads: Dict[str, Headword], book_words: Iterable[str]) -> int:
    """The forms the reader's books use, each added to its headword; how
    many were new."""
    lem = lemmatizer(heads)
    added = 0
    for w in set(book_words):
        if w in heads:
            continue
        head = lem.lemma(w)
        if head and head in heads and w not in heads[head].forms:
            heads[head].forms.add(w)
            added += 1
    return added


# --- what Matbaa reads itself ---------------------------------------------------

def save_db(heads: Dict[str, Headword], path: str) -> None:
    tmp = path + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    con = sqlite3.connect(tmp)
    con.execute("CREATE TABLE headword (word TEXT PRIMARY KEY, senses TEXT)")
    con.execute("CREATE TABLE form (form TEXT, word TEXT)")
    con.executemany("INSERT INTO headword VALUES (?, ?)",
                    ((h.word, json.dumps(h.senses, ensure_ascii=False)) for h in heads.values()))
    con.executemany("INSERT INTO form VALUES (?, ?)", ((f, h.word) for h in heads.values() for f in h.forms))
    con.execute("CREATE INDEX form_index ON form (form)")
    con.commit()
    con.close()
    os.replace(tmp, path)


class Dictionary:
    """The words Matbaa looks up itself, from tr.db."""

    def __init__(self, path: Optional[str] = None):
        self.path = path or os.path.join(DATA_DIR, DB_FILE)
        self._con = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, check_same_thread=False)
        self._lem: Optional[Lemmatizer] = None

    def close(self) -> None:
        """Let go of tr.db (Windows will not replace a file held open)."""
        try:
            self._con.close()
        except sqlite3.Error:
            pass

    @staticmethod
    def available(path: Optional[str] = None) -> bool:
        return os.path.isfile(path or os.path.join(DATA_DIR, DB_FILE))

    def lemmatizer(self) -> Lemmatizer:
        if self._lem is None:
            heads = [r[0] for r in self._con.execute("SELECT word FROM headword")]
            forms = {f: w for f, w in self._con.execute("SELECT form, word FROM form")}
            self._lem = Lemmatizer(heads, forms)
        return self._lem

    def senses(self, headword: str) -> List[Tuple[str, List[str]]]:
        row = self._con.execute("SELECT senses FROM headword WHERE word = ?", (headword,)).fetchone()
        return [tuple(s) for s in json.loads(row[0])] if row else []

    def look_up(self, word: str) -> Optional[Tuple[str, List[Tuple[str, List[str]]]]]:
        """(headword, senses) for a word as a book prints it."""
        head = self.lemmatizer().lemma(word)
        if not head:
            return None
        senses = self.senses(head)
        return (head, senses) if senses else None


# --- the Kindle dictionary --------------------------------------------------------

_HTML_HEAD = ('<html xmlns:math="http://exslt.org/math" xmlns:svg="http://www.w3.org/2000/svg" '
              'xmlns:tl="https://kindlegen.s3.amazonaws.com/AmazonKindlePublishingGuidelines.pdf" '
              'xmlns:saxon="http://saxon.sf.net/" xmlns:xs="http://www.w3.org/2001/XMLSchema" '
              'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
              'xmlns:cx="https://kindlegen.s3.amazonaws.com/AmazonKindlePublishingGuidelines.pdf" '
              'xmlns:dc="http://purl.org/dc/elements/1.1/" '
              'xmlns:mbp="https://kindlegen.s3.amazonaws.com/AmazonKindlePublishingGuidelines.pdf" '
              'xmlns:mmc="https://kindlegen.s3.amazonaws.com/AmazonKindlePublishingGuidelines.pdf" '
              'xmlns:idx="https://kindlegen.s3.amazonaws.com/AmazonKindlePublishingGuidelines.pdf">'
              '<head><meta http-equiv="Content-Type" content="text/html; charset=utf-8"/>'
              '<style>h5{font-size:1em;margin:0} p{margin:0.1em 0} .pos{font-style:italic}</style></head>'
              '<body><mbp:frameset>\n')
_HTML_TAIL = "</mbp:frameset></body></html>\n"


def _entry(h: Headword, forms: List[str], show: bool = True) -> str:
    e = html.escape
    infl = "".join(f'<idx:iform value="{e(f)}"/>' for f in forms)
    orth = (f'<idx:orth value="{e(h.word)}"><h5>{e(h.word)}</h5>'
            + (f"<idx:infl>{infl}</idx:infl>" if infl else "") + "</idx:orth>")
    if not show:
        return f'<idx:entry name="default" scriptable="yes" spell="yes">{orth}</idx:entry>\n'
    body = []
    for pos, glosses in h.senses:
        items = " ".join(f"{i}. {e(g)}" if len(glosses) > 1 else e(g) for i, g in enumerate(glosses, 1))
        label = f'<span class="pos">{e(pos)}</span> ' if pos else ""
        body.append(f"<p>{label}{items}</p>")
    return (f'<idx:entry name="default" scriptable="yes" spell="yes">{orth}{"".join(body)}</idx:entry>'
            '<hr/>\n')


def _entries(heads: Dict[str, Headword]) -> Iterable[str]:
    for word in sorted(heads):
        h = heads[word]
        forms = sorted(h.forms)
        yield _entry(h, forms[:MAX_IFORMS])
        # the rest of a long table of forms, on entries that show nothing
        for k in range(MAX_IFORMS, len(forms), MAX_IFORMS):
            yield _entry(h, forms[k:k + MAX_IFORMS], show=False)


FRONT = """<html><head><meta http-equiv="Content-Type" content="text/html; charset=utf-8"/></head><body>
<h2>{title}</h2>
<p>{count} madde. Kelimeler ve anlamları Türkçe Vikisözlük'ten (tr.wiktionary.org), katkıda bulunanların emeği;
wiktextract ile çıkarılmış hâli kaikki.org/trwiktionary (döküm: {dump}).</p>
<p>Lisans: Creative Commons Atıf-AynıLisanslaPaylaş (CC BY-SA 4.0), Vikisözlük'ün lisansı.
Çekimli biçimlerin bir kısmı okurun kendi kitaplarından eklendi (Matbaa).</p>
</body></html>
"""


def write_source(heads: Dict[str, Headword], folder: str, dump: str = "") -> str:
    """The dictionary's OPF and HTML in `folder`; the OPF's path."""
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "front.html"), "w", encoding="utf-8") as f:
        f.write(FRONT.format(title=html.escape(TITLE), count=len(heads), dump=html.escape(dump or "?")))
    files: List[str] = []
    chunk: List[str] = []

    def flush():
        name = f"content{len(files) + 1:03d}.html"
        with open(os.path.join(folder, name), "w", encoding="utf-8") as fh:
            fh.write(_HTML_HEAD + "".join(chunk) + _HTML_TAIL)
        files.append(name)
        chunk.clear()

    for entry in _entries(heads):
        chunk.append(entry)
        if len(chunk) >= ENTRIES_PER_FILE:
            flush()
    if chunk or not files:
        flush()
    manifest = ['<item id="front" href="front.html" media-type="application/xhtml+xml"/>'] + [
        f'<item id="c{i}" href="{n}" media-type="application/xhtml+xml"/>' for i, n in enumerate(files, 1)]
    spine = ['<itemref idref="front"/>'] + [f'<itemref idref="c{i}"/>' for i in range(1, len(files) + 1)]
    opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package unique-identifier="uid">
<metadata>
<dc-metadata xmlns:dc="http://purl.org/metadata/dublin_core" xmlns:oebpackage="http://openebook.org/namespaces/oeb-package/1.0/">
<dc:Title>{html.escape(TITLE)}</dc:Title>
<dc:Language>tr</dc:Language>
<dc:Identifier id="uid">matbaa-turkce-sozluk</dc:Identifier>
<dc:Creator>Vikisözlük katkıcıları</dc:Creator>
<dc:Rights>CC BY-SA 4.0</dc:Rights>
<dc:Subject BASICCode="REF008000">Dictionaries</dc:Subject>
</dc-metadata>
<x-metadata>
<output encoding="utf-8"></output>
<DictionaryInLanguage>tr</DictionaryInLanguage>
<DictionaryOutLanguage>tr</DictionaryOutLanguage>
<DefaultLookupIndex>default</DefaultLookupIndex>
</x-metadata>
</metadata>
<manifest>
{chr(10).join(manifest)}
</manifest>
<spine>
{chr(10).join(spine)}
</spine>
<guide></guide>
</package>
"""
    path = os.path.join(folder, "sozluk.opf")
    with open(path, "w", encoding="utf-8") as f:
        f.write(opf)
    return path


def find_kindlegen() -> Optional[str]:
    """kindlegen, as Kindle Previewer installs it (or MATBAA_KINDLEGEN)."""
    candidates = [os.environ.get("MATBAA_KINDLEGEN", "")]
    for base in (os.environ.get("LOCALAPPDATA", ""), os.environ.get("ProgramFiles", ""),
                 os.environ.get("ProgramFiles(x86)", "")):
        if base:
            candidates.append(os.path.join(base, "Amazon", "Kindle Previewer 3", "lib", "fc", "bin", "kindlegen.exe"))
    return next((c for c in candidates if c and os.path.isfile(c)), None)


def compile_mobi(opf_path: str, out_name: str = DEVICE_NAME, timeout: int = 7200) -> Tuple[Optional[str], str]:
    """kindlegen run on the OPF: (the .mobi's path or None, kindlegen's
    report)."""
    kg = find_kindlegen()
    if not kg:
        return None, "kindlegen bulunamadı (Kindle Previewer 3 kurulu olmalı)."
    run = subprocess.run([kg, opf_path, "-c0", "-dont_append_source", "-o", out_name], cwd=os.path.dirname(opf_path),
                         capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    report = (run.stdout or "") + (run.stderr or "")
    out = os.path.join(os.path.dirname(opf_path), out_name)
    return (out if os.path.isfile(out) else None), report
