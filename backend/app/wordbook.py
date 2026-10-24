"""The Kelime Defteri: words looked up on the Kindle, into the vault.

Each word the reader looked up (app/vocab.py) becomes one line of one
note, "Kelime Defteri", beside the vault's "Açık Sorular": under the book it
came from, the word with its headword, its meaning from the Turkish
Wiktionary (labelled as such: neither the reader's words nor a model's),
the sentence it stood in and the printed page, where the book is one
Matbaa made.

The vault's rules hold (4 - Tam Notlar/AGENTS.md): a looked-up word is not
made a link (it is vocabulary, not a concept) unless the vault already has
a note or alias of that name; the note is only ever added to; a word
already in it is recognised by its mark and never written twice, and
whatever the reader wrote under a word stays.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import os
import re
from dataclasses import asdict, dataclass
from typing import Callable, Dict, List, Optional

from app.notebook import BookText, book_blocks, fold_ascii, same_book
from app.obsidian import DASHBOARD, FilePlan, _diff, _fingerprint, book_folder, find_book_note, link_for
from app.vocab import Lookup

NOTE_NAME = "Kelime Defteri"
MARK = "matbaa:kelime"
MARK_RE = re.compile(r"%% " + re.escape(MARK) + r" (w-[0-9a-f]+) %%")
SENTENCE = re.compile(r"[^.!?…]*[.!?…]+[\"”’»)]*|[^.!?…]+$")
MAX_SENTENCE = 280
MAX_MEANING = 160


@dataclass
class WordEntry:
    id: str
    word: str               # as the book prints it
    headword: Optional[str]
    meaning: Optional[str]  # from the Turkish Wiktionary
    sentence: str
    page: Optional[str]
    book: str               # the name the vault knows the book by
    book_note: Optional[str]
    added: str
    learnt: bool
    lang: str
    link: Optional[str] = None     # an existing vault note the word names

    def to_dict(self) -> Dict:
        return asdict(self)


def sentence_with(usage: str, word: str) -> str:
    """The sentence of the Kindle's passage that holds the word, kept short."""
    usage = " ".join((usage or "").split())
    target = fold_ascii(word)
    pick = usage
    for m in SENTENCE.finditer(usage):
        if target and target in fold_ascii(m.group(0)):
            pick = m.group(0).strip()
            break
    if len(pick) <= MAX_SENTENCE:
        return pick
    # a long sentence: twenty words either side of the word
    words = pick.split(" ")
    k = next((i for i, w in enumerate(words) if target and target in fold_ascii(w)), 0)
    lo, hi = max(0, k - 20), min(len(words), k + 21)
    return ("…" if lo else "") + " ".join(words[lo:hi]) + ("…" if hi < len(words) else "")


def _meaning(senses) -> Optional[str]:
    if not senses:
        return None
    pos, glosses = senses[0]
    text = "; ".join(glosses[:2])
    if len(text) > MAX_MEANING:
        text = text[:MAX_MEANING].rsplit(" ", 1)[0] + "…"
    return text


def entries(lookups: List[Lookup], projects: List[Dict], get_session: Callable, dictionary=None,
            vault: Optional[str] = None, settings: Optional[Dict] = None,
            index: Optional[Dict[str, str]] = None) -> List[WordEntry]:
    folder = book_folder(vault, settings) if vault and os.path.isdir(vault) else None
    texts: Dict[str, Optional[BookText]] = {}
    out: List[WordEntry] = []
    for lk in lookups:
        project = None
        scored = sorted(((same_book(lk.book, p.get("book_title") or ""), p) for p in projects), key=lambda t: -t[0])
        if scored and scored[0][0] >= 0.8:
            project = scored[0][1]
        note = None
        if folder:
            note = find_book_note(folder, lk.book) or (find_book_note(folder, project["book_title"]) if project else None)
        name = os.path.basename(note)[:-3] if note else (project["book_title"] if project else lk.book)
        sentence = sentence_with(lk.usage, lk.word)
        page = None
        if project:
            sid = project["session_id"]
            if sid not in texts:
                session = get_session(sid)
                texts[sid] = BookText(book_blocks(session)) if session else None
            text = texts[sid]
            placed = text.find(sentence) if text and sentence else None
            page = placed.page if placed else None
        headword = meaning = None
        if dictionary is not None and (lk.lang or "tr").startswith("tr"):
            found = dictionary.look_up(lk.word)
            if found:
                headword, senses = found
                meaning = _meaning(senses)
        link = None
        if index:
            target, exists = link_for(headword or lk.word, index)
            link = target if exists else None
        out.append(WordEntry(lk.id, lk.word, headword, meaning, sentence, page, name,
                             os.path.basename(note)[:-3] if note else None, lk.added, lk.learnt, lk.lang, link))
    return out


