"""A book's genre: the local guess (backend/app/genre.py) and what Wikidata
says (backend/app/genre_lookup.py).

    python tools/test_genre.py

Books written here for every genre, none of them the reader's own: a Turkish
novel, translated Russian and Japanese ones, poems, and non-fiction on each
subject, with the traps a real library sets (a blurb's "hikâye", a list's
dashes, a bibliography). Wikidata is answered by a stand-in server; nothing
here goes online. Exit code is 1 if anything fails.
"""
from __future__ import annotations

import json
import os
import sys
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

from app import genre, genre_lookup  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        failures.append(name)


FILLER = ["Bu konuda söylenecek çok şey var ama önce bir adım geri çekilmek gerekiyor.",
          "Yazar bunu ilk bölümde de belirtmiş, örneklerle açıklamaya çalışmıştı.",
          "Okur burada durup kendi deneyimini hatırlayabilir.",
          "Sonraki sayfalarda bu düşünce biraz daha açılacak."]
SUBJECT_SENTENCES = {
    "felsefe": "Felsefenin temel sorusu varlık ile bilinç arasındaki ilişkidir; Kant ve Hegel bu soruyu farklı yanıtladı.",
    "siyaset": "Devlet, sınıf egemenliğinin aracıdır; işçi sınıfının partisi devrim için örgütlenmelidir.",
    "ekonomi": "Sermaye birikimi, piyasada fiyatların ve ücretlerin belirlenmesiyle iktisadi krize yol açar.",
    "tarih": "Osmanlı İmparatorluğu on yedinci yüzyılda padişahların ve hanedanın gücünü yitirdiği bir döneme girdi.",
    "sosyoloji": "Kentsel mekânda gündelik hayat, kimlik ve kamusal alan müşterek kullanım üzerinden yeniden kurulur.",
    "psikoloji": "Bilişsel terapi, depresyon ve kaygı yaşayan danışanın duygularını ve davranışlarını ele alır.",
    "sanat": "Mimarlık, bedenin duyularıyla deneyimlenen bir sanattır; ressam ve heykel de estetik bir mekân kurar.",
    "bilim": "Fizik yasaları, atom ve molekül düzeyindeki deneylerle sınanır; Newton mekaniği bunun ilk örneğidir.",
    "kisisel": "Küçük alışkanlıklar, her gün tekrarlanan bir rutin ve net bir hedef üretken olmanın anahtarıdır.",
    "din": "Peygamberin getirdiği vahiy, Kuran'da Allah'ın sözü olarak kabul edilir; ibadet ve mezhep farkları bundan doğar.",
}
NARRATION = ["Sabah olunca evden çıktım, sokak her zamanki gibi sessizdi.",
             "Annem pencerenin önünde oturmuş, kimseyi beklemiyormuş gibi dışarı bakıyordu.",
             "Köşedeki fırından sıcak ekmek kokusu geliyordu, adımlarımı yavaşlattım.",
             "O akşam eve döndüğümde kapı aralıktı, içeriden bir radyo sesi duyuluyordu."]
DIALOGUE = ["— Nereye gidiyorsun bu saatte? dedi annem.",
            "— Biraz yürüyeceğim, dedim, hemen dönerim.",
            "— Geç kalma, diye seslendi arkamdan.",
            "“Bir şey mi oldu?” diye sordu Ahmet. “Hayır,” dedim, “sadece yoruldum.”"]


def book(paragraphs):
    return "".join(f"<p>{p}</p>" for p in paragraphs)


def nonfiction(subject, n=60):
    return book(f"{SUBJECT_SENTENCES[subject]} {FILLER[i % 4]} {FILLER[(i + 1) % 4]}" for i in range(n))


def novel(n=80):
    return book(DIALOGUE[i % 4] if i % 3 == 0 else NARRATION[i % 4] for i in range(n))


print("Non-fiction: the subject whose stems the text uses most")
for subject in SUBJECT_SENTENCES:
    g = genre.guess("Bir İnceleme", "Ayşe Yılmaz", [("Birinci Bölüm", nonfiction(subject), "chapter")])
    check(f"{subject}: {g.label} ({g.reason})", g.key == subject)

print("Fiction: named on a line of its own, or speaking in dialogue")
g = genre.guess("Uzak Bir Sokak", "Ayşe Yılmaz", [("1", novel(), "chapter")], language="tr")
check(f"a Turkish novel, no translator: {g.label}", g.key == "turk-edebiyati")
g = genre.guess("Kar Altında", "Anonim", [("1", novel(), "chapter")],
                front_text="Rusçadan çeviren: Ayşe Yılmaz\nYordam Kitap")
check(f"“Rusçadan çeviren” on the imprint: {g.label}", g.key == "rus-edebiyati")
g = genre.guess("Kar Altında", "Fyodor Dostoyevski", [("1", novel(), "chapter")])
check(f"a Russian surname, no imprint: {g.label}", g.key == "rus-edebiyati")
g = genre.guess("Sessiz Göl", "Anonim", [("1", novel(), "chapter")],
                front_text="Japonca aslından çeviren: Ali Veli")
