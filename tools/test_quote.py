"""The start screen's line before any Kindle passage (backend/app/quote_lookup.py
and GET /api/start/quote).

    python tools/test_quote.py

Vikisöz is answered by a stand-in server; nothing here goes online. Exit
code is 1 if anything fails.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "backend"))
os.environ["MATBAA_PROJECTS"] = tempfile.mkdtemp()
os.environ.pop("MATBAA_ONLINE", None)

from app import quote_lookup  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        failures.append(name)


BOOK_PAGE = """<div class="mw-parser-output"><table class="infobox"><tr><td><ul><li>Bir kutudaki satır, alıntı değil ve yeterince uzun bir metin.</li></ul></td></tr></table>
<ul><li>"Öğrenciyim," diye mırıldandı genç adam, biraz eğilerek kapıdan içeri girerken.</li>
<li>Yoksulluk ayıp değil, bir gerçek; ama sefillik, sayın bayım, sefillik yüz karasıdır.<ul><li>Birinci Bölüm, s. 14</li></ul></li>
<li>Kısa.</li></ul></div>"""
AUTHOR_PAGE = """<div class="mw-parser-output"><ul><li>İnsan bir gizemdir; tüm yaşamını onu çözmekle geçirsen, zamanını boşa harcamış olmazsın.</li></ul></div>"""
PAGES = {"Suç ve Ceza": BOOK_PAGE, "Fyodor Dostoyevski": AUTHOR_PAGE}
asked: list[str] = []


class Wiki(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if q.get("action") == ["query"]:
            text = q["srsearch"][0]
            asked.append(text)
            data = {"query": {"search": [{"title": text}] if text in PAGES else []}}
        else:
            data = {"parse": {"text": PAGES.get(q["page"][0], "")}}
        body = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


server = HTTPServer(("127.0.0.1", 0), Wiki)
threading.Thread(target=server.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{server.server_port}/w/api.php"
quote_lookup.SITES = [("tr", base, "Vikisöz")]

print("A page's quotes: its top-level items, a readable length, no dialogue scraps")
found = quote_lookup.quotes_in(BOOK_PAGE)
check("the infobox's line and the source under a quote are left out",
      found == ["Yoksulluk ayıp değil, bir gerçek; ama sefillik, sayın bayım, sefillik yüz karasıdır."])

print("The book's page, else its author's, else nothing")
q = quote_lookup.look_up("Suç ve Ceza", "Fyodor Dostoyevski")
check("the book's own page gives the line", q and q["kind"] == "book" and q["text"].startswith("Yoksulluk ayıp değil"))
check("with its author and where it came from", q["author"] == "Fyodor Dostoyevski" and q["source"] == "Vikisöz: Suç ve Ceza"
      and q["url"].endswith("/wiki/Su%C3%A7%20ve%20Ceza"))
q = quote_lookup.look_up("Bilinmeyen Bir Roman", "Fyodor Dostoyevski")
check("a book without a page: its author's line", q and q["kind"] == "author" and q["text"].startswith("İnsan bir gizemdir"))
check("nothing known: None", quote_lookup.look_up("Kayıp Kitap", "Kimse") is None)
check("only titles and names were asked", set(asked) <= {"Suç ve Ceza", "Fyodor Dostoyevski", "Bilinmeyen Bir Roman",
                                                          "Kayıp Kitap", "Kimse"})

print("On the start screen")
from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402
from app.models import ConversionSession  # noqa: E402
from app.session_store import get_session, save_session  # noqa: E402

client = TestClient(main.app)
r = client.get("/api/start/quote").json()
check("no books: Trotsky's line for everyone", r["book"] is None and r["quote"]["author"] == "Lev Troçki"
      and "güneşi de söndürürüz" in r["quote"]["text"])
save_session(ConversionSession(session_id="s-suc", book_title="Suç ve Ceza", author="Fyodor Dostoyevski",
                               chapters=[], css=""))
asked.clear()
r = client.get("/api/start/quote").json()
check("a development server does not look it up", r["quote"]["kind"] == "fallback" and asked == [])
os.environ["MATBAA_ONLINE"] = "1"
r = client.get("/api/start/quote").json()
check("the reader's app shows a line from their latest book", r["book"]["title"] == "Suç ve Ceza"
      and r["quote"]["kind"] == "book")
asked.clear()
client.get("/api/start/quote")
check("looked up once, kept with the book", asked == [] and get_session("s-suc").web_quote["kind"] == "book")
save_session(ConversionSession(session_id="s-yok", book_title="Kayıp Kitap", author="Kimse", chapters=[], css=""))
r = client.get("/api/start/quote").json()
check("a book Vikisöz does not know: Trotsky's line", r["book"]["title"] == "Kayıp Kitap" and r["quote"]["kind"] == "fallback")
check("and it is not asked again", get_session("s-yok").web_quote == {"none": True})
os.environ.pop("MATBAA_ONLINE", None)
server.shutdown()

print()
if failures:
    print(f"{len(failures)} FAILED")
    sys.exit(1)
print("ALL CHECKS PASSED")
