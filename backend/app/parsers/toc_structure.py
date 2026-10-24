"""The book's own printed contents page, read as a tree.

A contents page is the book telling us its structure: which sections exist,
how they nest, what each is called and where it starts. Reading it as a flat
list of lines threw all of that away — the Kindle menu lost "Önsöz ›
İnce Buz, Steven Holl", chapter boundaries had to be guessed from type size
alone, and a title the scanner garbled on the chapter page ("Maddesel lik",
"l<aybı") had no second witness to be corrected against.

Everything here works on plain line records so it can be tested without a
PDF:

    {"text", "x0", "y0", "x1", "y1", "font", "size", "page"}

Three layouts are handled because three real books use them: page numbers
in their own right-hand column paired only by baseline; dot leaders with the
number on the title's own line; and indented sub-entries under an entry that
has no page number of its own. Titles that wrap onto a second line are
joined.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Sequence

BARE_NUMBER = re.compile(r"^\s*(\d{1,4})\s*$")
# A page number as a scanner reads it: "ı7", "2S", "S3", "7ı", "ll", "ıs".
# A capital I counts only beside a real digit, so a part's "II" stays a
# numeral rather than becoming page 11.
OCR_NUMBER = re.compile(r"^\s*[0-9ılSsOoI](?: ?[0-9ılSsOoI]){0,3}\s*$")
_OCR_DIGIT = str.maketrans({"ı": "1", "l": "1", "I": "1", "S": "5", "s": "5", "O": "0", "o": "0"})
# "3. Kautsky'nin Pannekoek'le Tartışması. 143": the number with no leader.
TRAILING_NUMBER = re.compile(r"^(\S+(?:\s+\S+){2,}?)\s+(\d{1,3})\s*$")


# Words a contents line set with no space between them:
# "KumandaÜstünlüğü:TemkinliSorumlulukGüvenidir." A word does not turn to
# a capital in its middle, so a lower-case letter followed by a capital,
# with three letters each side ("McCarthy" keeps its two), is two words.
GLUED_WORDS = re.compile(r"(?<=[^\W\d_]{3})(?<=[a-zçğıöşüâîû])(?=[A-ZÇĞİÖŞÜÂÎÛ][^\W\d_]{2})")
GLUED_COLON = re.compile(r"(?<=[^\W\d_]{2})([:;])(?=[^\W\d_])")
# an enumerator run into its title: "E)Tarih Filozofu"
GLUED_ENUMERATOR = re.compile(r"^((?:[A-ZÇĞİÖŞÜ]|[IVX]{1,4}|\d{1,2})\))(?=[^\W\d_])")


def unglue_words(text: str) -> str:
    text = GLUED_ENUMERATOR.sub(lambda m: m.group(1) + " ", text)
    return GLUED_COLON.sub(lambda m: m.group(1) + " ", GLUED_WORDS.sub(" ", text))


def _read_ocr_number(text: str) -> str:
    # a leader that the layer cut off from its title, number and all
    m = re.match(r"^[\s.·…•]{2,}(\d{1,4})\s*$", text)
    if m:
        return m.group(1)
    if not OCR_NUMBER.match(text):
        return text
    bare = text.replace(" ", "").strip()
    if not any(c.isdigit() for c in bare) and ("I" in bare or len(bare) < 2):
        return text
    return bare.translate(_OCR_DIGIT)
# "Title . . . . 17", "Title ....... 17", "Title …… 17"
LEADER_NUMBER = re.compile(r"^(.*?\S)\s*(?:[.·…•]\s*){2,}\s*(\d{1,4})\s*$")
# A leader whose page number the text layer put somewhere else — on its own
# line, or nowhere: "3. Şernaları Anlamak ......" became a chapter title
# with the dots still on it.
TRAILING_LEADER = re.compile(r"\s*(?:[.·…•]\s*){3,}$")
# The same leader with its number and a stray mark the layer set beside it,
# left inside a title that wrapped entries were joined into.
INNER_LEADER = re.compile(r"\s*(?:[.·…•]\s*){4,}(?:\d{1,4}\b)?\s*[,;:]?\s*")
TOC_TITLE = re.compile(
    r"^[\W_]*(İ|I|i|ı)?\s*[ÇC]\s*[İI]?\s*N\s*D\s*E\s*K", re.IGNORECASE
)
TOC_TITLE_WORDS = ("icindekiler", "contents", "tableofcontents")
# Back matter belongs to the book, not to the last part it happens to follow.
BACK_MATTER = re.compile(
    r"^\s*(dizin|kavram dizini|ad dizini|kaynak[cç]a|kaynaklar|bibliyografya|notlar|"
    r"s[oö]zl[uü]k|index|bibliography|notes|glossary|references|appendix|ekler?)\s*$",
    re.IGNORECASE,
)

_FOLD = str.maketrans({
    "İ": "i", "I": "i", "ı": "i", "Ş": "s", "ş": "s", "Ğ": "g", "ğ": "g",
    "Ü": "u", "ü": "u", "Ö": "o", "ö": "o", "Ç": "c", "ç": "c",
    "â": "a", "Â": "a", "î": "i", "û": "u",
})
_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def fold(text: str) -> str:
    """Casefold for comparison, with Turkish letters collapsed onto ASCII."""
    t = unicodedata.normalize("NFC", text or "").translate(_FOLD).lower()
    t = unicodedata.normalize("NFKD", t)
    return "".join(c for c in t if not unicodedata.combining(c))


def squash(text: str) -> str:
    """Letters and digits only — spacing and punctuation are the parts OCR
    and PyMuPDF get wrong, so matching must not depend on them."""
    return "".join(c for c in fold(text) if c.isalnum())


def words(text: str) -> List[str]:
    return _WORD.findall(fold(text))


@dataclass
class TocEntry:
    title: str
    printed_page: Optional[int]
    level: int
    # Titles of the enclosing labels / parent entries, outermost first.
    path: List[str] = field(default_factory=list)
    is_label: bool = False
    # The chapter number printed over this entry on its own line ("II."),
    # which numbers this entry only and groups nothing.
    number: Optional[str] = None


# A label that is only a number, as printed or as a scanner read it ("il."
# for "II.", "ııı." for "III.").
NUMBER_LABEL = re.compile(r"^\s*(?:[IVXLCDMivxlcdmıİ]{1,6}|\d{1,3})\s*[.):]?\s*$")
# Two labels in a row name one part: "BİRİNCİ KISIM" / "MEKANI MÜŞTEREKLEŞTİRMEK".
PART_JOIN = " — "


def tidy_number(text: str) -> str:
    """ "il." -> "II.", "vı." -> "VI.": a scanner's roman numeral, set right."""
    t = text.strip()
    if any(c.isdigit() for c in t):
        return t
    return t.translate(str.maketrans({"ı": "I", "l": "I", "i": "I", "İ": "I"})).upper()