check(f"translated from Japanese: {g.label}", g.key == "dunya-edebiyati")
g = genre.guess("Gece Şarkıları", "Ayşe Yılmaz",
                [("I", book(NARRATION[i % 4] for i in range(40)), "chapter")], front_text="ŞİİR\nDeniz Yayınları")
check(f"“Şiir” on a line of its own: {g.label}", g.key == "turk-edebiyati")
check("“Rusçadan çeviren” is read as the language", genre.translated_from("Rusçadan çeviren: X") == "Rusça")
check("“İngilizce aslından çeviren” too", genre.translated_from("İngilizce aslından çeviren: X") == "İngilizce")
check("no translation line: none", genre.translated_from("Yayına hazırlayan: X") is None)

print("Traps")
g = genre.guess("Devrim Üzerine", "Ayşe Yılmaz", [("1", nonfiction("siyaset"), "chapter")],
                front_text="Bu kitabın hikâyesi 1917'de başlar; öyküsü bir devrimin öyküsüdür.")
check(f"a blurb's “hikâye” is not a genre: {g.label}", g.key == "siyaset")
listed = book((f"- {SUBJECT_SENTENCES['siyaset']}" if i % 3 == 0 else f"{SUBJECT_SENTENCES['siyaset']} {FILLER[i % 4]}")
              for i in range(60))
g = genre.guess("Görevlerimiz", "Ayşe Yılmaz", [("1", listed, "chapter")])
check(f"a list's dashes are not dialogue: {g.label}", g.key == "siyaset")
g = genre.guess("Uzak Bir Sokak", "Ayşe Yılmaz", [("1", novel(), "chapter"), ("Kaynakça", "<p>x</p>", "chapter")])
check(f"a bibliography outweighs dialogue: {g.label}", g.key not in genre.FICTION)
g = genre.guess("Not Defteri", "Ayşe Yılmaz", [("1", book(FILLER[i % 4] for i in range(60)), "chapter")])
check(f"no subject's words: {g.label}", g.key == "diger")
habits = book("Small habits, a daily routine and a clear goal make you productive and focused. "
              "The author explains it with simple examples." for _ in range(60))
g = genre.guess("Tiny Changes", "Jane Doe", [("1", habits, "chapter")], language="en")
check(f"an English self-help book: {g.label}", g.key == "kisisel")

# --- Wikidata, answered by a stand-in -------------------------------------------
ANSWERS = {
    "Suç ve Ceza": [("Crime and Punishment", "1970 Soviet drama film"),
                    ("Crime and Punishment", "1866 novel by Fyodor Dostoyevsky")],
    "Fyodor Dostoyevski": [("Fyodor Dostoyevsky", "Russian novelist and philosopher (1821–1881)")],
    "Kürk Mantolu Madonna": [("Madonna in a Fur Coat", "1943 novel by Sabahattin Ali")],
    "Sabahattin Ali": [("Sabahattin Ali", "Turkish novelist, short story writer, poet, and journalist")],
    "Devlet ve Devrim": [("The State and Revolution", "1917 book by Vladimir Lenin")],
    "V. İ. Lenin": [("Vladimir Lenin", "Russian revolutionary and politician (1870–1924)")],
    "David D. Burns": [("David D. Burns", "American psychiatrist and author")],
    "Ali Rıza Kaya": [("Ali Rıza Kaya", "Turkish writer")],
    "Pür Dikkat": [("Deep Work", "2016 book by Cal Newport")],
    "Cal Newport": [("Cal Newport", "American author and computer scientist")],
}
asked: list[str] = []


