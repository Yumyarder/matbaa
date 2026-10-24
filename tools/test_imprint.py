"""The book's imprint (backend/app/imprint.py, book_lookup.py, the builder,
the API).

    python tools/test_imprint.py

Imprint pages written here after the library's real ones; the online
lookup is answered by a stand-in server. Exit code is 1 if anything fails.
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
import tempfile
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "backend"))
os.environ["MATBAA_PROJECTS"] = tempfile.mkdtemp()

from PIL import Image  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        failures.append(name)


# --- a stand-in for Open Library ------------------------------------------------
def jpeg(w: int, h: int) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (w, h), (180, 30, 30)).save(out, "JPEG")
    return out.getvalue()


ROUTES = {
    "/isbn/9789755709246.json": json.dumps({"title": "Müsterek Mekan", "publishers": ["Sel Yayincilik"],
                                           "publish_date": "Nov 01, 2018", "authors": [{"key": "/authors/OL1A"}]}),
    "/authors/OL1A.json": json.dumps({"name": "Stavros Stavrides"}),
    "/b/isbn/9789755709246-L.jpg": jpeg(400, 620),
    "/b/isbn/9786051721064-L.jpg": jpeg(60, 90),
    "/isbn/9786051721064.json": json.dumps({"title": "Devlet ve Devrim", "publishers": ["Yordam"],
                                           "publish_date": "2016"}),
}
asked: list[str] = []


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        asked.append(self.path)
        body = ROUTES.get(self.path.split("?")[0])
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(200)
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


server = HTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{server.server_port}"
os.environ["MATBAA_OPENLIBRARY_URL"] = base
os.environ["MATBAA_COVERS_URL"] = base
os.environ["MATBAA_GOOGLEBOOKS_URL"] = base + "/google"

from app import book_lookup, imprint  # noqa: E402
from app.builders.css_template import MATBAA_CSS  # noqa: E402
from app.builders.epub_builder import build_epub  # noqa: E402
from app.models import ChapterOut  # noqa: E402
from app.validate import check_epub  # noqa: E402

print("\nISBNs")
check("ISBN-13 with its check digit", imprint.isbns("ISBN 978-975-570-924-6") == ["9789755709246"])
check("ISBN-10 is given as ISBN-13", imprint.isbns("ISBN: 0-306-40615-2") == ["9780306406157"] and
      imprint.to_isbn13("0-306-40615-2") == "9780306406157")
check("a wrong check digit is no ISBN", imprint.isbns("ISBN 978-975-570-924-5") == [])
check("a barcode's bars are no ISBN", imprint.isbns("ISBN 1111111111\n111111111111111") == [])
check("a phone number is no ISBN", imprint.isbns("Tel. 0306406152") == [])
check("an unlabelled 978 thirteen (a barcode's digits) is", imprint.isbns("9786051721064") == ["9786051721064"])

print("\nThe imprint page")
COVER = "STAVROS STAVRIDES\nMÜŞTEREK MEKAN\nTÜRKÇESİ: CENK SARAÇOGLU\n111111111111111\n1"
IMPRINT = """*SEL YAYINCILIK
Kuloğlu Mahallesi, Turnacıbaşı Caddesi,
Tel. (0212) 516 96 85
*SEL YAYINCILIK: 919
ISBN 978-975-570-924-6
MÜŞTEREK MEKAN
Stavros Stavrides
Türkçesi: Cenk Saraçoğlu
Özgün Adı:
Common Space
The City as Commons
© Stavros Stavrides, 2016
Editör: Yalçın Göymen, Bülent Doğan
Birinci Baskı: Haziran, 2018
İkinci Baskı: Kasım, 2019
Sertifika No: 44865
"""
ADS = "Psikonet Yayınlarının diğer kitapları\nİyi Hissetmek 41. Basım\nDavid Eagleman'ın diğer kitapları\n"
imp = imprint.read_pages([(1, COVER), (3, IMPRINT), (220, ADS)])
check("ISBN from the imprint, not the cover's bars", imp.isbn == "9789755709246")
check("the translator in the imprint's own letters, not the cover's capitals", imp.translator == "Cenk Saraçoğlu")
check("the original title under its label, on two lines", imp.original_title == "Common Space The City as Commons")
check("the editors", imp.editor == "Yalçın Göymen, Bülent Doğan")
check("the publisher, in its own case", imp.publisher == "Sel Yayıncılık")
check("this printing is the latest listed", imp.edition == 2 and imp.year == "2019")
check("the pages it came from, not the back pages' advertisements", imp.pages == [1, 3])

other = imprint.read_pages([(4, """Hayatı Yeniden Keşfedin
Çeviren
ler:
Sandy Kohen ve Diana Güler
Editörler:
H. Alp Karaosmanoğlu
"""), (5, """Türkçesi
Uğur Sayal • Ada Sayal
Çevirenler: Uğur Sayal (Psikolog), Ada Sayal
İngilizce aslından çeviren ve yayına hazırlayan: Onur Öztürk
Çeviri dersleri vermektedir. Gerçek gazetesinde köşe yazarı
Birinci Kitap
1. Basım: Mart 2006
24. Basım: Nisan 2016
Copyright © 1980 by David D. Burns
ISBN: 9789759893729
""")])
check("\"Çeviren\" broken over two lines", other.translator == "Sandy Kohen ve Diana Güler")
check("the label alone, the names under it", other.editor == "H. Alp Karaosmanoğlu")
check("a book's volume is no publisher; a sentence is no translator", other.publisher is None)
check("the latest printing's year, not the original's copyright", other.edition == 24 and other.year == "2016")
check("\"Çeviri:\" and \"… çeviren ve yayına hazırlayan:\"",
      imprint.read_pages([(1, "Çeviri: Zeynep Arık Tozar")]).translator == "Zeynep Arık Tozar"
      and imprint.read_pages([(1, "İngilizce aslından çeviren ve yayına hazırlayan: Onur Öztürk")]).translator
      == "Onur Öztürk")
check("\"Özgün ismi:\"", imprint.read_pages([(1, "Özgün ismi: The Runaway Species")]).original_title
      == "The Runaway Species")
check("nothing to read: empty", imprint.read_pages([(1, "Birinci Bölüm\nMetin.")]).empty())

print("\nIn the book")
work = tempfile.mkdtemp()
path = os.path.join(work, "kunye.epub")
chapters = [ChapterOut(id="ch_0001", index=0, title="Giriş", html="<p>Metin.</p>")]
build_epub(book_title="Müşterek Mekan", author="Stavros Stavrides", chapters=chapters, css=MATBAA_CSS,
           output_path=path, language="tr", imprint=imp.to_dict(), imprint_page=True)
with zipfile.ZipFile(path) as z:
    opf = z.read("EPUB/content.opf").decode("utf-8")
    about = z.read("EPUB/bu_baski_hakkinda.xhtml").decode("utf-8")
    nav = z.read("EPUB/nav.xhtml").decode("utf-8")
check("publisher, date and the ISBN in the metadata", "<dc:publisher>Sel Yayıncılık</dc:publisher>" in opf
      and "<dc:date>2019</dc:date>" in opf and "urn:isbn:9789755709246" in opf)
check("the translator and editor with their roles", 'id="trl">Cenk Saraçoğlu</dc:contributor>' in opf
      and 'refines="#trl"' in opf and ">trl<" in opf and 'refines="#edt"' in opf)
check("a page \"Bu baskı hakkında\", at the end and in the contents", "Çeviren:</b> Cenk Saraçoğlu" in about
      and "2. baskı, 2019" in about and "bu_baski_hakkinda.xhtml" in nav)
check("the book is valid", not [f for f in check_epub(path) if f.severity == "error"])
plain = os.path.join(work, "plain.epub")
build_epub(book_title="M", author="A", chapters=chapters, css=MATBAA_CSS, output_path=plain, language="tr",
           imprint=imp.to_dict())
with zipfile.ZipFile(plain) as z:
    check("the page only when asked for", "EPUB/bu_baski_hakkinda.xhtml" not in z.namelist())

print("\nOnline, on request")
found = book_lookup.look_up("9789755709246")
check("Open Library's record, the author by its key", found["source"] == "Open Library"
      and found["authors"] == ["Stavros Stavrides"] and found["year"] == "2018")
check("its cover, big enough", found["cover"] and Image.open(io.BytesIO(base64.b64decode(found["cover"]))).height == 620)
merged, filled = book_lookup.merge({"publisher": "Sel Yayıncılık", "year": None}, found, "tr")
check("only empty fields are filled; the book's own spelling stays", merged["publisher"] == "Sel Yayıncılık"
      and merged["year"] == "2018" and filled == ["year"])
merged, _ = book_lookup.merge({}, found, "tr")
check("an ASCII publisher gets its Turkish letters back", merged["publisher"] == "Sel Yayıncılık")
small = book_lookup.look_up("9786051721064")
check("a thumbnail is no cover", small["cover"] is None)
check("a book nobody knows is None", book_lookup.look_up("9780306406157") is None)
check("and Google Books was asked for it", any(p.startswith("/google/volumes?q=isbn:9780306406157") for p in asked))

print("\nThe API")
from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402
from app.models import ConversionSession  # noqa: E402
from app.session_store import save_session  # noqa: E402

client = TestClient(main.app)
pdf_cover = base64.b64encode(jpeg(600, 900)).decode("ascii")
session = ConversionSession(session_id="s-kunye", book_title="Müşterek Mekan", author="Stavros Stavrides",
                            language="tr", chapters=chapters, css=MATBAA_CSS, cover_image_base64=pdf_cover,
                            imprint={"isbn": "9789755709246", "translator": "Cenk Saraçoğlu"})
save_session(session)
r = client.put("/api/session/s-kunye/meta", json={"imprint": {"publisher": "Sel Yayıncılık", "translator": ""}})
check("a field corrected, a field cleared", r.status_code == 200 and r.json()["imprint"]["publisher"] == "Sel Yayıncılık"
      and r.json()["imprint"]["translator"] is None)
check("a wrong ISBN is refused", client.put("/api/session/s-kunye/meta",
                                            json={"imprint": {"isbn": "978-975-570-924-5"}}).status_code == 400)
r = client.post("/api/session/s-kunye/imprint/lookup")
check("looked up online: the empty year filled, a cover offered", r.status_code == 200
      and r.json()["filled"] == ["year"] and r.json()["found"]["cover"] is True
      and r.json()["session"]["imprint"]["year"] == "2018")
r = client.post("/api/session/s-kunye/cover", json={"kind": "web"})
check("the web cover chosen", r.status_code == 200 and r.json()["cover_kind"] == "web"
      and r.json()["cover_image_base64"] == r.json()["web_cover_base64"])
r = client.post("/api/session/s-kunye/cover", json={"kind": "matbaa"})
r = client.post("/api/session/s-kunye/cover", json={"kind": "pdf"})
check("and the PDF's own cover comes back after any detour", r.json()["cover_kind"] == "pdf"
      and r.json()["cover_image_base64"] == pdf_cover)
client.put("/api/session/s-kunye/meta", json={"imprint_page": True})
r = client.get("/api/session/s-kunye/validate")
check("the exported book, with its imprint page, is valid", r.status_code == 200 and r.json()["valid"])
session2 = ConversionSession(session_id="s-yok", book_title="X", author="Y", language="tr", chapters=chapters,
                             css=MATBAA_CSS)
save_session(session2)
check("no ISBN: said so", client.post("/api/session/s-yok/imprint/lookup").status_code == 409)
check("no web cover yet: refused", client.post("/api/session/s-yok/cover", json={"kind": "web"}).status_code == 409)

server.shutdown()
if failures:
    print(f"\n{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("\nALL CHECKS PASSED")
