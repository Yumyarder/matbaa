"""A line worth quoting from a book, found on Vikisöz (Wikiquote), for the
start screen of a reader who has books but no Kindle notes yet.

The start screen shows a passage the reader marked on their Kindle; before
there is one, it shows a well-known line from their latest book: Vikisöz's
page for the book (Turkish, then English Wikiquote), else its author's. A
page lists its quotes as top-level items, each with its source as a nested
item under it; the first quote of a readable length is taken. Only the
title and the author's name leave the computer, and only in the reader's
app (MATBAA_ONLINE). With nothing found, and for a reader with no books at
all, the screen quotes Trotsky.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Dict, List, Optional

SITES = [("tr", os.environ.get("MATBAA_WIKIQUOTE_TR", "https://tr.wikiquote.org/w/api.php"), "Vikisöz"),
         ("en", os.environ.get("MATBAA_WIKIQUOTE_EN", "https://en.wikiquote.org/w/api.php"), "Wikiquote")]
TIMEOUT = 4
USER_AGENT = "Matbaa/1.0 (personal PDF-to-Kindle converter)"
MIN_LEN, MAX_LEN = 40, 320
NOT_A_QUOTE = re.compile(r"ISBN|https?://|\bs\.\s*\d|\bp\.\s*\d|Kaynak|Source|^\W*$", re.I)
# a scrap of a novel's dialogue ('…," diye mırıldandı') is not a line to stand alone
DIALOGUE = re.compile(r"[\"”]\s*(?:diye|dedi|said|asked)\b|,\s*[\"”]|[\"“”].*[\"“”]")
# the reader with no books yet (Trotsky's speech of 1918, as the Turkish
# edition of his writings titles it)
FALLBACK = {"text": "Yalnızca burjuvazi için parlayacaksa güneşi de söndürürüz.",
            "author": "Lev Troçki", "source": "1918", "url": None, "kind": "fallback"}


class _TopLevelItems(HTMLParser):
    """The text of each list item at the outermost list level of an article,
    without its nested items (a quote's source) and outside tables and
    boxes."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth_ul = 0
        self.skip = 0
        self.items: List[str] = []
        self._current: Optional[List[str]] = None

    def handle_starttag(self, tag, attrs):
        cls = dict(attrs).get("class") or ""
        if tag in ("table", "style", "script", "sup") or (tag == "div" and re.search(r"navbox|toc|thumb|mw-references", cls)):
            self.skip += 1
            return
        if self.skip:
            return
        if tag in ("ul", "ol"):
            self.depth_ul += 1
        elif tag == "li" and self.depth_ul == 1:
            self._current = []

    def handle_endtag(self, tag):
        if tag in ("table", "style", "script", "sup") or (tag == "div" and self.skip):
            if self.skip:
                self.skip -= 1
            return
        if self.skip:
            return
        if tag in ("ul", "ol"):
            self.depth_ul -= 1
        elif tag == "li" and self.depth_ul == 1 and self._current is not None:
            self.items.append(" ".join("".join(self._current).split()))
            self._current = None

    def handle_data(self, data):
        if not self.skip and self._current is not None and self.depth_ul == 1:
            self._current.append(data)


def _api(base: str, params: Dict) -> Dict:
    # origin=*: the wiki answers a browser's anonymous request (Matbaa in the browser)
    query = urllib.parse.urlencode({**params, "format": "json", "formatversion": 2, "origin": "*"})
    req = urllib.request.Request(f"{base}?{query}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310 - Wikimedia's own hosts
        return json.loads(resp.read().decode("utf-8"))


def quotes_in(html: str) -> List[str]:
    parser = _TopLevelItems()
    parser.feed(html or "")
    out = []
    for item in parser.items:
        text = item.strip(" “”\"'«»")
        if MIN_LEN <= len(text) <= MAX_LEN and not NOT_A_QUOTE.search(text) and not DIALOGUE.search(text):
            out.append(text)
    return out


def _fold(text: str) -> str:
    return re.sub(r"[^\w]", "", (text or "").replace("İ", "i").replace("I", "ı").lower())


def _page(base: str, wanted: str) -> Optional[str]:
    """The title of the page that is `wanted` (a book or a person), if the
    wiki has one."""
    found = _api(base, {"action": "query", "list": "search", "srsearch": wanted, "srlimit": 3})
    for hit in (found.get("query") or {}).get("search") or []:
        if _fold(hit.get("title")) == _fold(wanted):
            return hit["title"]
    return None


def look_up(title: str, author: str) -> Optional[Dict]:
    """{text, author, source, url, kind: "book" | "author"} or None."""
    try:
        for kind, wanted in (("book", title), ("author", author)):
            if not wanted or wanted.strip().lower() in ("unknown", "untitled book"):
                continue
            for lang, base, name in SITES:
                page = _page(base, wanted)
                if not page:
                    continue
                parsed = _api(base, {"action": "parse", "page": page, "prop": "text"})
                found = quotes_in((parsed.get("parse") or {}).get("text") or "")
                if found:
                    site = base.split("/w/")[0]
                    return {"text": found[0], "author": author if kind == "book" else page,
                            "source": f"{name}: {page}", "url": f"{site}/wiki/{urllib.parse.quote(page)}",
                            "kind": kind, "lang": lang}
    except (urllib.error.URLError, OSError, ValueError, KeyError):
        return None
    return None
