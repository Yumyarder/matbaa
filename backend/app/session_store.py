"""Converted books, kept on disk.

Every edit used to live only in this process's memory: closing the app
lost the book and every correction made to it. A session is now written
through to MATBAA_PROJECTS (default ~/Matbaa/projects), one JSON file per
book, atomically — a write lands in full or not at all — and read back
when the process has never seen it, so a book survives a restart.
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Dict, List, Optional

from app.builders.themes import apply_theme, theme_of
from app.models import ConversionSession

_LOCK = threading.Lock()
_SESSIONS: Dict[str, ConversionSession] = {}


def projects_dir() -> str:
    path = os.environ.get("MATBAA_PROJECTS") or os.path.join(os.path.expanduser("~"), "Matbaa", "projects")
    os.makedirs(path, exist_ok=True)
    return path


def _path(session_id: str) -> str:
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_")
    return os.path.join(projects_dir(), f"{safe}.json")


def save_session(session: ConversionSession) -> None:
    with _LOCK:
        _SESSIONS[session.session_id] = session
        path = _path(session.session_id)
        tmp = path + ".part"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(session.model_dump_json())
        os.replace(tmp, path)


def get_session(session_id: str) -> Optional[ConversionSession]:
    with _LOCK:
        if session_id in _SESSIONS:
            return _SESSIONS[session_id]
        path = _path(session_id)
        if not os.path.exists(path):
            return None
        try:
            with open(path, encoding="utf-8") as fh:
                session = ConversionSession.model_validate_json(fh.read())
        except (OSError, ValueError):
            return None
        # a theme block saved with the book is brought up to the theme as it
        # is now defined, so a theme's correction reaches the books using it
        session.css = apply_theme(session.css, theme_of(session.css))
        _SESSIONS[session_id] = session
        return session


def delete_session(session_id: str) -> None:
    with _LOCK:
        _SESSIONS.pop(session_id, None)
        try:
            os.remove(_path(session_id))
        except OSError:
            pass


def list_projects() -> List[Dict]:
    """The books on disk, most recently changed first, without their text."""
    out = []
    for name in os.listdir(projects_dir()):
        if not name.endswith(".json"):
            continue
        path = os.path.join(projects_dir(), name)
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        chapters = data.get("chapters") or []
        out.append({
            "session_id": data.get("session_id"),
            "book_title": data.get("book_title"),
            "author": data.get("author"),
            "chapters": sum(1 for c in chapters if c.get("kind") == "chapter" and not c.get("is_split_continuation")),
            "score": (data.get("report") or {}).get("score"),
            "language": data.get("language"),
            "has_cover": bool(data.get("cover_image_base64")),
            "genre": data.get("genre"),
            "updated": time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(path))),
            "mtime": os.path.getmtime(path),
        })
    out.sort(key=lambda p: -p["mtime"])
    return out
