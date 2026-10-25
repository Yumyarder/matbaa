"""The site's counter: what the reader's app sends (backend/app/counter.py)
and what the site keeps (functions/api/sayac.js).

    python tools/test_counter.py

The site is a stand-in server here; the Pages Function runs under Node
against an in-memory SQLite with the real schema. Exit code is 1 if
anything fails.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "backend"))
os.environ["MATBAA_PROJECTS"] = tempfile.mkdtemp()
os.environ.pop("MATBAA_COUNTER_URL", None)

from app import counter  # noqa: E402

counter.SETTINGS_FILE = os.path.join(tempfile.mkdtemp(), "sayac.json")
failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        failures.append(name)


received: list[dict] = []
headers_seen: list[dict] = []
got: list[str] = []


class Site(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        got.append(self.path)
        body = json.dumps({"total": 15, "genres": [{"tur": "felsefe", "n": 5}, {"tur": "rus-edebiyati", "n": 2}],
                           "recent": [{"tur": "felsefe", "saat": "2026-10-24T09"}]}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        received.append(json.loads(self.rfile.read(n).decode("utf-8")))
        headers_seen.append(dict(self.headers))
        self.send_response(201)
        self.end_headers()

    def log_message(self, *args):
        pass


site = HTTPServer(("127.0.0.1", 0), Site)
threading.Thread(target=site.serve_forever, daemon=True).start()
SITE = f"http://127.0.0.1:{site.server_port}/api/sayac"


def wait_for(n: int, timeout: float = 5.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if len(received) >= n:
            return True
        time.sleep(0.05)
    return len(received) >= n


def book(genre="felsefe"):
    return SimpleNamespace(counted=False, genre=genre)


print("Only the reader's app counts, and only once")
b = book()
check("no counter address (tests, development): nothing counted", counter.count(b) is False and not b.counted)
os.environ["MATBAA_COUNTER_URL"] = SITE
b = book()
check("the reader's app counts a book", counter.count(b) is True and b.counted)
check("the site receives the genre and nothing else", wait_for(1) and received == [{"tur": "felsefe", "v": 1}])
check("no cookie, no referrer", not any(k.lower() in ("cookie", "referer") for k in headers_seen[0]))
check("a book is counted once", counter.count(b) is False and len(received) == 1)

print("The reader decides")
counter.settings(enabled=False)
b = book("siyaset")
check("turned off: nothing sent", counter.count(b) is False and not wait_for(2, 0.5))
check("and the book is not counted later either", b.counted)
counter.settings(enabled=True)

print("Offline: the line waits and goes with the next book")
os.environ["MATBAA_COUNTER_URL"] = "http://127.0.0.1:9/api/sayac"
counter.count(book("rus-edebiyati"))
end = time.time() + 5
while time.time() < end and not counter.load()["pending"]:
    time.sleep(0.05)
check("kept while the site cannot be reached", counter.load()["pending"] == ["rus-edebiyati"])
os.environ["MATBAA_COUNTER_URL"] = SITE
counter.count(book("tarih"))
check("sent with the next one", wait_for(3) and received[1:] == [{"tur": "rus-edebiyati", "v": 1}, {"tur": "tarih", "v": 1}])
check("nothing left waiting", counter.load()["pending"] == [])
counter.settings(enabled=False)
check("turning it off forgets what waited", counter.load()["pending"] == [])
counter.settings(enabled=True)

print("In the app: the first export counts, the next does not")
import pymupdf as fitz  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402

work = tempfile.mkdtemp()
pdf = os.path.join(work, "b.pdf")
doc = fitz.open()
for _ in range(6):
    doc.new_page(width=420, height=595).insert_textbox(
        fitz.Rect(50, 60, 370, 540), "Felsefenin temel sorusu varlık ile bilinç arasındaki ilişkidir. " * 30, fontsize=10)
doc.save(pdf)
doc.close()
client = TestClient(main.app)
with open(pdf, "rb") as fh:
    up = client.post("/api/upload", files={"file": ("Ayşe Yılmaz - Bir Deneme.pdf", fh, "application/pdf")}).json()
s = client.post(f"/api/convert/{up['upload_id']}", json={"excluded_pages": [], "image_pages": [], "toc_pages": []}).json()
before = len(received)
client.post(f"/api/session/{s['session_id']}/export")
check("the first export adds the book, by its genre", wait_for(before + 1) and received[-1] == {"tur": s["genre"], "v": 1})
client.post(f"/api/session/{s['session_id']}/export")
time.sleep(0.4)
check("a second export does not", len(received) == before + 1)
check("the book remembers it was counted", client.get(f"/api/session/{s['session_id']}").json().get("counted") is True)
st = client.get("/api/counter").json()
check("the app says whether it counts", st == {"enabled": True, "notice_seen": False, "active": True})
st = client.post("/api/counter", json={"notice_seen": True}).json()
check("the reader has seen the notice", st["notice_seen"] is True and counter.load()["notice_seen"] is True)
st = client.post("/api/counter", json={"enabled": False}).json()
check("and can turn it off from the app", st["enabled"] is False)

print("The start screen reads the counter")
summary = client.get("/api/counter/summary").json()
check("the total, each genre with its name, the latest",
      summary.get("available") and summary["total"] == 15
      and summary["genres"][0] == {"id": "felsefe", "label": "Felsefe", "n": 5}
      and summary["recent"][0] == {"id": "felsefe", "label": "Felsefe", "hour": "2026-10-24T09"})
client.get("/api/counter/summary")
check("kept a while: the site is asked once", len(got) == 1)
os.environ.pop("MATBAA_COUNTER_URL", None)
check("outside the reader's app: nothing to show", client.get("/api/counter/summary").json() == {"available": False})
os.environ["MATBAA_COUNTER_URL"] = SITE
site.shutdown()

print("The site's function, on the real schema")
try:
    run = subprocess.run(["node", os.path.join(REPO_ROOT, "tools", "qa", "counter_function_check.mjs")],
                         capture_output=True, text=True, encoding="utf-8", timeout=60)
    out = json.loads(run.stdout.strip().splitlines()[-1])
except (OSError, ValueError, IndexError, subprocess.TimeoutExpired) as exc:
    out = None
    check(f"node runs the function ({exc})", False)
if out:
    check("a known genre is stored", out["valid"] == 201)
    check("anything else in the request is ignored", out["extraIgnored"] == 201)
    check("an unknown genre is refused", out["unknown"] == 400)
    check("a body that is not JSON is refused", out["notJson"] == 400)
    check("a long body is refused", out["tooLarge"] == 413)
    check("a row is the genre, the day and the hour, no address", out["columns"] == ["id", "tur", "gun", "saat"])
    body = out["get"]["body"]
    check("the front page gets the total and each genre", body["total"] == 4
          and body["genres"][0] == {"tur": "felsefe", "n": 2})
    check("and the latest, by genre and hour only", body["recent"] and set(body["recent"][0]) == {"tur", "saat"})
    check("cached a minute", out["get"]["cache"] == "public, max-age=60")
    check("past the day's limit: refused", out["overDailyLimit"] == 429)

print()
if failures:
    print(f"{len(failures)} FAILED")
    sys.exit(1)
print("ALL CHECKS PASSED")