def _reads_as_name(text: str) -> bool:
    """A person's name: two to four capitalised words and nothing else."""
    ws = text.split()
    return (2 <= len(ws) <= 4 and all(w[:1].isupper() and w[1:].replace(".", "").isalpha() for w in ws)
            and any(c.islower() for c in text))


def _same_row(a: dict, b: dict) -> bool:
    overlap = min(a["y1"], b["y1"]) - max(a["y0"], b["y0"])
    shortest = min(a["y1"] - a["y0"], b["y1"] - b["y0"])
    return shortest > 0 and overlap / shortest >= 0.5


def _is_toc_title(text: str) -> bool:
    s = squash(text)
    return any(s.startswith(w) or s.endswith(w) for w in TOC_TITLE_WORDS) and len(s) <= 20


def parse_printed_toc(lines: Sequence[dict], page_width: float) -> List[TocEntry]:
    """Turn the contents page(s) into an ordered list of entries with levels.

    Labels ("1. BÖLÜM", "Önsöz") are level 0 and carry no page. Numbered
    entries are one level below the last label (or level 0 if the book has
    no labels). An unnumbered line whose following lines are indented under
    it is a parent entry; its children sit one level deeper.
    """
    rows: List[dict] = []
    for page in sorted({ln["page"] for ln in lines}):
        on_page = sorted((dict(ln) for ln in lines if ln["page"] == page),
                         key=lambda ln: (ln["y0"], ln["x0"]))
        for ln in on_page:
            ln["text"] = _read_ocr_number(ln["text"])
        numbers = [ln for ln in on_page if BARE_NUMBER.match(ln["text"])]
        texts = [ln for ln in on_page if not BARE_NUMBER.match(ln["text"])]
        for ln in texts:
            ln["text"] = ln["text"].strip()
            ln["number"] = None
            m = LEADER_NUMBER.match(ln["text"])
            if m:
                ln["text"], ln["number"] = m.group(1).strip(), int(m.group(2))
            else:
                bare = TRAILING_LEADER.sub("", ln["text"]).strip()
                ln["leader"] = bare != ln["text"]
                ln["text"] = bare
                t = TRAILING_NUMBER.match(bare)
                if t and not ln["leader"]:
                    ln["text"], ln["number"] = t.group(1).strip(), int(t.group(2))
        # A number in its own right-hand column belongs to the text line it
        # shares a baseline with.
        for num in numbers:
            partner = next(
                (t for t in texts
                 if t["number"] is None and _same_row(t, num) and t["x1"] <= num["x0"] + 1),
                None,
            )
            if partner is not None:
                partner["number"] = int(BARE_NUMBER.match(num["text"]).group(1))
        for ln in texts:
            if not squash(ln["text"]) or _is_toc_title(ln["text"]):
                continue
            rows.append(ln)

    if not rows:
        return []

    numbered = [r for r in rows if r["number"] is not None]
    if not numbered:
        return []
    entry_style = Counter((r["font"], round(r["size"])) for r in numbered).most_common(1)[0][0]
    entry_x0 = Counter(round(r["x0"] / 4) * 4 for r in numbered).most_common(1)[0][0]
    entry_size = entry_style[1] or 1
    # The page's own heading, however the scanner spelled it: set well
    # above entry size and before the first numbered line.
    first_numbered = rows.index(numbered[0])
    rows = [
        r for k, r in enumerate(rows)
        if not (k < first_numbered and r["size"] >= entry_size * 1.4)
    ]

    def is_indented(r: dict, base: float) -> bool:
        return r["x0"] > base + entry_size * 0.9

    def looks_like_label(i: int, r: dict) -> bool:
        centre = (r["x0"] + r["x1"]) / 2
        centred = abs(centre - page_width / 2) < page_width * 0.12 and r["x0"] > entry_x0 + page_width * 0.15
        other_style = (r["font"], round(r["size"])) != entry_style
        return centred or other_style

    entries: List[TocEntry] = []
    labels: List[str] = []           # current label (level 0) — at most one deep
    parent: Optional[dict] = None    # current unnumbered parent entry row
    pending_wrap: List[str] = []
    pending_number: Optional[str] = None
    label_open = False               # the last row read was a label, nothing under it yet
    i = 0
    while i < len(rows):
        r = rows[i]
        nxt = rows[i + 1] if i + 1 < len(rows) else None
        if r["number"] is None:
            wraps = (
                nxt is not None
                and nxt["number"] is not None
                and abs(nxt["x0"] - r["x0"]) < entry_size
                and (nxt["y0"] - r["y1"]) < entry_size * 0.8
                and nxt["page"] == r["page"]
                and not looks_like_label(i, r)
            )
            parent_of_next = (
                nxt is not None
                and nxt["page"] == r["page"]
                and is_indented(nxt, r["x0"])
                and not looks_like_label(i, r)
            )
            if r.get("leader") and not looks_like_label(i, r):
                # dots run out to a number the layer lost: a whole entry,
                # never the first line of the next one
                title = " ".join(pending_wrap + [r["text"]])
                pending_wrap = []
                path = list(labels[:1]) + ([parent["text"]] if parent is not None else [])
                entries.append(TocEntry(title=title, printed_page=None, level=len(path), path=path))
            elif wraps:
                pending_wrap.append(r["text"])
            elif parent_of_next:
                parent = r
                path = labels[:1]
                entries.append(TocEntry(title=r["text"], printed_page=None,
                                        level=len(path), path=list(path)))
            elif NUMBER_LABEL.match(r["text"]):
                pending_number = r["text"]
                i += 1
                continue
            elif (nxt is not None and nxt["number"] is not None and _reads_as_name(nxt["text"])
                    and nxt["size"] < r["size"]):
                # a section with its author set under it ("Ön söz" / "Massimo
                # De Angelis"): one entry, the name its byline — not a label
                # every later entry would be filed under
                path = list(labels[:1])
                entries.append(TocEntry(title=f'{r["text"]}, {nxt["text"]}', printed_page=nxt["number"],
                                        level=len(path), path=path))
                label_open = False
                i += 2
                continue
            elif label_open and entries and entries[-1].is_label:
                merged = entries[-1].title + PART_JOIN + r["text"]
                entries[-1].title = merged
                labels = [merged]
            else:
                labels = [r["text"]]
                parent = None
                entries.append(TocEntry(title=r["text"], printed_page=None,
                                        level=0, path=[], is_label=True))
                label_open = True
                i += 1
                continue
            label_open = False
            i += 1
            continue

        title = " ".join(pending_wrap + [r["text"]])
        pending_wrap = []
        if parent is not None and not is_indented(r, parent["x0"]):
            parent = None
        if BACK_MATTER.match(title):
            labels, parent = [], None
        path = list(labels[:1])
        if parent is not None:
            path.append(parent["text"])
        entries.append(TocEntry(title=title, printed_page=r["number"],
                                level=len(path), path=path, number=pending_number))
        pending_number = None
        label_open = False
        i += 1

    for e in entries:
        title = INNER_LEADER.sub(" ", e.title).strip(" ,;:")
        # what a spaced leader leaves when only its first dot shared the line
        title = re.sub(r"\s+\.$", "", title)
        # a mark the scanner read off the leader ("Temsili ®")
        while title and unicodedata.category(title[-1]).startswith("S"):
            title = title[:-1].rstrip()
        e.title = unglue_words(title)

    # A parent entry starts where its first child starts.
    for k, e in enumerate(entries):
        if e.printed_page is None and not e.is_label:
            child = next((c for c in entries[k + 1:] if c.printed_page is not None), None)
            if child is not None:
                e.printed_page = child.printed_page
    return entries


