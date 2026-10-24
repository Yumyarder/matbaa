"""A book's imprint completed online, by its ISBN, on the reader's request.

Matbaa sends nothing anywhere by itself; this runs when the reader presses
"İnternetten tamamla", and the only thing that leaves the computer is the
ISBN. Open Library is asked first (no key, free covers), Google Books when
Open Library does not know the book.

What comes back only fills what the book's own imprint left empty: the book
spells its publisher and its title in Turkish letters, Open Library often
does not ("Sel Yayincilik", "Müsterek Mekan"), so a value found here never
replaces one read from the book, and one in plain ASCII is given its
Turkish letters back (app/deasciify.py) for a Turkish book. A cover counts
only at a size a Kindle can show (at least 500 pixels tall).
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import urllib.error
import urllib.request
from typing import Dict, Optional, Tuple

OPENLIBRARY = os.environ.get("MATBAA_OPENLIBRARY_URL", "https://openlibrary.org")
COVERS = os.environ.get("MATBAA_COVERS_URL", "https://covers.openlibrary.org")
GOOGLEBOOKS = os.environ.get("MATBAA_GOOGLEBOOKS_URL", "https://www.googleapis.com/books/v1")
MIN_COVER_HEIGHT = 500
TIMEOUT = 15
YEAR = re.compile(r"\b(1[5-9]\d\d|20\d\d)\b")


class LookupFailed(RuntimeError):
    pass


def _get(url: str) -> Optional[bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": "Matbaa (personal e-book converter)"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310 - fixed public hosts
            return resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise LookupFailed(f"{url.split('/')[2]}: HTTP {exc.code}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise LookupFailed(f"{url.split('/')[2]} yanıt vermedi ({exc})") from exc


def _json(url: str) -> Optional[Dict]:
    data = _get(url)
    if not data:
        return None
    try:
        return json.loads(data.decode("utf-8"))
    except ValueError:
        return None


def _cover(url: str) -> Optional[str]:
    """The image at `url` as base64, if it is a picture tall enough."""
    try:
        data = _get(url)
    except LookupFailed:
        return None
    if not data:
        return None
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as img:
            if img.height < MIN_COVER_HEIGHT:
                return None
    except Exception:  # noqa: BLE001
        return None
    return base64.b64encode(data).decode("ascii")


def _year(text) -> Optional[str]:
    m = YEAR.search(str(text or ""))
    return m.group(1) if m else None


def from_openlibrary(isbn: str) -> Optional[Dict]:
    d = _json(f"{OPENLIBRARY}/isbn/{isbn}.json")
    if not d:
        return None
    authors = []
    for a in d.get("authors") or []:
        key = a.get("key") if isinstance(a, dict) else None
        if key:
            info = _json(f"{OPENLIBRARY}{key}.json") or {}
            if info.get("name"):
                authors.append(info["name"])
    cover = _cover(f"{COVERS}/b/isbn/{isbn}-L.jpg?default=false")
    return {"source": "Open Library", "title": d.get("title"), "subtitle": d.get("subtitle"), "authors": authors,
            "publisher": (d.get("publishers") or [None])[0], "year": _year(d.get("publish_date")),
            "pages": d.get("number_of_pages"), "cover": cover}


def from_googlebooks(isbn: str) -> Optional[Dict]:
    d = _json(f"{GOOGLEBOOKS}/volumes?q=isbn:{isbn}")
    items = (d or {}).get("items") or []
    if not items:
        return None
    v = items[0].get("volumeInfo") or {}
    links = v.get("imageLinks") or {}
    cover = None
    for size in ("extraLarge", "large", "medium"):
        if links.get(size):
            cover = _cover(links[size].replace("http://", "https://"))
            if cover:
                break
    return {"source": "Google Books", "title": v.get("title"), "subtitle": v.get("subtitle"),
            "authors": v.get("authors") or [], "publisher": v.get("publisher"), "year": _year(v.get("publishedDate")),
            "pages": v.get("pageCount"), "cover": cover}


def look_up(isbn: str) -> Optional[Dict]:
    """What Open Library, else Google Books, knows of the book; None if
    neither knows it. LookupFailed when neither could be reached."""
    errors = []
    for source in (from_openlibrary, from_googlebooks):
        try:
            found = source(isbn)
        except LookupFailed as exc:
            errors.append(str(exc))
            continue
        if found:
            return found
    if len(errors) == 2:
        raise LookupFailed("; ".join(errors))
    return None


def _turkish(value: str, language: str) -> str:
    if value and value.isascii() and (language or "").lower().startswith("tr"):
        from app.deasciify import restore
        return restore(value)[0]
    return value


def merge(imprint: Optional[Dict], found: Dict, language: str = "tr") -> Tuple[Dict, list]:
    """The imprint with what was found filled in where it was empty, and the
    names of the fields filled."""
    out = dict(imprint or {})
    filled = []
    for key in ("publisher", "year"):
        value = found.get(key)
        if value and not out.get(key):
            out[key] = _turkish(str(value), language) if key == "publisher" else str(value)
            filled.append(key)
    return out, filled
