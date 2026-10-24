"""The book's imprint (künye), read from its own pages.

A Turkish book prints its künye on one of its first pages — the original
title, the translator, the publisher, which printing, the year, the ISBN —
and the ISBN again on the back cover. They are read here from the text of
the first and last pages (the searchable copy, for a scan). Only what a
labelled line plainly says is taken — "Türkçesi: Cenk Saraçoğlu", "24.
Basım: Nisan 2016", "Özgün Adı:" with the title under it — and a value is
kept only if it reads as what the label promises: names for a translator,
a short name ending in "Yayınları" or the like for a publisher. An ISBN
counts only with its check digit right, and a bare run of digits only as
the 978/979 thirteen of a barcode (a phone number has ten digits too).

What is read goes into the book's metadata (publisher, date, ISBN,
translator) and, if the reader wants it, a page "Bu baskı hakkında"; the
online lookup only fills what this left empty.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Dict, Iterable, List, Optional, Tuple

FRONT_PAGES = 8
BACK_PAGES = 3

ISBN_RE = re.compile(r"(?<![\dXx])((?:97[89][\s\-–‑]?)?(?:\d[\s\-–‑]?){9}[\dXx])(?![\d])")
ISBN_NEAR = re.compile(r"(?:ISBN|ıSBN|lSBN|1SBN)[\s:\-–]*$", re.I)
_SEP = re.compile(r"[\s\-–‑]")

# a label and what follows it on its line; a label left alone on its line
# takes the line under it ("Çeviren" / "ler:" broken over two lines is joined first)
_FROM_LANGUAGE = r"(?:[a-zçğıöşü]+(?:ce|ca|çe|ça)(?:den|dan)\s+)?"
LABELS: List[Tuple[str, re.Pattern]] = [
    ("translator", re.compile(r"^" + _FROM_LANGUAGE + r"(?:çevirenler|çeviren|türkçesi|türkçeleştiren|tercüme eden|"
                              r"çev\.|translated by)(?=[\s:]|$)\s*[:\-–]?\s*(?P<v>.*)$"
                              # "Çeviri: X"; "İngilizce aslından çeviren ve yayına hazırlayan: X"
                              r"|^(?:çeviri|(?:[\wçğıöşü]+\s+){0,3}çeviren(?:ler)?(?:\s+ve\s+[\wçğıöşü ]{3,30}?)?)"
                              r"\s*:\s*(?P<w>.*)$", re.I)),
    ("editor", re.compile(r"^(?:editörler|editör|yayına hazırlayanlar|yayına hazırlayan|derleyenler|derleyen|"
                          r"edited by)(?=[\s:]|$)\s*[:\-–]?\s*(?P<v>.*)$", re.I)),
    ("original_title", re.compile(r"^(?:kitabın\s+)?(?:özgün|orijinal|asıl)\s+(?:ad[ıi]?|ismi|isim)(?=[\s:]|$)\s*[:\-–]?\s*(?P<v>.*)$"
                                  r"|^original(?:ly)?\s+(?:title|published as)(?=[\s:]|$)\s*[:\-–]?\s*(?P<w>.*)$", re.I)),
]
BROKEN_LABEL = re.compile(r"(?im)^(çeviren|editör|derleyen|yayına hazırlayan)\s*\n\s*(ler|lar)\s*:")
PUBLISHER = re.compile(r"^[*©\s]*(?P<v>[A-ZÇĞİÖŞÜ0-9][\w&'’.\- ]{1,40}?\s+"
                       r"(?i:yayınları|yayıncılık|yayınevi|kitapları|kitap|press|publishing|publishers))"
                       r"(?i:\s+(?:ltd\.?|şti\.?|a\.ş\.?|san\.|tic\.|inc\.?)\b.*)?\s*[:\d]*\s*$")
EDITION = re.compile(r"(?P<n>\d{1,2})\s*\.\s*(?:baskı|basım)\b(?:[^\n\d]{0,25}?(?P<y>1[89]\d\d|20\d\d))?", re.I)
WORD_EDITION = re.compile(r"\b(?P<n>[Bb]irinci|[İi]kinci|[Üü]çüncü|[Dd]ördüncü|[Bb]eşinci|[Aa]ltıncı|BİRİNCİ|İKİNCİ|ÜÇÜNCÜ)\s+(?:baskı|basım)\b"
                          r"(?:[^\n\d]{0,25}?(?P<y>1[89]\d\d|20\d\d))?", re.I)
COPYRIGHT_YEAR = re.compile(r"(?:©|\(c\)|copyright)[^\n\d]{0,60}?(?P<y>19\d\d|20\d\d)\b", re.I)
ORDINALS = {"birinci": 1, "ikinci": 2, "üçüncü": 3, "dördüncü": 4, "beşinci": 5, "altıncı": 6}
NOT_A_NAME = re.compile(r"\d|@|www\.|https?:|sertifika|\btel\b|faks|adres|editör|edited", re.I)
NAME_JOINERS = {"ve", "ile", "&", "•", "-", "–", "and", "von", "van", "de", "der", "la", "le", "bin", "ibn"}
PARENS = re.compile(r"\s*\([^)]*\)")


@dataclass
class Imprint:
    isbn: Optional[str] = None            # ISBN-13, digits only
    translator: Optional[str] = None
    editor: Optional[str] = None
    original_title: Optional[str] = None
    publisher: Optional[str] = None
    edition: Optional[int] = None
    year: Optional[str] = None
    pages: List[int] = field(default_factory=list)      # the PDF pages it was read from (1-based)

    def to_dict(self) -> Dict:
        return asdict(self)

    def empty(self) -> bool:
        return not any((self.isbn, self.translator, self.editor, self.original_title, self.publisher, self.year))


def _isbn10_ok(d: str) -> bool:
    if len(d) != 10 or not d[:9].isdigit() or not (d[9].isdigit() or d[9] in "Xx"):
        return False
    total = sum((10 - i) * int(c) for i, c in enumerate(d[:9])) + (10 if d[9] in "Xx" else int(d[9]))
    return total % 11 == 0


def _isbn13_ok(d: str) -> bool:
    if len(d) != 13 or not d.isdigit() or not d.startswith(("978", "979")):
        return False
    return sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(d)) % 10 == 0


def to_isbn13(d: str) -> Optional[str]:
    d = _SEP.sub("", d or "").upper()
    if _isbn13_ok(d):
        isbn = d
    elif _isbn10_ok(d):
        core = "978" + d[:9]
        isbn = core + str((10 - sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(core)) % 10) % 10)
    else:
        return None
    if len(set(isbn[3:12])) <= 2:          # a barcode's bars read as "1111111111"
        return None
    return isbn


def isbns(text: str) -> List[str]:
    """The ISBNs in `text` with a valid check digit, as ISBN-13: one printed
    after the word "ISBN", or a 978/979 thirteen on its own."""
    near, other = [], []
    for m in ISBN_RE.finditer(text or ""):
        isbn = to_isbn13(m.group(1))
        if not isbn:
            continue
        labelled = bool(ISBN_NEAR.search(text[max(0, m.start() - 12):m.start()]))
        if labelled:
            near.append(isbn)
        elif len(_SEP.sub("", m.group(1))) == 13:
            other.append(isbn)
    out: List[str] = []
    for isbn in near + other:
        if isbn not in out:
            out.append(isbn)
    return out


def _name_case(value: str) -> str:
    """CENK SARAÇOĞLU -> Cenk Saraçoğlu; a name already in mixed case is
    left as printed."""
    if any(c.islower() for c in value):
        return value
    low = value.replace("I", "ı").replace("İ", "i").lower()
    return " ".join(w if w in NAME_JOINERS else w[:1].replace("i", "İ").replace("ı", "I").upper() + w[1:]
                    for w in low.split())


def _names(value: str) -> Optional[str]:
    """`value` if it reads as one or more people's names."""
    value = PARENS.sub("", " ".join((value or "").split())).strip(" .:;,-–")
    if not value or NOT_A_NAME.search(value) or len(value) > 90:
        return None
    words = [w for w in re.split(r"[\s,]+", value) if w]
    if not 2 <= len(words) <= 12:
        return None
    if not all(w.lower() in NAME_JOINERS or w[:1].isupper() for w in words):
        return None
    return _name_case(value)