def printed_page_offset(folios: Dict[int, int], min_share: float = 0.3) -> Optional[int]:
    """printed page number − PDF page index, if the book agrees on one.

    `folios` maps PDF page index → the number printed in that page's margin.
    """
    if not folios:
        return None
    counts = Counter(num - idx for idx, num in folios.items())
    offset, votes = counts.most_common(1)[0]
    return offset if votes >= max(3, min_share * len(folios)) else None


# ---------------------------------------------------------------------------
# Matching an entry to the text on its page
# ---------------------------------------------------------------------------
def split_author(title: str) -> (str, Optional[str]):
    """ "İnce Buz, Steven Holl" -> ("İnce Buz", "Steven Holl")."""
    if "," in title:
        head, tail = title.rsplit(",", 1)
        tail = tail.strip()
        # A person's name, not the rest of an all-caps title
        # ("… İKTİSAT, TEKNOLOJİ VE FİZİK").
        if (1 <= len(tail.split()) <= 4 and all(w[:1].isupper() for w in tail.split())
                and any(c.islower() for c in tail)):
            return head.strip(), tail
    return title, None


def match_prefix(block_text: str, title: str) -> Optional[int]:
    """How many squashed characters of `title` the block's text accounts for,
    counting the block as matching when it is (nearly) a prefix of the title
    or the title is (nearly) a prefix of the block. None if they differ."""
    b, t = squash(block_text), squash(title)
    if len(b) < 3 or len(t) < 3:
        return None
    if b == t or t.startswith(b) and len(b) >= min(8, len(t)):
        return len(b)
    if b.startswith(t):
        return len(t)
    n = min(len(b), len(t))
    if n >= 6 and SequenceMatcher(None, b[:n], t[:n]).ratio() >= 0.8:
        if abs(len(b) - len(t)) <= max(3, 0.25 * len(t)) or len(b) < len(t):
            return n
    return None


