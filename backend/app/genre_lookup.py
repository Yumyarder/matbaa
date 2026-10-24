"""A book's genre from what Wikidata says of the book or of its author.

Wikidata (Wikipedia's data) describes most books and nearly every author in
one line: "1866 novel by Fyodor Dostoyevsky", "Kürk Mantolu Madonna:
Sabahattin Ali'nin 1943 tarihli romanı", "American psychiatrist and author",
"French philosopher". That line is enough for a genre:

1. the book itself, found by its title, when the line names a literary form
   (novel, poems) or a subject; a novel's origin from the line ("Russian")
   or from its author's;
2. otherwise the author, found by name: a novelist's or poet's books are
   literature of the author's country, a philosopher's philosophy, a
   psychiatrist's psychology, a revolutionary's politics.

A plain "writer" says nothing of the book, and then the book's own reading
decides (app/genre.py). Only the title and the author's name leave the
computer, and only when Matbaa runs as the reader's app (MATBAA_ONLINE, set
by run_server.py); a failure or a slow answer falls back to the local guess.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import List, Optional, Tuple

WIKIDATA = os.environ.get("MATBAA_WIKIDATA_URL", "https://www.wikidata.org/w/api.php")
TIMEOUT = 4
USER_AGENT = "Matbaa/1.0 (personal PDF-to-Kindle converter)"

NOT_A_BOOK = re.compile(r"\b(film|album|song|single|episode|television|tv series|painting|scientific article|"
                        r"podcast|disambiguation|family name|given name|surname|video game|band|street|museum|"
                        r"audiobook|sesli kitap|yapımı|dizisi)\b", re.I)
LITERARY = re.compile(r"\b(novel|novella|short stor\w*|poem\w*|poetry|play|drama|roman|romanı|öykü\w*|hikâye\w*|"
                      r"şiir\w*|tiyatro oyunu)\b", re.I)
NOVELIST = re.compile(r"\b(novelist|poet|playwright|short story writer|romancı|şair|öykücü|hikâyeci|oyun yazarı)\b", re.I)
RUSSIAN = re.compile(r"\b(russian|soviet|rus|rusça|sovyet)\b", re.I)
TURKISH = re.compile(r"\b(turkish|ottoman|türk|türkçe|osmanlı)\b", re.I)
# (genre, words of an occupation or a book's subject), the first that fits wins
SUBJECTS: List[Tuple[str, re.Pattern]] = [
    ("din", re.compile(r"theolog|religious (?:scholar|leader|text)|islamic scholar|cleric|imam\b|priest|saint|"
                       r"mytholog|ilahiyat|din adamı|mitoloj", re.I)),
    ("felsefe", re.compile(r"philosoph|filozof|felsefeci|felsefi", re.I)),
    ("ekonomi", re.compile(r"economist|economic|iktisatçı|ekonomist|iktisat", re.I)),
    ("psikoloji", re.compile(r"psychiatr|psycholog|psychoanalys|psychotherap|psikiyatr|psikolog|psikanaliz", re.I)),
    ("sosyoloji", re.compile(r"sociolog|anthropolog|urbanist|sosyolog|antropolog", re.I)),
    ("tarih", re.compile(r"historian|history of|tarihçi|tarihi", re.I)),
    ("sanat", re.compile(r"architect|art historian|art critic|painter|sculptor|film director|composer|"
                         r"musicolog|mimar|sanat tarihçisi|ressam|heykeltıraş|besteci", re.I)),
    ("bilim", re.compile(r"physicist|chemist|biologist|neuroscien|mathematician|astronomer|scientist|"
                         r"fizikçi|kimyager|biyolog|matematikçi|bilim insanı", re.I)),
    ("kisisel", re.compile(r"self-help|motivational|life coach|productivity|kişisel gelişim", re.I)),
    ("siyaset", re.compile(r"politician|revolutionar|communist|marxist|socialist|political|activist|statesman|"
                           r"siyasetçi|politikacı|devrimci|komünist|sosyalist|siyasal|siyasi", re.I)),
]


@dataclass
class Found:
    key: Optional[str]       # a genre, or None for "a literary book, origin unknown" / "a writer"
    fiction: bool
    reason: str
    description: str = ""
    level: str = "book"      # "book": its own entry; "author": its author's


def _search(text: str) -> List[Tuple[str, str]]:
    """(label, description) of Wikidata's best matches for `text`."""
    if not text or not text.strip():
        return []
    query = urllib.parse.urlencode({"action": "wbsearchentities", "search": text.strip()[:120], "language": "tr",
                                    "uselang": "en", "type": "item", "limit": 5, "format": "json"})
    req = urllib.request.Request(f"{WIKIDATA}?{query}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310 - one fixed public host
        data = json.loads(resp.read().decode("utf-8"))
    return [(s.get("label") or "", s.get("description") or "") for s in data.get("search") or []]


def _origin(description: str) -> Optional[str]:
    """Russian or Turkish literature by the line's nationality; None when it
    names neither."""
    if RUSSIAN.search(description or ""):
        return "rus-edebiyati"
    if TURKISH.search(description or ""):
        return "turk-edebiyati"
    return None


def _subject(description: str) -> Optional[str]:
    for key, rx in SUBJECTS:
        if rx.search(description):
            return key
    return None


def _surname(author: str) -> str:
    parts = [p for p in re.split(r"[\s,.]+", author or "") if len(p) > 1]
    return parts[-1].lower() if parts else ""


def from_book(title: str, author: str) -> Optional[Found]:
    surname = _surname(author)
    for label, description in _search(title):
        if not description or NOT_A_BOOK.search(description):
            continue
        # the right book names its author, or at least is a book
        if surname and surname[:5] not in description.lower() and not re.search(r"\b(book|kitap|novel|roman)", description, re.I):
            continue
        if LITERARY.search(description):
            return Found(_origin(description), True, f"Wikidata: “{description}”", description)
        subject = _subject(description)
        if subject:
            return Found(subject, False, f"Wikidata: “{description}”", description)
    return None


def from_author(author: str) -> Optional[Found]:
    if not author or author.strip().lower() in ("unknown", "bilinmiyor"):
        return None
    for label, description in _search(author):
        if not description or NOT_A_BOOK.search(description):
            continue
        why = f"Wikidata, yazar: “{description}”"
        if NOVELIST.search(description):
            return Found(_origin(description) or "dunya-edebiyati", True, why, description, "author")
        subject = _subject(description)
        if subject:
            return Found(subject, False, why, description, "author")
        if re.search(r"\b(writer|author|yazar|journalist|gazeteci|essayist|denemeci)\b", description, re.I):
            return Found(None, False, why, description, "author")   # a writer: says nothing of the book
    return None


def look_up(title: str, author: str) -> Optional[Found]:
    """What Wikidata says; None when it says nothing useful or cannot be
    reached. A plain writer comes back with key None: the book's own reading
    decides, and the writer's nationality gives a novel its origin."""
    try:
        book = from_book(title, author)
        if book and not (book.fiction and book.key is None):
            return book
        writer = from_author(author)
        if book:        # a literary book whose line names no country: its author's
            origin = _origin(writer.description) if writer else None
            return Found(origin or "dunya-edebiyati", True, book.reason, book.description)
        return writer
    except (urllib.error.URLError, OSError, ValueError):
        return None