def line(e: WordEntry) -> str:
    """One word, as the note holds it."""
    head = f"[[{e.link}]]" if e.link else f"**{e.word}**"
    if e.headword and fold_ascii(e.headword) != fold_ascii(e.word):
        head += f" ({e.headword})"
    parts = [f"- {head}"]
    if e.meaning:
        parts.append(f" — *{e.meaning}* (Vikisözlük)")
    if e.sentence:
        word_re = re.compile(r"(?<!\w)(" + re.escape(e.word) + r")(?!\w)")
        sentence = word_re.sub(r"**\1**", e.sentence, count=1) if not e.link else e.sentence
        parts.append(f" · “{sentence}”")
    if e.page:
        parts.append(f" (s. {e.page})")
    parts.append(f" %% {MARK} {e.id} %%")
    return "".join(parts)


def ids_in(text: str) -> set:
    return set(MARK_RE.findall(text or ""))


def note_path(vault: str, settings: Optional[Dict] = None) -> str:
    """Beside the "Açık Sorular" page, wherever the reader keeps it."""
    folder = book_folder(vault, settings)
    for where in (vault, os.path.dirname(folder)):
        if os.path.isfile(os.path.join(where, DASHBOARD + ".md")):
            return os.path.join(where, NOTE_NAME + ".md")
    return os.path.join(os.path.dirname(folder), NOTE_NAME + ".md")


def new_note(today: str) -> str:
    return "\n".join([
        "---", "tags: []", f"Created: {today}", "Source:", "Discovered via:", "aliases: []", "---", "",
        "Kindle'da sözlükte baktığım kelimeler, geçtikleri cümle ve sayfayla. Anlamlar Türkçe Vikisözlük'ten.",
        "(Matbaa Okuma Defteri yeni kelimeleri kitabın başlığı altına ekler; yazdıklarıma dokunmaz.)", ""])


def _heading(e: WordEntry) -> str:
    return f"## [[{e.book_note}]]" if e.book_note else f"## {e.book}"


def _heading_key(text: str) -> str:
    return fold_ascii(re.sub(r"[\[\]#]", "", text))


def add_words(text: str, new: List[WordEntry]) -> str:
    """`text` with each new word added at the end of its book's section (a
    section made at the end of the note for a book it does not have yet)."""
    lines = text.replace("\r\n", "\n").split("\n")
    for e in new:
        key = _heading_key(_heading(e))
        at = next((i for i, ln in enumerate(lines) if ln.startswith("## ") and _heading_key(ln) == key), None)
        if at is None:
            while lines and not lines[-1].strip():
                lines.pop()
            lines += ["", _heading(e), "", line(e), ""]
            continue
        end = next((i for i in range(at + 1, len(lines)) if lines[i].startswith("#")), len(lines))
        last = end - 1
        while last > at and not lines[last].strip():
            last -= 1
        lines.insert(last + 1, line(e))
    out = "\n".join(lines)
    return out if out.endswith("\n") else out + "\n"


def plan(words: List[WordEntry], vault: str, settings: Optional[Dict] = None, include: Optional[set] = None,
         today: Optional[str] = None) -> Dict:
    """The note as it would be with the chosen words added; nothing is
    written here."""
    today = today or _dt.date.today().isoformat()
    path = note_path(vault, settings)
    exists = os.path.isfile(path)
    old = open(path, encoding="utf-8").read() if exists else ""
    there = ids_in(old)
    chosen = [w for w in words if w.id not in there and (include is None or w.id in include)]
    base = old if exists else new_note(today)
    text = add_words(base, chosen) if chosen else base
    fp = FilePlan(path, text, exists, _diff(old, text, path) if (chosen or not exists) else "",
                  _fingerprint(old) if exists else "")
    token = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
    return {"file": fp, "added": len(chosen), "already": len([w for w in words if w.id in there]), "token": token}


def write(fp: FilePlan) -> Dict[str, List[str]]:
    """Write what the reader saw; a note changed since, or one that
    appeared since, is left alone and reported."""
    if fp.exists:
        if not os.path.exists(fp.path) or _fingerprint(open(fp.path, encoding="utf-8").read()) != fp.base:
            return {"written": [], "conflicts": [fp.path]}
        if not fp.diff:
            return {"written": [], "conflicts": []}
    elif os.path.exists(fp.path):
        return {"written": [], "conflicts": [fp.path]}
    os.makedirs(os.path.dirname(fp.path), exist_ok=True)
    tmp = fp.path + ".matbaa-part"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(fp.text)
    os.replace(tmp, fp.path)
    return {"written": [fp.path], "conflicts": []}
