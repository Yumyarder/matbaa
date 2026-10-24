"""Kitapla sohbet: search a book, ask it, check the answer, keep it
(backend/app/search.py, ask.py, the API).

    python tools/test_ask.py

A stand-in answers as the language model would. Exit code is 1 if anything
fails.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
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
os.environ["MATBAA_NOTEBOOK"] = tempfile.mkdtemp()

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        failures.append(name)


ANSWER = ("Gramsci'ye göre hegemonya rızaya dayanır: \"hegemonya zor ile rızanın bir bileşimidir\" [s. 41]. "
          "Kitap ayrıca \"devlet yalnızca bir baskı aracı değildir\" der [s. 12]. "
          "Uydurma bir alıntı: \"bu cümle kitapta hiç geçmiyor ki\" [s. 99].")
asked: list = []


class Model(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])).decode("utf-8"))
        asked.append(body)
        data = json.dumps({"choices": [{"message": {"content": ANSWER}}]}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


server = HTTPServer(("127.0.0.1", 0), Model)
threading.Thread(target=server.serve_forever, daemon=True).start()
os.environ["MATBAA_LLM_PROVIDER"] = "openai"
os.environ["MATBAA_LLM_MODEL"] = "stand-in"
os.environ["MATBAA_LLM_BASE_URL"] = f"http://127.0.0.1:{server.server_port}"

from app import ask, search  # noqa: E402
from app.builders.css_template import MATBAA_CSS  # noqa: E402
from app.models import ChapterOut, ConversionSession  # noqa: E402
from app.session_store import save_session  # noqa: E402
from app.turkish_words import Lemmatizer  # noqa: E402

PAGE = '<span epub:type="pagebreak" role="doc-pagebreak" id="page-{0}" aria-label="{0}"></span>'
chapters = [
    ChapterOut(id="ch_0001", index=0, title="Devlet", html=(
        f"<p>Bu bölüm devlet üzerine.{PAGE.format(12)} Yazara göre devlet yalnızca bir baskı aracı değildir; "
        "aynı zamanda bir eğitim kurumudur ve toplumu biçimlendirir.</p>"
        "<p>Kentlerde mahalle meclisleri kuruldu ve kararlar ortaklaşa alındı, bu pratik yayıldı.</p>")),
    ChapterOut(id="ch_0002", index=1, title="Hegemonya", html=(
        f"<p>Hegemonyanın kuruluşu uzun sürer.{PAGE.format(41)} Gramsci'nin düşüncesinde hegemonya zor ile "
        "rızanın bir bileşimidir; egemen sınıf rızayı kültür yoluyla örgütler.</p>"
        "<p>Sivil toplumun kurumları, okullar ve kiliseler, hegemonyanın taşıyıcılarıdır.</p>")),
]
session = ConversionSession(session_id="s-sor", book_title="Hapishane Defterleri", author="Antonio Gramsci",
                            language="tr", chapters=chapters, css=MATBAA_CSS)
other = ConversionSession(session_id="s-baska", book_title="Müşterek Mekan", author="Stavros Stavrides",
                          language="tr", chapters=[ChapterOut(id="ch_0001", index=0, title="Giriş", html=(
                              "<p>Müşterekler, ortaklaşa kullanılan ve birlikte yönetilen kaynaklardır; mahalle "
                              "meclisleri bunun bir örneğidir.</p>"))], css=MATBAA_CSS)
save_session(session)
save_session(other)

print("\nSearch")
lem = Lemmatizer({"hegemonya", "rıza", "devlet", "kurum", "meclis", "mahalle", "müşterek", "kent"}).lemma
index = search.BookIndex(session, lem)
hits = search.search([index], "Gramsci hegemonyayı nasıl tanımlar?")
check("the passage a question is about comes first", hits and hits[0].chapter_id == "ch_0002"
      and "hegemonya zor ile" in hits[0].text)
check("with its printed pages (a passage running over a page)", hits[0].page == "12–41")
check("words found in other forms (\"hegemonyayı\", \"rızanın\")", search.query_terms(index, "hegemonyayı rızanın")
      == ["hegemonya", "riza"])
check("the question's own words do not count (\"nasıl\", \"nedir\")",
      search.query_terms(index, "devlet nedir nasıl") == ["devlet"])
both = search.search([index, search.BookIndex(other, lem)], "mahalle meclisleri")
check("across books, each hit with its book", {h.book_title for h in both} == {"Hapishane Defterleri", "Müşterek Mekan"})
check("nothing matching: nothing found", search.search([index], "uzay gemisi") == [])
copy = ConversionSession(session_id="s-kopya", book_title="Hapishane Defterleri (2)", author="Antonio Gramsci",
                         language="tr", chapters=chapters, css=MATBAA_CSS)
twice = search.search([index, search.BookIndex(copy, lem)], "Gramsci hegemonyayı nasıl tanımlar?")
check("a passage two saved copies of a book share is shown once",
      len([h for h in twice if "hegemonya zor ile" in h.text]) == 1)

print("\nThe request, and the answer checked")
found = search.passages([index], "Gramsci hegemonyayı nasıl tanımlar?", 4)
request = ask.prompt("Gramsci hegemonyayı nasıl tanımlar?", found)
check("the request: the rules, the book, the question and numbered passages with pages",
      request.startswith(ask.SYSTEM) and "Kitap: Hapishane Defterleri" in request
      and "[1] (s. 12–41 · Hegemonya)" in request)
result = ask.check(ANSWER, found, session)
q = {x["text"][:20]: x for x in result["quotes"]}
check("a quotation in the passages, on the page cited", q["hegemonya zor ile rı"]["found"]
      and q["hegemonya zor ile rı"]["page_ok"] is True)
check("a quotation found elsewhere in the book, its page checked too", q["devlet yalnızca bir "]["found"]
      and q["devlet yalnızca bir "]["page"] == "12" and q["devlet yalnızca bir "]["page_ok"] is True)
check("a quotation the book does not have is marked, not hidden", not q["bu cümle kitapta hiç"]["found"]
      and not result["ok"])
check("an answer citing nothing is marked", ask.check("Hegemonya rızadır.", found, session)["uncited"])

print("\nInto the book's note")
vault = tempfile.mkdtemp()
note = os.path.join(vault, "Hapishane Defterleri.md")
with open(note, "w", encoding="utf-8") as f:
    f.write("---\ntags:\n  - Kitap\n---\n\n## Giriş\n\n> Bir vurgu.\n==benim notum==\n\n## Final Notes\n\nKendi düşüncem.\n")
plan = ask.plan_note(note, True, "Gramsci hegemonyayı nasıl tanımlar?", "Rıza ve zorun bileşimi [s. 41].", found,
                     "Hapishane Defterleri")
check("the question as the reader's open task, the answer in the collapsed AI box",
      "- [ ] Gramsci hegemonyayı nasıl tanımlar?\n> [!quote]- *Yardımcı bağlam · AI*\n> *Rıza ve zorun bileşimi [s. 41].*"
      in plan.text and "> *Pasajlar: s. 12–41" in plan.text)
check("in its own section, before the reader's closing notes", plan.text.index("## Kitaba sorduklarım")
      < plan.text.index("## Final Notes") and plan.text.endswith("Kendi düşüncem.\n"))
check("nothing of the note is lost", all(ln in plan.text.splitlines() for ln in open(note, encoding="utf-8").read().splitlines()))
from app import wordbook  # noqa: E402

wordbook.write(plan)
again = ask.plan_note(note, True, "Gramsci hegemonyayı nasıl tanımlar?", "Rıza ve zorun bileşimi [s. 41].", found,
                      "Hapishane Defterleri")
check("the same answer is not written twice", not again.diff)
second = ask.plan_note(note, True, "Sivil toplum nedir?", "Okullar ve kiliseler [s. 41].", found, "Hapishane Defterleri")
check("a second question joins the section", second.text.count("- [ ] ") == 2
      and second.text.index("Sivil toplum") < second.text.index("## Final Notes"))

print("\nThe API")
from fastapi.testclient import TestClient  # noqa: E402

from app import main, obsidian  # noqa: E402

client = TestClient(main.app)
r = client.get("/api/search", params={"q": "mahalle meclisleri"}).json()
check("searching every saved book", {h["book_title"] for h in r["hits"]} == {"Hapishane Defterleri", "Müşterek Mekan"})
r = client.get("/api/search", params={"q": "mahalle meclisleri", "session_id": "s-baska"}).json()
check("or one", {h["book_title"] for h in r["hits"]} == {"Müşterek Mekan"})
r = client.post("/api/ask", json={"question": "Gramsci hegemonyayı nasıl tanımlar?", "session_id": "s-sor"}).json()
check("asking without a model: the passages and the request to copy", r["passages"] and "Soru: Gramsci" in r["prompt"]
      and "answer" not in r and not asked)
r = client.post("/api/ask", json={"question": "Gramsci hegemonyayı nasıl tanımlar?", "session_id": "s-sor",
                                  "model": True}).json()
check("asking the model: its answer, checked", r["answer"] == ANSWER and r["check"]["quotes"]
      and not r["check"]["ok"] and len(asked) == 1)
check("the model was given the rules and the passages", asked[0]["messages"][0]["content"] == ask.SYSTEM
      and "[1] (s. 12–41" in asked[0]["messages"][1]["content"])
r = client.post("/api/ask/check", json={"question": "Gramsci hegemonyayı nasıl tanımlar?", "session_id": "s-sor",
                                        "answer": "\"hegemonya zor ile rızanın bir bileşimidir\" [s. 41]"}).json()
check("an answer pasted back from ChatGPT, checked", r["ok"] and r["quotes"][0]["page_ok"] is True)
vault2 = tempfile.mkdtemp()
os.makedirs(os.path.join(vault2, "2 - Kaynak", "Kitap"))
real = obsidian.load_settings
obsidian.load_settings = lambda: {"vault": vault2}
try:
    body = {"question": "Gramsci hegemonyayı nasıl tanımlar?", "session_id": "s-sor", "answer": "Rıza [s. 41]."}
    plan = client.post("/api/ask/plan", json=body).json()
    check("a new book note when there is none", plan["file"]["name"] == "Hapishane Defterleri.md"
          and not plan["file"]["exists"] and "Author: Antonio Gramsci" in plan["file"]["text"])
    check("written only as previewed", client.post("/api/ask/write", json={**body, "token": "x"}).status_code == 409)
    w = client.post("/api/ask/write", json={**body, "token": plan["token"]}).json()
    check("written", len(w["written"]) == 1 and os.path.isfile(os.path.join(vault2, "2 - Kaynak", "Kitap",
                                                                             "Hapishane Defterleri.md")))
finally:
    obsidian.load_settings = real

print("\nThe reader's own model settings")
from app import llm  # noqa: E402

llm.SETTINGS_FILE = os.path.join(tempfile.mkdtemp(), "llm.json")
llm.LOCAL_SERVER = "http://127.0.0.1:9"          # nothing listens there
r = client.put("/api/llm/settings", json={"provider": "anthropic", "model": "claude-test", "api_key": "test-key-1"})
view = client.get("/api/llm/settings").json()
check("saved; the page is told a key is there, never the key", r.status_code == 200 and view["has_key"]
      and view["model"] == "claude-test" and "test-key-1" not in json.dumps(view))
client.put("/api/llm/settings", json={"provider": "anthropic", "model": "claude-other", "api_key": ""})
saved = json.load(open(llm.SETTINGS_FILE, encoding="utf-8"))
check("a key left empty keeps the one saved", saved["api_key"] == "test-key-1" and saved["model"] == "claude-other")
check("a provider it does not know is refused", client.put("/api/llm/settings",
                                                           json={"provider": "x", "model": "m"}).status_code == 400)
check("no local model server: none offered", view["local"] is None)
client.put("/api/llm/settings", json={"clear": True})
check("and the settings can be forgotten", not os.path.exists(llm.SETTINGS_FILE))

server.shutdown()
if failures:
    print(f"\n{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("\nALL CHECKS PASSED")
