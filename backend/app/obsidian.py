"""A book's Kindle highlights written into the reader's Obsidian vault.

The vault has its own rules (its AGENTS.md, read from the vault itself);
what is written here follows them:

- a book note lives in "2 - Kaynak/Kitap", with the Basic Template's
  fields and the book's chapters as headings; a highlight is the quote,
  the reader's own note on it follows as ==…==, exactly as they write;
- the note is never rewritten: on a later sync only highlights it does
  not hold yet are added, under their chapter, and the reader's text —
  "Final Notes" and everything else — is left as it is;
- a word or two the reader highlighted to make a link becomes [[…]]; an
  existing note or alias is used when there is one, and a new concept
  gets only a 1–2 line placeholder in "6 - Tags", in the collapsed
  "Yardımcı bağlam · AI" box the vault reserves for machine context;
- the reader's questions ("nedir", "anlamadım", "yapay zekaya sor") are
  gathered at the top, each linked to its passage, in a region Matbaa
  marks as its own and may refresh.

Nothing is written without a plan the reader has seen: `plan_book`
returns the resulting files and a diff, `apply_plan` writes exactly that.
"""
from __future__ import annotations

import datetime as _dt
import difflib
import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Tuple

from app.clippings import BookClips, Highlight, fold
from app.notebook import Placement, fold_ascii, same_book, tidy_quote

SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".matbaa", "obsidian.json")
SKIP_DIRS = {".obsidian", ".trash", ".smart-env", ".git"}
# on ASCII-folded words: what a reader types on a Kindle when they mean to come back to it
QUESTION = re.compile(r"\?|\bnedir\b|ne demek|anlamad|anlayamad|kavrayamad|bilemed|yapay zeka|\bai\b|emin degil|"
                      r"acaba|arastir|kontrol et|sormak|\bsor\b|\bney\b|\bnasil\b|\bnasi\b|\bkim(dir|mis|miydi)\b|"
                      r"\bneci\w*|\bbi(r)? bak\b|\bbakilabilir\b|\bne ki\b|\bne(dir)? bu\b", re.I)
REGION_BEGIN = "%% matbaa:sorular %%"
REGION_END = "%% /matbaa:sorular %%"
FINAL_HEADING = re.compile(r"^#{1,6}\s*(final notes|son notlar|düşüncelerim)\s*$", re.I | re.M)
SHORT_WORDS = 4


# --- settings and the vault -------------------------------------------------------------

def default_vault() -> Optional[str]:
    """The vault Obsidian itself last opened."""
    cfg = os.path.join(os.environ.get("APPDATA", ""), "obsidian", "obsidian.json")
    try:
        vaults = json.load(open(cfg, encoding="utf-8")).get("vaults", {})
    except Exception:  # noqa: BLE001
        return None
    best = max(vaults.values(), key=lambda v: v.get("ts", 0), default=None)
    return best.get("path") if best else None


