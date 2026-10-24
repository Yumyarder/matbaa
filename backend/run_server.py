"""
Matbaa — single-process launcher.

Run this directly with `python run_server.py` for a "just double-click and
it works" experience: it starts the FastAPI backend AND serves the built
React frontend from the same process/port, then opens your browser to it
automatically. This is also the entry point PyInstaller uses to build a
standalone .exe (see build_exe.bat / matbaa.spec).

Requires the frontend to already be built once (`cd frontend && npm run
build`) — that drops the production bundle into backend/app/frontend_dist,
which app/main.py serves automatically when it's present.
"""

import os
import socket
import sys
import threading
import time
import webbrowser

import uvicorn

HOST = "127.0.0.1"
# MATBAA_PORT runs a second copy beside the reader's own (tests, a smoke test
# of the packaged .exe); MATBAA_NO_BROWSER keeps it from opening a tab.
PORT = int(os.environ.get("MATBAA_PORT") or 8765)
OPEN_BROWSER = not os.environ.get("MATBAA_NO_BROWSER")
# The reader's app looks a new book's genre up on Wikidata (app/genre_lookup.py)
# and adds each book, by genre alone, to the site's counter (app/counter.py);
# development servers and the tests never go online.
os.environ.setdefault("MATBAA_ONLINE", "1")
# The published site's counter, e.g. "https://matbaa.pages.dev/api/sayac".
# Empty until the site exists under that name (docs/YAYIN.md): a pages.dev
# name nobody has claimed yet could be claimed by anyone.
COUNTER_URL = ""
if COUNTER_URL:
    os.environ.setdefault("MATBAA_COUNTER_URL", COUNTER_URL)


def _port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) != 0


def _open_browser_when_ready():
    # Poll instead of a fixed sleep — starting the server (importing
    # PyMuPDF/ebooklib etc.) can take a couple seconds the first time,
    # especially from a frozen .exe.
    for _ in range(60):
        if not _port_is_free(HOST, PORT):
            webbrowser.open(f"http://{HOST}:{PORT}")
            return
        time.sleep(0.25)


def main() -> None:
    # When frozen by PyInstaller, sys.path needs the bundle root so
    # `import app.main` resolves the same way it does in dev.
    if getattr(sys, "frozen", False):
        sys.path.insert(0, os.path.dirname(sys.executable))
    else:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    if not _port_is_free(HOST, PORT):
        print(f"Matbaa seems to already be running at http://{HOST}:{PORT} — opening it.")
        if OPEN_BROWSER:
            webbrowser.open(f"http://{HOST}:{PORT}")
        return

    if OPEN_BROWSER:
        threading.Thread(target=_open_browser_when_ready, daemon=True).start()

    print(f"Matbaa starting at http://{HOST}:{PORT}  (Ctrl+C to stop)")
    uvicorn.run("app.main:app", host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
