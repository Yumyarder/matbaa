"""A book's title and author from its file name, when the PDF says nothing.

The engine reads the title and author from the PDF's metadata, its title
page and its running heads. When all three are silent the book came out as
"Untitled Book" by "Unknown", and the reader typed both in for every scan.
The file the reader chose usually names the book — "Stavros Stavrides -
Müşterek Mekan.pdf", "Teori ve Pratik - Mao Zedung.pdf" — so it is the last
place to look. Only what the engine could not find is taken from it; the
title and author stay editable in the workbench.

The name is cleaned of what download sites and tools add: a leading
number ("706422706-"), bracketed sources ("(Yordam Kitap)", "(ornek-site.com,
2021)"), a trailing "compressed" or "ocr"; underscores are spaces. With
" - " between two parts, the one that reads as a person's name is the
author — the left one where both do, "Author - Title" being the usual
order. A name typed without Turkish letters ("Savasinin Planlari") gets
them back where the library's own spelling is sure (app/deasciify.py).
A name that is a code ("Mir.az-00dc7b00-29da-…") gives nothing.
"""
from __future__ import annotations

import os
import re
from typing import Optional, Tuple

UNTITLED = "Untitled Book"
UNKNOWN = "Unknown"

_DOWNLOAD_ID = re.compile(r"^\d{5,}[\s_-]+")
_BRACKETS = re.compile(r"\s*[\(\[][^()\[\]]*[\)\]]")
_TAIL = re.compile(r"[\s_.-]+(?:compress(?:ed)?|ocr(?:ed)?|scan(?:ned)?|optimi[sz]ed|final|\d{1,3})$", re.I)
_SPLIT = re.compile(r"\s+[-–—]\s+")
_CODE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}|\b[0-9a-f]{12,}\b|\d{6,}", re.I)
_SMALL = {"ve", "ile", "veya", "ya", "da", "de", "ki", "mi", "için", "gibi",
          "and", "or", "of", "the", "a", "an", "in", "on", "to", "for"}


def _person(text: str) -> bool:
    """Two to four capitalised words, initials allowed: "Stavros Stavrides",
    "V. İ. Lenin", "David D. Burns"."""
    words = text.split()
    if not 2 <= len(words) <= 4:
        return False
    full = 0
    for w in words:
        if re.fullmatch(r"[^\W\d_]\.", w) and w[0].isupper():
            continue
        if not (w[:1].isupper() and w[1:].replace("-", "").isalpha() and w[1:].islower()):
            return False
        full += 1
    return full >= 1


def _title_case(text: str) -> str:
    """A name typed all in small letters or all in capitals, set the way a
    Turkish title is: each word's first letter large (i -> İ), small words
    small."""
    words = text.lower().replace("i̇", "i").split()
    return " ".join(w if k and w in _SMALL else w[:1].replace("i", "İ").replace("ı", "I").upper() + w[1:]
                    for k, w in enumerate(words))


def _tidy(text: str, language: str) -> str:
    text = " ".join(text.replace("_", " ").split()).strip(" -–—.,")
    if text.isupper():
        text = text.replace("I", "ı").replace("İ", "i").lower()
    if (language or "").lower().startswith("tr") and text.isascii():
        from app.deasciify import restore
        text = restore(text)[0]
    if text.islower():
        text = _title_case(text)
    return text


def from_filename(filename: Optional[str], language: str = "tr") -> Tuple[Optional[str], Optional[str]]:
    """(title, author) as the file name gives them; None for what it does not."""
    stem = os.path.splitext(os.path.basename(filename or ""))[0]
    stem = _BRACKETS.sub("", _DOWNLOAD_ID.sub("", stem))
    previous = None
    while previous != stem:
        previous, stem = stem, _TAIL.sub("", stem).strip()
    if len(stem) < 3 or _CODE.search(stem):
        return None, None
    # a file name cannot hold a colon: " _ " stands in for it
    stem = re.sub(r"\s+_\s+", ": ", stem)
    parts = [p.strip() for p in _SPLIT.split(stem) if p.strip(" -_")]
    if len(parts) >= 2:
        left = " ".join(parts[0].replace("_", " ").split())
        right = " ".join(" ".join(parts[1:]).replace("_", " ").split())
        if _person(left):
            return _tidy(right, language), _tidy(left, language)
        if _person(right.replace(",", "")):
            return _tidy(left, language), _tidy(right, language)
    # one part, its words joined by hyphens or underscores: the title, no author guessed
    return _tidy(re.sub(r"[-_]+", " ", stem), language), None


_FILE_TITLE = re.compile(r"\.(?:pdf|docx?|epub|indd|qxd)\s*$", re.I)


def fill(title: str, author: str, filename: Optional[str], language: str = "tr") -> Tuple[str, str]:
    """`title` and `author`, with what the engine could not find taken from
    the file name. A title that is itself a file name — the metadata of a
    PDF saved from a download ("David Eagleman, Anthony Brandt - Yaratıcı
    Tür.pdf") — counts as missing, and is read as one if the reader's file
    name gives nothing."""
    file_title = bool(title and _FILE_TITLE.search(title))
    missing_title = not title or title.strip() == UNTITLED or file_title
    missing_author = not author or author.strip() == UNKNOWN
    if not (missing_title or missing_author):
        return title, author
    for source in [filename] + ([title] if file_title else []):
        if not source:
            continue
        name_title, name_author = from_filename(source, language)
        if missing_title and name_title:
            title, missing_title = name_title, False
        if missing_author and name_author:
            author, missing_author = name_author, False
    if missing_title and file_title:
        title = UNTITLED
    return title, author
