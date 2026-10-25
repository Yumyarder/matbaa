"""The site's counter: "this press has set N books", by genre.

When a book leaves Matbaa for the first time (exported, or sent to the
Kindle), the reader's app sends one line to Matbaa's site:
{"tur": "felsefe", "v": 1}. No title, no file, no name, no page count; the
site stores the genre and the hour (functions/api/sayac.js). It runs only in
the reader's app, where run_server.py gives the address
(MATBAA_COUNTER_URL); development servers and tests send nothing.

The reader is told once (a line under the look switch) and can turn it off
in "Hakkında ve lisanslar"; turned off, nothing is sent and nothing kept.
Without a network the line waits in a short list (at most 50) and goes with
the next book.
"""
from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from typing import Dict, List

SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".matbaa", "sayac.json")
TIMEOUT = 3
MAX_PENDING = 50
_LOCK = threading.Lock()


def url() -> str:
    return os.environ.get("MATBAA_COUNTER_URL", "")


def load() -> Dict:
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
    return {"enabled": data.get("enabled", True), "notice_seen": bool(data.get("notice_seen")),
            "pending": [g for g in data.get("pending") or [] if isinstance(g, str)][-MAX_PENDING:]}


def _save(data: Dict) -> None:
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    tmp = SETTINGS_FILE + ".part"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, SETTINGS_FILE)


def state() -> Dict:
    data = load()
    return {"enabled": data["enabled"], "notice_seen": data["notice_seen"], "active": bool(url())}


def settings(enabled=None, notice_seen=None) -> Dict:
    """The reader's choice, changed where given; turning it off forgets
    what was waiting to be sent."""
    with _LOCK:
        data = load()
        if enabled is not None:
            data["enabled"] = bool(enabled)
            if not enabled:
                data["pending"] = []
        if notice_seen is not None:
            data["notice_seen"] = bool(notice_seen)
        _save(data)
    return {"enabled": data["enabled"], "notice_seen": data["notice_seen"], "active": bool(url())}


def _post(genre: str) -> bool:
    body = json.dumps({"tur": genre, "v": 1}).encode("utf-8")
    req = urllib.request.Request(url(), data=body, method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "Matbaa/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310 - Matbaa's own site
            return 200 <= resp.status < 300
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _send(genres: List[str]) -> None:
    """Send what waits plus the new one; keep what did not go."""
    left = []
    for i, g in enumerate(genres):
        if not _post(g):
            left = genres[i:]
            break
    with _LOCK:
        data = load()
        if data["enabled"]:
            data["pending"] = (left + data["pending"])[-MAX_PENDING:] if left else data["pending"]
            _save(data)


_SUMMARY = {"at": 0.0, "data": None}
SUMMARY_SECONDS = 300


def summary() -> Dict:
    """What the site's counter says, for the start screen: the total, each
    genre with its name, the latest; kept five minutes. {"available": False}
    outside the reader's app or when the site cannot be reached."""
    import time

    from app.genre import label

    if not url():
        return {"available": False}
    if time.time() - _SUMMARY["at"] < SUMMARY_SECONDS and _SUMMARY["data"] is not None:
        return _SUMMARY["data"]
    req = urllib.request.Request(url(), headers={"User-Agent": "Matbaa/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310 - Matbaa's own site
            raw = json.loads(resp.read().decode("utf-8"))
        data = {"available": True, "total": int(raw.get("total") or 0),
                "genres": [{"id": g["tur"], "label": label(g["tur"]), "n": int(g["n"])} for g in raw.get("genres") or []],
                "recent": [{"id": r["tur"], "label": label(r["tur"]), "hour": r["saat"]} for r in raw.get("recent") or []]}
    except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError):
        data = {"available": False}
    _SUMMARY.update(at=time.time(), data=data)
    return data


def count(session) -> bool:
    """Count the book once, if the reader's app has a counter and the reader
    has not turned it off. Returns whether the book was counted now; the
    sending happens in the background."""
    if session.counted or not url():
        return False
    session.counted = True
    with _LOCK:
        data = load()
        if not data["enabled"]:
            return False
        waiting, data["pending"] = data["pending"], []
        _save(data)
    genres = waiting + [session.genre or "diger"]
    try:
        threading.Thread(target=_send, args=(genres,), daemon=True).start()
    except RuntimeError:
        # no threads: Matbaa in the browser (app/browser.py) sends it now
        _send(genres)
    return True