def _publisher(value: str) -> bool:
    """A publisher's name: a few words, each capitalised ("Sel Yayıncılık",
    "Yordam Kitap"), not a volume ("Birinci Kitap") or a sentence."""
    words = value.split()
    first = words[0].replace("İ", "i").replace("I", "ı").lower()
    if len(words) > 5 or NOT_A_NAME.search(value) or first in ORDINALS:
        return False
    if words[0].lower() in ("distributed", "printed", "published"):
        return False
    return all(w[:1].isupper() or w[:1].isdigit() or w in ("&", "ve", "and") for w in words)


def _title(lines: List[str]) -> Optional[str]:
    text = " ".join(" ".join(lines).split()).strip(" .:;")
    if len(text) < 3 or len(text) > 140 or NOT_A_NAME.search(text):
        return None
    return text


def read_pages(pages: Iterable[Tuple[int, str]]) -> Imprint:
    """The imprint from (page number, text) pairs: the book's first and last
    pages, in that order."""
    imp = Imprint()
    editions: List[Tuple[int, Optional[str]]] = []
    copyright_year: Optional[str] = None
    capitals: Dict[str, bool] = {}
    for number, text in pages:
        text = BROKEN_LABEL.sub(lambda m: m.group(1) + m.group(2) + ":", text or "")
        lines = [" ".join(ln.split()) for ln in text.splitlines()]
        found_here = False
        for k, line in enumerate(lines):
            if not line:
                continue
            for attr, rx in LABELS:
                m = rx.match(line)
                if not m:
                    continue
                value = (m.group("v") if "v" in rx.groupindex else None) or (
                    m.group("w") if "w" in rx.groupindex else None) or ""
                under = [ln for ln in lines[k + 1:k + 4] if ln]
                if attr == "original_title":
                    if not value:
                        # the title under the label, on a line or two, until the next label
                        taken = []
                        for ln in under[:2]:
                            if ":" in ln or ln.startswith(("©", "(c)")) or NOT_A_NAME.search(ln):
                                break
                            taken.append(ln)
                        value = " ".join(taken)
                    raw, good = value, _title([value])
                else:
                    raw = value
                    good = _names(value) if value else None
                    if not good and not value and under:
                        raw = under[0]
                        good = _names(under[0])
                        # a list of names running on to the next line
                        more = _names(under[1]) if len(under) > 1 and "," in under[0] else None
                        if good and more:
                            good = f"{good}, {more}"
                if good:
                    # a name set in capitals (on a cover) gives way to the
                    # same label's value in the imprint's own letters
                    if not getattr(imp, attr) or (capitals.get(attr) and any(c.islower() for c in raw)):
                        setattr(imp, attr, good)
                        capitals[attr] = not any(c.islower() for c in raw)
                    found_here = True
            m = PUBLISHER.match(line)
            if m and not imp.publisher and _publisher(m.group("v")):
                imp.publisher = _name_case(" ".join(m.group("v").split()))
                found_here = True
        m = COPYRIGHT_YEAR.search(text)
        found = isbns(text)
        if found and not imp.isbn:
            imp.isbn = found[0]
            found_here = True
        # printings and years only from a page that is an imprint (the back
        # pages list other books with "41. Basım")
        if found_here or m:
            if m and not copyright_year and 1900 <= int(m.group("y")) <= date.today().year:
                copyright_year = m.group("y")
            for rx in (EDITION, WORD_EDITION):
                for e in rx.finditer(text):
                    n = e.group("n").replace("İ", "i").replace("I", "ı").lower()
                    editions.append((int(n) if n.isdigit() else ORDINALS.get(n, 0), e.group("y")))
        if found_here and number not in imp.pages:
            imp.pages.append(number)
    if editions:
        # this printing is the latest one the imprint lists ("1. Basım: 2006 … 24. Basım: 2016")
        n, year = max(editions, key=lambda e: (e[0], e[1] or ""))
        imp.edition = n or None
        imp.year = year or next((y for _, y in sorted(editions, reverse=True) if y), None)
    if not imp.year and copyright_year:
        imp.year = copyright_year
    return imp


def read_pdf(pdf_path: str) -> Imprint:
    """The imprint of a PDF, from the text of its first and last pages."""
    import fitz

    try:
        doc = fitz.open(pdf_path)
    except Exception:  # noqa: BLE001
        return Imprint()
    with doc:
        n = doc.page_count
        wanted = list(range(min(FRONT_PAGES, n))) + [i for i in range(max(0, n - BACK_PAGES), n) if i >= FRONT_PAGES]
        return read_pages((i + 1, doc[i].get_text()) for i in wanted)