def cut_title(title: str, squashed_len: int) -> (str, str):
    """Split `title` after the character where its squashed form reaches
    `squashed_len` — the part a heading block printed, and the rest."""
    count = 0
    for idx, ch in enumerate(title):
        if squash(ch):
            count += len(squash(ch))
            if count >= squashed_len:
                end = idx + 1
                while end < len(title) and title[end] in ")]}\"'”’»":
                    end += 1
                return title[:end].strip(" ,;:-"), title[end:].strip(" ,;:-")
    return title.strip(), ""


# ---------------------------------------------------------------------------
# Repairing a title with the book's own vocabulary
# ---------------------------------------------------------------------------
@dataclass
class Vocabulary:
    uni: Counter
    bi: Counter
    # folded form -> how the book actually spells it, most often
    surface: Dict[str, str]


def build_vocabulary(texts: Sequence[str]) -> Vocabulary:
    uni: Counter = Counter()
    bi: Counter = Counter()
    spellings: Dict[str, Counter] = {}
    for text in texts:
        raw = _WORD.findall(unicodedata.normalize("NFC", text or ""))
        ws = [fold(w) for w in raw]
        uni.update(ws)
        bi.update(zip(ws, ws[1:]))
        for w, f in zip(raw, ws):
            spellings.setdefault(f, Counter())[w.lower() if not w[:1].isupper() else w[:1].lower() + w[1:]] += 1
    surface = {f: c.most_common(1)[0][0] for f, c in spellings.items()}
    return Vocabulary(uni=uni, bi=bi, surface=surface)