class Wikidata(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        text = query.get("search", [""])[0]
        asked.append(text)
        results = [{"id": f"Q{i}", "label": label, "description": d} for i, (label, d) in enumerate(ANSWERS.get(text, []))]
        data = json.dumps({"search": results}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


server = HTTPServer(("127.0.0.1", 0), Wikidata)
threading.Thread(target=server.serve_forever, daemon=True).start()
genre_lookup.WIKIDATA = f"http://127.0.0.1:{server.server_port}/w/api.php"

print("Wikidata: the book's own line, else its author's")
f = genre_lookup.look_up("Suç ve Ceza", "Fyodor Dostoyevski")
check("a film of the same name is passed over; the novel's author is Russian",
      f is not None and f.key == "rus-edebiyati" and f.fiction)
f = genre_lookup.look_up("Kürk Mantolu Madonna", "Sabahattin Ali")
check("a novel by a Turkish novelist is Turkish literature", f is not None and f.key == "turk-edebiyati")
f = genre_lookup.look_up("Devlet ve Devrim", "V. İ. Lenin")
check("a book whose line names no subject goes by its author: a revolutionary's is politics",
      f is not None and f.key == "siyaset" and f.level == "author")
f = genre_lookup.look_up("İyi Hissetmek", "David D. Burns")
check("an unknown title by a psychiatrist is psychology", f is not None and f.key == "psikoloji")
f = genre_lookup.look_up("Kayıp Bir Kitap", "Kimse Bilmez")
check("nothing known: None, the local guess decides", f is None)
f = genre_lookup.look_up("Bir Defter", "Ali Rıza Kaya")
check("a plain writer says nothing of the book", f is not None and f.key is None and f.level == "author")
f = genre_lookup.look_up("Pür Dikkat", "Cal Newport")
check("a computer scientist's book is science, as far as Wikidata says", f is not None and f.key == "bilim")
check("only the title and the author were asked", set(asked) <= set(ANSWERS) | {"İyi Hissetmek", "Kayıp Bir Kitap",
                                                                                "Kimse Bilmez", "Bir Defter"})

print("The two together")
local_novel = genre.Guess("turk-edebiyati", "Türk edebiyatı", 0.65, "konuşma")
local_politics = genre.Guess("siyaset", "Siyaset", 0.9, "devrim, sınıf")
d = genre.decide(local_politics, genre_lookup.Found("felsefe", False, "Wikidata: “philosophical work”"))
check("the book's own entry wins", d.key == "felsefe")
d = genre.decide(local_politics, genre_lookup.Found("turk-edebiyati", True, "yazar: novelist", "Turkish novelist", "author"))
check("an author called a novelist does not make a clearly political book a novel", d.key == "siyaset")
d = genre.decide(local_novel, genre_lookup.Found(None, False, "yazar: Russian writer", "Russian writer", "author"))
check("a plain writer's country gives the novel its origin", d.key == "rus-edebiyati")
d = genre.decide(local_politics, None)
check("no answer: the local guess", d.key == "siyaset")

print("In the app: guessed at conversion, Wikidata only for the reader's app, changed by hand")
import tempfile  # noqa: E402
import zipfile  # noqa: E402

import pymupdf as fitz  # noqa: E402

os.environ["MATBAA_PROJECTS"] = tempfile.mkdtemp()
os.environ.pop("MATBAA_ONLINE", None)
from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402

work = tempfile.mkdtemp()
pdf_path = os.path.join(work, "book.pdf")
doc = fitz.open()
text = " ".join(f"{SUBJECT_SENTENCES['siyaset']} {FILLER[i % 4]}" for i in range(14))
for _ in range(12):
    doc.new_page(width=420, height=595).insert_textbox(fitz.Rect(50, 60, 370, 540), text, fontsize=10)
doc.save(pdf_path)
doc.close()
client = TestClient(main.app)


def convert(name):
    with open(pdf_path, "rb") as fh:
        up = client.post("/api/upload", files={"file": (name, fh, "application/pdf")}).json()
    return client.post(f"/api/convert/{up['upload_id']}", json={"excluded_pages": [], "image_pages": [],
                                                                  "toc_pages": []}).json()


asked.clear()
s = convert("V. İ. Lenin - Devlet ve Devrim.pdf")
check(f"a development server reads the book itself: {s.get('genre')} ({s.get('genre_source')})",
      s.get("genre") == "siyaset" and s.get("genre_source") == "auto")
check("and asks Wikidata nothing", asked == [])
os.environ["MATBAA_ONLINE"] = "1"
s = convert("V. İ. Lenin - Devlet ve Devrim.pdf")
os.environ.pop("MATBAA_ONLINE", None)
check(f"the reader's app asks Wikidata: {s.get('genre')} ({s.get('genre_reason')})",
      s.get("genre") == "siyaset" and s.get("genre_source") == "wikidata")
check("with the title and the author only", set(asked) == {"Devlet ve Devrim", "V. İ. Lenin"})
check("the book's report says what it was taken for, and from where",
      any(line.startswith("Tür: Siyaset (Wikidata") for line in (s.get("report") or {}).get("strategy", [])))
r = client.put(f"/api/session/{s['session_id']}/meta", json={"genre": "felsefe"}).json()
check("the reader's choice wins", r.get("genre") == "felsefe" and r.get("genre_source") == "reader")
check("a genre Matbaa does not know is refused",
      client.put(f"/api/session/{s['session_id']}/meta", json={"genre": "uydurma"}).status_code == 400)
listed = {p["session_id"]: p for p in client.get("/api/projects").json()}
check("the library lists each book's genre", listed[s["session_id"]].get("genre") == "felsefe")
epub = client.post(f"/api/session/{s['session_id']}/export")
with zipfile.ZipFile(__import__("io").BytesIO(epub.content)) as z:
    opf = next(z.read(n).decode("utf-8") for n in z.namelist() if n.endswith(".opf"))
check("the EPUB carries it as dc:subject", "<dc:subject>Felsefe</dc:subject>" in opf)
import time  # noqa: E402

kept = main.get_session(s["session_id"])
kept.genre = None
main.save_session(kept)
with TestClient(main.app):
    for _ in range(100):
        if main.get_session(s["session_id"]).genre:
            break
        time.sleep(0.1)
check("a book kept without a genre gets one when the app starts",
      main.get_session(s["session_id"]).genre == "siyaset")

server.shutdown()
genre_lookup.WIKIDATA = "http://127.0.0.1:9/w/api.php"
check("Wikidata unreachable: None, quickly", genre_lookup.look_up("Suç ve Ceza", "Fyodor Dostoyevski") is None)

print()
if failures:
    print(f"{len(failures)} FAILED")
    sys.exit(1)
print("ALL CHECKS PASSED")
