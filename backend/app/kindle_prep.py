"""Readying the Kindle for Matbaa's books, once per device.

Two things a Kindle does not have and the books want: typefaces beyond
Amazon's own (put in the fonts/ folder at its root, they are offered in the
Aa menu for every book), and a Turkish dictionary (none of Amazon's
dictionaries is Turkish; one put in documents/dictionaries/ is used for
books whose language is Turkish). Only files are added; a file of the same
name already on the Kindle is left as it is (kindle_usb.put_files), except
Matbaa's own dictionary when it has been made again with new books.
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional

from app import dictionary, fonts, kindle_usb

FONT_FOLDER = "fonts"
DICTIONARY_FOLDER = "documents/dictionaries"


def font_status(names_there: set) -> List[Dict]:
    return [{"family": family, "label": family.capitalize(),
             "installed": all(name in names_there for name in names)}
            for family, names in fonts.KINDLE_FAMILIES.items()]


def report() -> Dict:
    """What the plugged-in Kindle has of what Matbaa gives it."""
    st = kindle_usb.state()
    out: Dict = {"state": st, "connected": st != "NO_KINDLE", "ready": st == "READY",
                 "message": kindle_usb.MESSAGES.get(st) if st not in ("READY", "NO_KINDLE") else None,
                 "fonts": [], "dictionaries": [],
                 "matbaa_dictionary": {"built": dictionary_file() is not None, "on_kindle": False,
                                       "new_books": _books_since_built()}}
    if st != "READY":
        return out
    try:
        there = {item.name for item in (kindle_usb.list_folder(FONT_FOLDER) or [])}
        out["fonts"] = font_status(there)
        listed = [item for item in (kindle_usb.list_folder(DICTIONARY_FOLDER) or []) if not item.folder]
        out["dictionaries"] = sorted(item.name for item in listed)
        mine = next((item for item in listed if item.name == dictionary.DEVICE_NAME), None)
        made = dictionary_file()
        out["matbaa_dictionary"]["on_kindle"] = mine is not None
        # the Kindle holds an older make of it than the one made here
        out["matbaa_dictionary"]["outdated"] = bool(mine and made and mine.size and mine.size != os.path.getsize(made))
    except kindle_usb.KindleNotFound as exc:
        out.update(ready=False, message=str(exc))
    return out


def _books_since_built() -> int:
    from app.dictionary_build import books_since_built
    try:
        return books_since_built()
    except OSError:
        return 0


def install_fonts() -> Dict[str, str]:
    """Matbaa's faces copied into the Kindle's fonts/ folder: file -> OK,
    SKIP (already there) or TIMEOUT."""
    return kindle_usb.put_files(FONT_FOLDER, [path for _, path in fonts.kindle_files()])


def dictionary_file() -> Optional[str]:
    """The Turkish dictionary as tools/make_dictionary.py made it, if made."""
    path = os.path.join(dictionary.DATA_DIR, dictionary.DEVICE_NAME)
    return path if os.path.isfile(path) else None


def install_dictionary(replace: bool = False) -> Dict[str, str]:
    """The Turkish dictionary copied into documents/dictionaries/;
    `replace`: the one there is an older make of it, and gives way."""
    path = dictionary_file()
    if not path:
        raise FileNotFoundError(dictionary.DEVICE_NAME)
    return kindle_usb.put_files(DICTIONARY_FOLDER, [path],
                                replace=(dictionary.DEVICE_NAME,) if replace else ())