def load_settings() -> Dict:
    try:
        data = json.load(open(SETTINGS_FILE, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        data = {}
    data.setdefault("vault", default_vault())
    return data


def save_settings(data: Dict) -> Dict:
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump({k: data.get(k) for k in ("vault", "book_folder", "tags_folder")}, f, ensure_ascii=False, indent=2)
    return load_settings()


def _find_dir(root: str, *patterns: str) -> Optional[str]:
    """A folder by the words in its name: "2 - Kaynak" / "Kitap"."""
    here = root
    for pat in patterns:
        try:
            names = sorted(n for n in os.listdir(here) if os.path.isdir(os.path.join(here, n)))
        except OSError:
            return None
        hit = next((n for n in names if pat.lower() in n.lower()), None)
        if hit is None:
            return None
        here = os.path.join(here, hit)
    return here


def book_folder(vault: str, settings: Optional[Dict] = None) -> str:
    rel = (settings or {}).get("book_folder")
    if rel:
        return os.path.join(vault, rel)
    return _find_dir(vault, "kaynak", "kitap") or os.path.join(vault, "2 - Kaynak", "Kitap")


def tags_folder(vault: str, settings: Optional[Dict] = None) -> str:
    rel = (settings or {}).get("tags_folder")
    if rel:
        return os.path.join(vault, rel)
    return _find_dir(vault, "tags") or os.path.join(vault, "6 - Tags")


_ALIASES = re.compile(r"^aliases:\s*(.*?)(?=^\S|\Z)", re.S | re.M)


def _note_aliases(path: str) -> List[str]:
    try:
        with open(path, encoding="utf-8") as f:
            head = f.read(2000)
    except OSError:
        return []
    if not head.startswith("---"):
        return []
    fm = head.split("---", 2)[1] if head.count("---") >= 2 else ""
    m = _ALIASES.search(fm)
    if not m:
        return []
    raw = m.group(1)
    items = re.findall(r"^\s*-\s*(.+)$", raw, re.M) or [x for x in re.split(r"[,\[\]]", raw) if x.strip()]
    return [x.strip().strip("\"'") for x in items if x.strip().strip("\"'")]


def vault_index(vault: str) -> Dict[str, str]:
    """folded name or alias -> the note's name as Obsidian links it."""
    index: Dict[str, str] = {}
    for root, dirs, files in os.walk(vault):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if not f.endswith(".md"):
                continue
            name = f[:-3]
            index.setdefault(fold_ascii(name), name)
            for alias in _note_aliases(os.path.join(root, f)):
                index.setdefault(fold_ascii(alias), name)
    return index


def find_book_note(folder: str, title: str) -> Optional[str]:
    try:
        notes = [f for f in os.listdir(folder) if f.endswith(".md")]
    except OSError:
        return None
    scored = sorted(((same_book(title, f[:-3]), f) for f in notes), key=lambda t: -t[0])
    if scored and scored[0][0] >= 0.8:
        return os.path.join(folder, scored[0][1])
    return None


# --- links the reader made by highlighting a word ------------------------------------------

def _strip_term(text: str) -> str:
    t = tidy_quote(text).strip()
    t = t.strip(" \t\"'“”‘’«»()[].,;:!?")
    # a possessive or case ending after an apostrophe: "Lenin’in" -> "Lenin"
    t = re.sub(r"[’'][a-zçğıöşü]{1,5}$", "", t)
    return t.strip()


def is_link_highlight(text: str) -> bool:
    words = text.split()
    return 0 < len(words) <= SHORT_WORDS and len(_strip_term(text)) >= 3


def link_for(text: str, index: Dict[str, str]) -> Tuple[Optional[str], bool]:
    """(note name, exists) for a short highlight meant as a link, or (None,
    False) when it does not read as a name or term. An existing note or
    alias wins, also behind a Turkish case ending ("özel mülkiyetle" ->
    [[Özel Mülkiyet]]); a new one is made only of a term the book itself
    marks as one — capitalised or quoted, not a heading in capitals."""
    if not is_link_highlight(text):
        return None, False
    term = _strip_term(text)
    if re.search(r"[?!.:;,\"“”«»()]", term):
        return None, False                 # a sentence's pieces, not a name
    key = fold_ascii(term)
    if key in index:
        return index[key], True
    for k in range(1, 5):                     # a case ending the vault's name does not carry
        if len(key) - k >= 4 and key[:-k] in index:
            return index[key[:-k]], True
    # a new note only for what the book itself marks as a name or a term: a
    # quoted term, a single capitalised word, or a name in title case
    # ("Gezi Direnişi"); "Beklenti nesnesini çağırır" is a sentence's start
    words = term.split()
    quoted = bool(re.match(r"^\s*[\"“«'‘].+[\"”»'’]\s*[.,;:]?\s*$", tidy_quote(text)))
    titled = all(w[:1].isupper() for w in words) and not term.isupper()
    if quoted or titled:
        return term[:1].upper() + term[1:], False
    return None, False


# --- the note ----------------------------------------------------------------------------------

@dataclass
class Entry:
    highlight: Highlight
    placement: Optional[Placement]
    quote: str
    chapter: str
    subheading: Optional[str]
    link: Optional[str] = None
    link_exists: bool = False
    note_kind: Optional["NoteKind"] = None
    note_links: List[Tuple[str, bool]] = field(default_factory=list)   # (name, note exists)
    answer: Optional[str] = None                                         # brought back from ChatGPT

    @property
    def page(self) -> Optional[str]:
        return self.highlight.page


# --- what a note says it is: the Kindle sign language ---------------------------------------
# Typing on a Kindle is slow, so the first character of a note carries the
# reader's intent:  ? a question  ! my own idea  > links  * important.

@dataclass
class NoteKind:
    kind: str                       # "question" | "idea" | "link" | "important" | "plain"
    text: str                       # the note without its sign
    names: List[str] = field(default_factory=list)   # for "link": the names written after ">"


_SIGNS = {"?": "question", "!": "idea", ">": "link", "*": "important"}


def classify_note(note: Optional[str]) -> NoteKind:
    if not note or not note.strip():
        return NoteKind("plain", "")
    raw = note.strip()
    kind = _SIGNS.get(raw[0])
    if raw == "*":
        return NoteKind("important", "")
    if raw == "?":
        return NoteKind("question", "?")       # "I did not get this" with nothing more to say
    # "?!" or "!!!" alone is a reaction, not a sign
    if kind and len(raw) > 1 and raw[1] not in "?!*>":
        text = raw[1:].strip()
        if kind == "link":
            names = [n.strip(" .") for n in re.split(r"[,;]|\s+ve\s+|\n", text) if n.strip(" .")]
            return NoteKind("link", "", names[:8])
        return NoteKind(kind, text)
    if QUESTION.search(fold_ascii_keep_spaces(raw)):
        return NoteKind("question", raw)
    return NoteKind("plain", raw)


def is_question(note: Optional[str]) -> bool:
    return classify_note(note).kind == "question"


def is_idea(note: Optional[str]) -> bool:
    return classify_note(note).kind == "idea"


def resolve_name(name: str, index: Dict[str, str]) -> Tuple[str, bool]:
    """A name the reader wrote after ">" as the vault links it: an existing
    note or alias (also behind a Turkish case ending), else as written."""
    key = fold_ascii(name)
    if key in index:
        return index[key], True
    for k in range(1, 5):
        if len(key) - k >= 4 and key[:-k] in index:
            return index[key[:-k]], True
    return name[:1].upper() + name[1:], False


def fold_ascii_keep_spaces(text: str) -> str:
    return " ".join(fold_ascii(w) for w in text.split()) + (" ?" if "?" in text else "")


def entries_for(book: BookClips, placements: Dict[str, Optional[Placement]], index: Dict[str, str],
                dropped: Optional[set] = None, link_choice: Optional[Dict[str, Optional[str]]] = None,
                answers: Optional[Dict[str, str]] = None) -> List[Entry]:
    out: List[Entry] = []
    dropped = dropped or set()
    link_choice = link_choice or {}
    for h in book.highlights:
        if h.id in dropped:
            continue
        p = placements.get(h.id)
        quote = p.quote if p and p.quote else tidy_quote(h.text)
        chapter = (p.chapter_title if p else None) or h.section or "Vurgular"
        e = Entry(h, p, quote, chapter, p.subheading if p else None)
        e.note_kind = classify_note(h.note)
        e.note_links = [resolve_name(n, index) for n in e.note_kind.names]
        e.answer = (answers or {}).get(h.id)
        if h.text:
            if h.id in link_choice:
                e.link = link_choice[h.id] or None
                e.link_exists = bool(e.link and fold_ascii(e.link) in index)
            else:
                e.link, e.link_exists = link_for(h.text, index)
        out.append(e)
    return out


def _page_ref(e: Entry) -> str:
    return f"s. {e.page}" if e.page else "pasaj"


def _quote_line(e: Entry) -> str:
    q = e.quote
    if e.link:
        term = _strip_term(q)
        if fold_ascii(term) == fold_ascii(e.link) and term in q:
            q = q.replace(term, f"[[{e.link}]]", 1)
        else:
            q = f"{q} [[{e.link}]]" if fold_ascii(term) != fold_ascii(e.link) else q.replace(term, f"[[{e.link}|{term}]]", 1)
    if e.note_kind and e.note_kind.kind == "important":
        q = f"**{q}**"
    page = f" (s. {e.page})" if e.page else ""
    return f"{q}{page} ^{e.highlight.id}"


def _note_block(note: str) -> str:
    return "\n\n".join(f"=={p.strip()}==" for p in note.split("\n\n") if p.strip())


def note_markdown(e: Entry) -> str:
    """The reader's note as their vault writes it: ==…== for a remark or a
    question, **Ben:** for their own idea (the vault's own form), and the
    names after ">" as links."""
    kind = e.note_kind or classify_note(e.highlight.note)
    if kind.kind == "link":
        return "→ " + " · ".join(f"[[{name}]]" for name, _ in e.note_links) if e.note_links else ""
    if not kind.text:
        return ""
    if kind.kind == "idea":
        return "\n\n".join(f"**Ben:** {p.strip()}" if i == 0 else p.strip()
                           for i, p in enumerate(kind.text.split("\n\n")) if p.strip())
    return _note_block(kind.text)


ANSWER_MARK = "matbaa:yanit"


def answer_block(highlight_id: str, text: str) -> str:
    """An answer the reader brought back (from ChatGPT or a configured
    model) in the box the vault reserves for machine context: collapsed,
    titled "Yardımcı bağlam · AI", italic where the text allows, and marked
    so the next sync recognises it instead of adding it again."""
    lines = ["> [!quote]- *Yardımcı bağlam · AI*"]
    for para in [p.strip() for p in text.strip().split("\n\n") if p.strip()]:
        for i, line in enumerate(para.splitlines()):
            line = line.rstrip()
            plain = "*" not in line and not re.match(r"^\s*([-+]|\d+[.)]|#)", line)
            lines.append(f"> *{line}*" if plain and line else f"> {line}")
        lines.append(">")
    lines.append(f"> %% {ANSWER_MARK} {highlight_id} %%")
    return "\n".join(lines)


def entry_markdown(e: Entry) -> str:
    parts = []
    if e.highlight.text:
        parts.append(_quote_line(e))
    if e.highlight.note:
        block = note_markdown(e)
        if block:
            parts.append(block)
    if e.answer:
        parts.append(answer_block(e.highlight.id, e.answer))
    return "\n\n".join(parts)


_NOTE_LINE = ("==", "**Ben:**", "→ [[")
_EXPORT_LABELS = {"note", "**note**", "==**note**==", "highlight (yellow)", "**highlight (yellow)**"}


def _past_notes(lines: List[str], at: int) -> int:
    """The last line of the reader's note(s) right under line `at`: ==…==,
    **Ben:**, → [[…]], and the export's "Note" labels, blank lines between."""
    j = at + 1
    while j < len(lines):
        s = lines[j].strip()
        if not s:
            j += 1
            continue
        if s.startswith(_NOTE_LINE) or s.lower() in _EXPORT_LABELS:
            at = j
            j += 1
            continue
        break
    return at


def _pasted_note_line(lines: List[str], e: Entry) -> Optional[int]:
    """The line of a pasted-in note (no block id) that holds the reader's
    note on this passage. A short note ("ne demek") can stand under many
    passages, so a line counts only when the passage itself is just above
    it; with several such lines and none of them under the passage, the
    answer is not placed rather than guessed."""
    key = fold(classify_note(e.highlight.note).text or e.highlight.note or "")
    if len(key) < 3:
        return None
    hits = [i for i, line in enumerate(lines) if key in fold(line)]
    head = fold(e.highlight.text)[:5] if e.highlight.text else ""
    near = [i for i in hits if head and any(head in fold(lines[k]) for k in range(max(0, i - 6), i))]
    if near:
        return near[0]
    return hits[0] if len(hits) == 1 and not head else None


_ANSWER_BLOCK = re.compile(r"^> \[!quote\]-[^\n]*\n(?:>[^\n]*\n)*?> %% " + re.escape(ANSWER_MARK) + r" (h-[0-9a-f]{6}) %%[ \t]*$",
                           re.M)


def place_answers(text: str, entries: List[Entry]) -> Tuple[str, int]:
    """Answers into a note that already holds their passages: a changed
    answer replaces its box, a new one goes after the passage (found by
    its block id) and the reader's note under it — or, for a passage pasted
    in without an id, after the reader's note line. Returns the text and
    how many answers were placed."""
    placed = 0
    existing = {m.group(1): m for m in _ANSWER_BLOCK.finditer(text)}
    for e in entries:
        if not e.answer:
            continue
        hid = e.highlight.id
        block = answer_block(hid, e.answer)
        if hid in existing:
            m = _ANSWER_BLOCK.search(text, 0)
            while m and m.group(1) != hid:
                m = _ANSWER_BLOCK.search(text, m.end())
            if m and m.group(0) != block:
                text = text[:m.start()] + block + text[m.end():]
                placed += 1
            continue
        lines = text.split("\n")
        at = None
        for i, line in enumerate(lines):
            if line.rstrip().endswith(f"^{hid}"):
                at = i
                break
        if at is None and e.highlight.note:
            at = _pasted_note_line(lines, e)
        if at is None:
            continue
        at = _past_notes(lines, at)
        lines[at + 1:at + 1] = ["", block]
        text = "\n".join(lines)
        placed += 1
    return text, placed


def _question_key(e: Entry) -> str:
    return e.highlight.id


def answered_questions(note_text: str) -> set:
    """Questions the reader ticked off in the note's region: the region is
    rebuilt on every sync, the ticks are kept. A question is recognised by
    its passage's block id, or, without one, by its words."""
    if REGION_BEGIN not in note_text or REGION_END not in note_text:
        return set()
    region = note_text[note_text.index(REGION_BEGIN):note_text.index(REGION_END)]
    done = set()
    for line in region.splitlines():
        m = re.match(r"^\s*-\s*\[[xX]\]\s*(.*)$", line)
        if not m:
            continue
        ref = re.search(r"\^(h-[0-9a-f]{6})", m.group(1))
        done.add(ref.group(1) if ref else fold(m.group(1).split(" — ")[0]))
    return done


def questions_region(entries: List[Entry], note_text: Optional[str] = None, done: Optional[set] = None) -> str:
    """The reader's questions as boxes to tick once answered, each linked to
    its passage — only where the passage carries Matbaa's block id; a
    passage pasted in earlier without one is named by its page, never given
    a link that leads nowhere. Open boxes across all book notes are what the
    "Açık Sorular" page gathers."""
    qs = [e for e in entries if is_question(e.highlight.note)]
    if not qs:
        return ""
    done = done or set()
    lines = [REGION_BEGIN, "## Sorularım", ""]
    for e in qs:
        note = " ".join(classify_note(e.highlight.note).text.split())
        note = note if len(note) <= 140 else note[:137] + "…"
        linkable = e.highlight.text and (note_text is None or f"^{e.highlight.id}" in note_text)
        target = f"[[#^{e.highlight.id}|{_page_ref(e)}]]" if linkable else _page_ref(e)
        tick = "x" if (e.highlight.id in done or fold(note) in done) else " "
        lines.append(f"- [{tick}] {note} — {target}")
    lines += ["", REGION_END]
    return "\n".join(lines)


IDEAS_BEGIN = "%% matbaa:fikirler %%"
IDEAS_END = "%% /matbaa:fikirler %%"


def ideas_region(entries: List[Entry], note_text: Optional[str] = None) -> str:
    """The reader's own ideas ("!" notes) listed at the top, each linked to
    the passage that set it off — the seeds of their own notes."""
    ideas = [e for e in entries if is_idea(e.highlight.note)]
    if not ideas:
        return ""
    lines = [IDEAS_BEGIN, "## Fikirlerim", ""]
    for e in ideas:
        text = " ".join(classify_note(e.highlight.note).text.split())
        text = text if len(text) <= 160 else text[:157] + "…"
        linkable = e.highlight.text and (note_text is None or f"^{e.highlight.id}" in note_text)
        target = f"[[#^{e.highlight.id}|{_page_ref(e)}]]" if linkable else _page_ref(e)
        lines.append(f"- {text} — {target}")
    lines += ["", IDEAS_END]
    return "\n".join(lines)


def _set_region(text: str, begin: str, end: str, region: str, after: Optional[str] = None) -> str:
    """Put Matbaa's own region in the note, replacing the old one; a new one
    goes after `after` (another region's end marker) or after the front
    matter. Nothing outside the markers is touched."""
    if begin in text and end in text:
        a, b = text.index(begin), text.index(end) + len(end)
        return text[:a] + region + text[b:] if region else text[:a].rstrip("\n") + "\n" + text[b:].lstrip("\n")
    if not region:
        return text
    if after and after in text:
        at = text.index(after) + len(after)
        return text[:at] + "\n\n" + region + text[at:]
    if text.startswith("---") and text.count("---") >= 2:
        end_fm = text.index("---", 3) + 3
        return text[:end_fm] + "\n\n" + region + "\n" + text[end_fm:]
    return region + "\n\n" + text


DASHBOARD = "Açık Sorular"
IDEAS_PAGE = "Fikirlerim"


def dashboard_note(book_folder_rel: str, today: str) -> str:
    """One page for every open question in the book notes. It is an Obsidian
    search embedded in the note (a core feature, no plugin): ticking a
    question in its book note takes it off this page."""
    path = book_folder_rel.replace("\\", "/")
    return "\n".join([
        "---", "tags: []", f"Created: {today}", "Source:", "Discovered via:", "aliases: []", "---", "",
        "Kitap notlarındaki, henüz yanıtlanmamış sorularım. Bir soruyu yanıtladığımda kitabın notunda kutusunu",
        "işaretliyorum; buradan kalkıyor. (Matbaa Okuma Defteri bu sayfayı bir kez açtı, sonra dokunmaz.)", "",
        "```query", f'task-todo:"" path:"{path}"', "```", ""])


def ideas_page(book_folder_rel: str, today: str) -> str:
    """Every idea of mine written under a book passage ("**Ben:**"), on one
    page, by Obsidian's own search."""
    path = book_folder_rel.replace("\\", "/")
    return "\n".join([
        "---", "tags: []", f"Created: {today}", "Source:", "Discovered via:", "aliases: []", "---", "",
        "Kitap okurken aklıma gelen kendi fikirlerim (Kindle'da “!” ile başlayan notlar). Gelişmeye değer olanı",
        "“3 - Gelişen Notlar”a taşıyorum. (Matbaa Okuma Defteri bu sayfayı bir kez açtı, sonra dokunmaz.)", "",
        "```query", f'"**Ben:**" path:"{path}"', "```", ""])


def frontmatter(book: BookClips, today: str) -> str:
    author = book.author if book.author and book.author.lower() not in ("bilinmiyor", "bilinmeyen yazar", "unknown") else ""
    return "\n".join(["---", "tags:", "  - Kitap", f"Created: {today}", "Source:",
                      f"Author: {author}" if author else "Author:", "aliases:", "Discovered via:", "---"])


def _sections(entries: List[Entry]) -> List[Tuple[str, List[Entry]]]:
    out: List[Tuple[str, List[Entry]]] = []
    for e in entries:
        if not out or out[-1][0] != e.chapter:
            out.append((e.chapter, []))
        out[-1][1].append(e)
    return out


def _section_markdown(entries: List[Entry]) -> str:
    chunks, sub = [], None
    for e in entries:
        if e.subheading and e.subheading != sub:
            chunks.append(f"### {e.subheading}")
            sub = e.subheading
        chunks.append(entry_markdown(e))
    return "\n\n".join(chunks)


def new_note(book: BookClips, entries: List[Entry], today: str) -> str:
    parts = [frontmatter(book, today)]
    for region in (questions_region(entries), ideas_region(entries)):
        if region:
            parts.append(region)
    for chapter, items in _sections(entries):
        parts.append(f"## {chapter}\n\n{_section_markdown(items)}")
    parts.append("# Final Notes\n")
    return "\n\n".join(parts) + "\n"


ALREADY_SIMILARITY = 0.85      # a passage in the note spelled a little differently is still the passage


def _already_in(note_folded: str, note_text: str, e: Entry) -> bool:
    h = e.highlight
    if f"^{h.id}" in note_text:
        return True
    probe = h.text or h.note or ""
    key = fold(probe)
    if not key:
        return True
    if not h.text and h.note_original and fold(h.note_original) in note_folded:
        return True                     # a standalone note, pasted in before the reader corrected it
    if len(key) >= 12:
        if key in note_folded or fold(tidy_quote(probe)) in note_folded:
            return True
        # the notes export and My Clippings can spell one passage a little
        # differently ("gerek tiğine" / "gerektiğine"): either end finds where
        # it would be, and the whole of it must read nearly the same there.
        # An end alone was taken for the passage, and a highlight that only
        # began like one already in the note ("Not açıldıktan sonra …") was
        # never added.
        if len(key) >= 40:
            for part, from_start in ((key[:18], True), (key[-18:], False)):
                at = note_folded.find(part)
                while at >= 0:
                    start = at if from_start else max(0, at + len(part) - len(key))
                    window = note_folded[start:start + len(key)]
                    if difflib.SequenceMatcher(None, key, window, autojunk=False).ratio() >= ALREADY_SIMILARITY:
                        return True
                    at = note_folded.find(part, at + 1)
        return False
    # a word or two: present as a word of its own, quoted, linked or plain
    term = _strip_term(probe)
    return bool(term) and bool(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", note_text, re.I))


def missing_from(existing: str, entries: List[Entry]) -> List[Entry]:
    folded = fold(existing)
    return [e for e in entries if not _already_in(folded, existing, e)]


def update_note(existing: str, entries: List[Entry], add: List[Entry]) -> str:
    """`existing` with the entries in `add` placed under their chapter (or
    in a new chapter section before "Final Notes"), and the questions region
    refreshed from all `entries`. Nothing the reader wrote is changed."""
    new = add
    text = existing.replace("\r\n", "\n")

    for chapter, items in _sections(new):
        block = _section_markdown(items)
        heading = re.search(r"^##\s+" + re.escape(chapter) + r"\s*$", text, re.M | re.I)
        if heading:
            nxt = re.compile(r"^#{1,2}\s", re.M).search(text, heading.end())
            at = nxt.start() if nxt else len(text)
            text = text[:at].rstrip("\n") + "\n\n" + block + "\n\n" + text[at:].lstrip("\n")
        else:
            final = FINAL_HEADING.search(text)
            at = final.start() if final else len(text)
            text = text[:at].rstrip("\n") + f"\n\n## {chapter}\n\n{block}\n\n" + text[at:].lstrip("\n")

    text, _ = place_answers(text, entries)
    text = _set_region(text, REGION_BEGIN, REGION_END, questions_region(entries, text, answered_questions(text)))
    text = _set_region(text, IDEAS_BEGIN, IDEAS_END, ideas_region(entries, text), after=REGION_END)
    if not text.endswith("\n"):
        text += "\n"
    return text


def placeholder_note(name: str, book_note: str, context: str, today: str) -> str:
    context = " ".join(context.split())
    if len(context) > 140:
        context = context[:137] + "…"
    line = f"İlk karşılaşma: [[{book_note}]]" + (f" — “{context}”" if context else "")
    return "\n".join(["---", "tags: []", f"Created: {today}", "Source:", "Discovered via:", "aliases: []", "---",
                      "", "> [!quote]- *Yardımcı bağlam · AI*", f"> *{line}*", ""])


def _sentence_with(text: str, term: str) -> Optional[str]:
    """The sentence of `text` that names `term`, roughly."""
    i = fold_ascii(text).find(fold_ascii(term))
    if i < 0:
        return None
    at = min(len(text) - 1, int(i * len(text) / max(1, len(fold_ascii(text)))))
    start = max(0, max(text.rfind(".", 0, at), text.rfind("?", 0, at), text.rfind("!", 0, at)) + 1)
    stop = min([p for p in (text.find(".", at), text.find("?", at), text.find("!", at)) if p >= 0] or [len(text) - 1])
    return text[start:stop + 1].strip()


def _context(e: Entry, entries: List[Entry]) -> str:
    """Where the term was met: its sentence in the book, or in a longer
    highlight of the same passage, or the reader's own note on it."""
    term = _strip_term(e.highlight.text)
    if e.placement and e.placement.paragraph:
        return _sentence_with(e.placement.paragraph, term) or ""
    for other in entries:
        if other is not e and len(other.quote) > len(e.quote) + 10:
            found = _sentence_with(other.quote, term)
            if found:
                return found
    return e.highlight.note or ""


# --- plan, then write ------------------------------------------------------------------------------

@dataclass
class FilePlan:
    path: str
    text: str
    exists: bool
    diff: str = ""
    base: str = ""         # fingerprint of the file the plan was made from


def _fingerprint(text: str) -> str:
    return hashlib.sha1(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


@dataclass
class BookPlan:
    note: FilePlan
    added: int
    already: int
    placeholders: List[FilePlan] = field(default_factory=list)
    links: List[Dict] = field(default_factory=list)
    questions: int = 0
    ideas: int = 0
    answers: int = 0          # answers in the note after this write
    # highlights made before the note was started that it does not hold:
    # most likely ones the reader deleted on the Kindle (My Clippings keeps
    # them), so they are offered, not added
    held_back: List[Dict] = field(default_factory=list)
    pages: List[FilePlan] = field(default_factory=list)   # the "Açık Sorular" page, made once
    token: str = ""

    def to_dict(self) -> Dict:
        return asdict(self)


def _diff(old: str, new: str, path: str) -> str:
    return "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                        fromfile=os.path.basename(path), tofile=os.path.basename(path), n=2))


def _safe_name(name: str) -> str:
    name = name.replace(": ", " - ")
    return " ".join(re.sub(r'[\\/:*?"<>|#^\[\]]', " ", name).split())


def _created(note_text: str):
    m = re.search(r"^Created:\s*(\d{4})-(\d{2})-(\d{2})", note_text, re.M)
    if not m:
        return None
    try:
        return _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def plan_book(book: BookClips, placements: Dict[str, Optional[Placement]], vault: str,
              settings: Optional[Dict] = None, dropped: Optional[set] = None,
              link_choice: Optional[Dict[str, Optional[str]]] = None, include: Optional[set] = None,
              today: Optional[str] = None, answers: Optional[Dict[str, str]] = None) -> BookPlan:
    from app.clippings import parse_added

    today = today or _dt.date.today().isoformat()
    include = include or set()
    index = vault_index(vault)
    entries = entries_for(book, placements, index, dropped, link_choice, answers)
    folder = book_folder(vault, settings)
    path = find_book_note(folder, book.title) or os.path.join(folder, _safe_name(book.title) + ".md")
    book_note = os.path.basename(path)[:-3]

    # highlights older than the note that the note lacks: offered, held back
    # unless the reader ticks them — and still listed once ticked, so the
    # tick stays where the reader put it
    older: List[Entry] = []
    if os.path.exists(path):
        old = open(path, encoding="utf-8").read()
        missing = missing_from(old, entries)
        started = _created(old)
        if started:
            for e in missing:
                made = parse_added(e.highlight.added) if e.highlight.added else None
                if made and made < started:
                    older.append(e)
    held = [e for e in older if e.highlight.id not in include]
    if os.path.exists(path):
        add = [e for e in missing if e not in held]
        shown = [e for e in entries if e not in held]
        text = update_note(old, shown, add)
        note = FilePlan(path, text, True, _diff(old, text, path), _fingerprint(old))
        already = len(entries) - len(missing)
    else:
        add = entries
        text = new_note(book, entries, today)
        note = FilePlan(path, text, False, _diff("", text, path))
        already = 0

    placeholders, links, seen = [], [], set()
    tags = tags_folder(vault, settings)
    def placeholder(name: str, e: "Entry") -> None:
        key = fold_ascii(name)
        if key in seen or key in index:
            return
        seen.add(key)
        ppath = os.path.join(tags, _safe_name(name) + ".md")
        if not os.path.exists(ppath):
            ptext = placeholder_note(name, book_note, _context(e, entries), today)
            placeholders.append(FilePlan(ppath, ptext, False, _diff("", ptext, ppath)))

    for e in add:                      # links of what is being added now, nothing older
        if e.link:
            links.append({"id": e.highlight.id, "text": e.highlight.text, "link": e.link, "exists": e.link_exists})
            if not e.link_exists:
                placeholder(e.link, e)
        for name, exists in e.note_links:      # names the reader wrote after ">"
            links.append({"id": e.highlight.id, "text": e.highlight.note, "link": name, "exists": exists})
            if not exists:
                placeholder(name, e)

    questions = sum(1 for e in entries if is_question(e.highlight.note) and e not in held)
    answered = sum(1 for e in entries if e.answer and f"{ANSWER_MARK} {e.highlight.id}" in note.text)
    ideas = sum(1 for e in entries if is_idea(e.highlight.note) and e not in held)
    pages: List[FilePlan] = []
    rel = os.path.relpath(folder, vault)
    for wanted, name, make in ((questions, DASHBOARD, dashboard_note), (ideas, IDEAS_PAGE, ideas_page)):
        dpath = os.path.join(os.path.dirname(folder), name + ".md")
        if wanted and not os.path.exists(dpath):
            dtext = make(rel, today)
            pages.append(FilePlan(dpath, dtext, False, _diff("", dtext, dpath)))

    plan = BookPlan(note=note, added=len(add), already=already, placeholders=placeholders, links=links,
                    questions=questions, ideas=ideas, answers=answered, pages=pages,
                    held_back=[{"id": e.highlight.id, "text": e.highlight.text, "note": e.highlight.note,
                                "added": e.highlight.added, "included": e not in held} for e in older])
    plan.token = hashlib.sha1((note.text + "".join(p.text for p in placeholders + pages))
                              .encode("utf-8")).hexdigest()[:16]
    return plan


def apply_plan(plan: BookPlan) -> Dict[str, List[str]]:
    """Write what the reader saw in the plan. A note the reader changed
    since the plan was made, or a file that appeared since, is left alone
    and reported."""
    written, conflicts = [], []
    for fp in [plan.note] + plan.placeholders + plan.pages:
        if fp.exists:
            if not os.path.exists(fp.path) or _fingerprint(open(fp.path, encoding="utf-8").read()) != fp.base:
                conflicts.append(fp.path)
                continue
            if not fp.diff:
                continue                  # nothing new for this note
        elif os.path.exists(fp.path):
            conflicts.append(fp.path)
            continue
        os.makedirs(os.path.dirname(fp.path), exist_ok=True)
        tmp = fp.path + ".matbaa-part"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(fp.text)
        os.replace(tmp, fp.path)
        written.append(fp.path)
    return {"written": written, "conflicts": conflicts}


# --- where a concept was met before -----------------------------------------------------------------

_WIKILINK = re.compile(r"\[\[([^\]|#^]+)")


def encounters(vault: str, settings: Optional[Dict] = None) -> Dict[str, List[str]]:
    """folded note name -> the book notes that link to it. Shown in review
    as "daha önce: …"; never written into a note (the vault's rule: a second
    encounter is not added by default)."""
    folder = book_folder(vault, settings)
    out: Dict[str, List[str]] = {}
    try:
        names = sorted(f for f in os.listdir(folder) if f.endswith(".md"))
    except OSError:
        return out
    for f in names:
        try:
            with open(os.path.join(folder, f), encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            continue
        for target in {m.strip() for m in _WIKILINK.findall(text)}:
            out.setdefault(fold_ascii(target), []).append(f[:-3])
    return out


# --- an idea grown into its own note ------------------------------------------------------------------

def developing_folder(vault: str, settings: Optional[Dict] = None) -> str:
    rel = (settings or {}).get("developing_folder")
    if rel:
        return os.path.join(vault, rel)
    return _find_dir(vault, "gelişen") or _find_dir(vault, "gelisen") or os.path.join(vault, "3 - Gelişen Notlar")


def _idea_name(text: str) -> str:
    words = re.sub(r"\s+", " ", text).strip().split(" ")
    name = " ".join(words[:7]).rstrip(" .,;:!?")
    return _safe_name(name[:1].upper() + name[1:]) or "Fikir"


def develop_plan(book: BookClips, highlight: Highlight, book_note: str, vault: str,
                 settings: Optional[Dict] = None, today: Optional[str] = None,
                 note_has_block: bool = False) -> FilePlan:
    """A new note in "3 - Gelişen Notlar" for one of the reader's "!" ideas:
    their words, the passage that set them off, and a link back to it. Only
    what the reader wrote and the passage itself — the vault's rule is that
    their own notes are theirs to grow, never summarised for them."""
    today = today or _dt.date.today().isoformat()
    idea = classify_note(highlight.note).text or (highlight.note or "")
    folder = developing_folder(vault, settings)
    base = _idea_name(idea)
    path = os.path.join(folder, base + ".md")
    k = 2
    while os.path.exists(path):
        path = os.path.join(folder, f"{base} ({k}).md")
        k += 1
    target = f"{book_note}#^{highlight.id}" if note_has_block else book_note
    page = f", s. {highlight.page}" if highlight.page else ""
    lines = ["---", "tags: []", f"Created: {today}", f'Source: "[[{book_note}]]"', "Discovered via:", "aliases: []",
             "---", "", idea.strip(), ""]
    if highlight.text:
        quote = tidy_quote(highlight.text)
        lines += [f"> {quote}", f"> — [[{target}|{book_note}{page}]]", ""]
    text = "\n".join(lines)
    return FilePlan(path, text, False, _diff("", text, path))


def vault_problem(vault: Optional[str]) -> str:
    """Why the vault cannot be reached, said so the reader can fix it: a
    vault on a drive that is not there (Google Drive for desktop not running
    after a restart) is not the same as a wrong folder."""
    if not vault:
        return "Obsidian kasası seçilmedi; Okuma Defteri'nin üstündeki “değiştir”den kasanın klasörünü seçin."
    drive = os.path.splitdrive(vault)[0]
    if drive and not os.path.exists(drive + os.sep):
        return (f"Kasa {drive} sürücüsünde, ama {drive} sürücüsü şu an görünmüyor — Google Drive uygulaması kapalı "
                f"olabilir. Açıp birkaç saniye bekleyin, sonra tekrar deneyin.")
    return f"Obsidian kasası bulunamadı: {vault}. Klasör taşınmış olabilir; “değiştir”den yeniden seçin."