def _edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _recase(word: str, like: str) -> str:
    if like.isupper() and len(like) > 1:
        return word.upper() if not word.isupper() else word
    if like[:1].isupper():
        return word[:1].upper() + word[1:]
    return word


def vote_title(primary: str, witness: Optional[str], vocab: "Vocabulary") -> str:
    """Repair `primary` (the contents-page title, whose spacing is clean)
    word by word, using the chapter page's version and the book's own
    vocabulary as witnesses.

    A word is replaced only by something the book itself spells more often:
    the witness's version of that word, or — when both sources were misread
    the same way ("Steven Hali") — a word the book prints after the same
    preceding word, one or two letters away.
    """
    uni, bi = vocab.uni, vocab.bi
    raw = re.findall(r"\S+", primary)
    if not raw:
        return primary
    wit_words = words(witness or "")
    # Pair each title word with the page's word in the same place; a word
    # elsewhere in the page's title is not a reading of this one.
    own = [fold(re.sub(r"^\W+|\W+$", "", t)) for t in raw]
    aligned: Dict[int, str] = {}
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, own, wit_words, autojunk=False).get_opcodes():
        if tag in ("equal", "replace") and i2 - i1 == j2 - j1:
            for d in range(i2 - i1):
                aligned[i1 + d] = wit_words[j1 + d]
    out: List[str] = []
    prev_fold: Optional[str] = None
    prev_is_name = False
    for pos, tok in enumerate(raw):
        m = re.match(r"^(\W*)(.*?)(\W*)$", tok, re.UNICODE)
        lead, core, trail = m.group(1), m.group(2), m.group(3)
        fc = fold(core)
        # Only plain words are repaired. A word with an apostrophe or hyphen
        # inside ("HESSEN'İN") is split differently by the vocabulary, and a
        # word of three letters or fewer ("II", "ve") has too many
        # neighbours to choose between safely.
        titlecase = core[:1].isupper() and core[1:].islower()
        if not _WORD.fullmatch(core or "_") or len(fc) < 4:
            out.append(tok)
            prev_fold = fc if _WORD.fullmatch(core or "_") else None
            prev_is_name = titlecase and not trail
            continue
        best_key, best = fc, uni.get(fc, 0)
        # OCR reads a final "l" as "!" ("Retina!"): if the book knows the
        # word with the "l", that is the word.
        if trail[:1] in ("!", "|") and uni.get(fold(core + "l"), 0) > 0:
            best_key, best = fold(core + "l"), uni.get(fold(core + "l"), 0)
            trail = trail[1:]
        # the chapter page's reading of the same word, at the same position
        w = aligned.get(pos)
        if (w and w != best_key and len(w) >= 4
                and _edit_distance(w, best_key) <= max(1, len(best_key) // 4)
                and uni.get(w, 0) > best):
            best_key, best = w, uni.get(w, 0)
        # both witnesses misread it the same way ("Steven Hali"): what does
        # the book print after the same word, clearly more often? Only for a
        # name — a capitalised word after another capitalised word — which
        # a book repeats in one spelling. Ordinary words have too many
        # legitimate near neighbours ("üretici" / "üretim").
        is_name = core[:1].isupper() and core[1:].islower() and prev_is_name
        if prev_fold and is_name:
            here = bi.get((prev_fold, best_key), 0)
            allowed = max(1, len(best_key) // 3)
            if len(best_key) <= 5:
                allowed = 2
            close = [
                (n, w2) for (w1, w2), n in bi.items()
                if w1 == prev_fold and w2 != best_key and n >= 3 and n > here * 1.4
                and len(w2) >= 3 and _edit_distance(w2, best_key) <= allowed
            ]
            if close:
                best_key = max(close)[1]
        if best_key != fc:
            core = _recase(vocab.surface.get(best_key, best_key), core)
        out.append(lead + core + trail)
        prev_fold = best_key
        prev_is_name = titlecase and not trail
    return " ".join(out)
