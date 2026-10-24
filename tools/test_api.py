"""Regression coverage for the editing API — the operations a person runs
on a converted book, where a bug loses their work rather than a parse.

    python tools/test_api.py

Exit code is 1 if anything fails.
"""
from __future__ import annotations

import json
import os
import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
# books this test saves go to a scratch folder, never the user's own projects
import tempfile as _tempfile  # noqa: E402
os.environ["MATBAA_PROJECTS"] = _tempfile.mkdtemp()
if os.path.join(REPO_ROOT, "backend") not in sys.path:
    sys.path.insert(0, os.path.join(REPO_ROOT, "backend"))

from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402
from app.models import ChapterImage, ChapterOut, ConversionSession, Footnote  # noqa: E402
from app.session_store import save_session  # noqa: E402

client = TestClient(main.app)
failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        failures.append(name)


def noteref(fn_id: str, n: int) -> str:
    return (f'<sup class="footnote-ref" id="fnref_{fn_id}">'
            f'<a epub:type="noteref" href="#{fn_id}">{n}</a></sup>')


print("\nSplitting a chapter keeps each half's figures and notes")
before = f'<p>Birinci yarı{noteref("fn_a", 1)}.</p><figure><img src="images/ch_img1.png"/></figure>'
after = f'<p>İkinci yarı{noteref("fn_b", 2)}.</p><figure><img src="images/ch_img2.png"/></figure>'
session = ConversionSession(
    session_id="test-split", book_title="Kitap", css="",
    chapters=[ChapterOut(
        id="ch_0001", index=0, title="Bölüm", html=before + after,
        footnotes=[Footnote(id="fn_a", marker="1", text="A notu"),
                   Footnote(id="fn_b", marker="2", text="B notu"),
                   Footnote(id="fn_orphan", marker="3", text="Bağlantısız not")],
        images=[ChapterImage(id="ch_img1", base64="AAA"), ChapterImage(id="ch_img2", base64="BBB")],
        toc_path=["1. BÖLÜM"],
    )],
)
save_session(session)
r = client.post("/api/session/test-split/chapter/ch_0001/split",
                json={"before_html": before, "after_html": after, "new_title": "Devamı"})
check("the split is accepted", r.status_code == 200)
first, second = r.json()["chapters"]
check("the first half keeps only its own text", first["html"] == before)
check("the second half's figure goes with it", [i["id"] for i in second["images"]] == ["ch_img2"])
check("and the first half keeps its own", [i["id"] for i in first["images"]] == ["ch_img1"])
check("the second half's note goes with it", [f["id"] for f in second["footnotes"]] == ["fn_b"])
check("a note nothing refers to stays where it was",
      [f["id"] for f in first["footnotes"]] == ["fn_a", "fn_orphan"])
check("the new chapter stays under the same printed heading", second["toc_path"] == ["1. BÖLÜM"])

print("\nSkipping OCR stops it on the server")
main._set_ocr_job("test-ocr", state="running", done=2, total=10)
r = client.post("/api/upload/test-ocr/ocr/cancel")
check("a running pass is asked to stop", r.json()["state"] == "cancelling")



def fake_build(src, dst, pages=None, progress=None, **_):
    # The progress hook is what notices; call it the way the real pass does
    # between pages. Reaching the line after it means nothing stopped.
    progress(3, 10)
    raise RuntimeError("the pass ran on after being cancelled")


real_build = main.ocr_layer.build_searchable_copy
main.ocr_layer.build_searchable_copy = fake_build
try:
    main._run_ocr_job("test-ocr", [0, 1, 2])
finally:
    main.ocr_layer.build_searchable_copy = real_build
check("and the pass ends cancelled, writing no copy", main._ocr_job_state("test-ocr")["state"] == "cancelled")

print("\nThe book's report and its bundle for a language model")
from types import SimpleNamespace  # noqa: E402

from app.diagnosis import build_report  # noqa: E402

broken = ['<p>Kent hakkı üzerine bir tartışma burada başlar ve sayfa sonunda</p>',
          '<p>yarım kalan cümle burada sürer.</p>'] * 30
fake = SimpleNamespace(
    chapters=[SimpleNamespace(id="ch_0001", kind="chapter", is_split_continuation=False, title="Giriş",
                              eyebrow=None, paragraphs=broken, footnotes=[], images=[])],
    warnings=[], detected_language="tr", decisions={"structure": "printed_toc", "toc_sequential": True},
)
report = build_report(fake, {"producer": "Adobe Acrobat Paper Capture"}).to_dict()
check("the report names the kind of PDF", "Taranmış" in report["kind"])
check("and says where the structure came from", any("sırayla" in s for s in report["strategy"]))
issue = next((i for i in report["issues"] if i["code"] == "broken_paragraphs"), None)
check("broken paragraphs are reported with where they are", issue is not None and issue["chapter_ids"] == ["ch_0001"])
save_session(ConversionSession(
    session_id="test-report", book_title="Kitap", css="", report=report,
    chapters=[ChapterOut(id="ch_0001", index=0, title="Giriş", html="".join(broken))],
))
r = client.get("/api/session/test-report/report")
check("the report is served", r.status_code == 200 and r.json()["score"] == report["score"])
r = client.get("/api/session/test-report/report/bundle")
bundle = r.json()
check("the bundle carries each model task with its passages",
      r.status_code == 200 and bundle["tasks"] and "yarım kalan" in bundle["tasks"][0]["passages"][0]["text"])

print("\nA language model proposes, the app checks, the user applies")
from app import llm  # noqa: E402

chapter_html = ('<p>Kent hakkı üzerine <em>Lefebvre</em> ilk kez 196S yılında yazdı ve sayfa sonunda</p>'
                f'<p>yarım kalan cümle burada sürer{noteref("fn_k", 1)}.</p>'
                '<h2 class="subheading">Meydanlar</h2><p>Meydanlarda müşterekleşme.</p>')
save_session(ConversionSession(
    session_id="test-llm", book_title="Kitap", css="", language="tr",
    chapters=[ChapterOut(id="ch_0001", index=0, title="Giriş", html=chapter_html)],
))
real_complete = llm.complete
llm.complete = lambda system, prompt, max_tokens=4000: json.dumps({
    "merge": [1, 7],
    "replace": [{"paragraph": 0, "wrong": "196S", "right": "1965"},
                {"paragraph": 3, "wrong": "Meydanlarda müşterekleşme.", "right": "Kent meydanlarında yepyeni bir hayat."},
                {"paragraph": 0, "wrong": "Haussmann", "right": "Hausmann"}],
})
try:
    r = client.post("/api/session/test-llm/chapter/ch_0001/llm/propose")
finally:
    llm.complete = real_complete
proposals = r.json()["proposals"]
check("the model's proposals are checked against the text",
      r.status_code == 200 and proposals == {"merge": [1], "replace": [{"paragraph": 0, "wrong": "196S", "right": "1965"}]})
r = client.post("/api/session/test-llm/chapter/ch_0001/llm/apply", json=proposals)
html_after = r.json()["chapters"][0]["html"]
check("applied, the cut paragraph is one and the misreading corrected",
      html_after.startswith("<p>Kent hakkı üzerine <em>Lefebvre</em> ilk kez 1965 yılında yazdı ve sayfa sonunda yarım kalan"))
check("and its emphasis, note link and heading are kept",
      'href="#fn_k"' in html_after and '<h2 class="subheading">Meydanlar</h2>' in html_after)

print("\nA book survives the app being closed")
from app import session_store  # noqa: E402

session_store._SESSIONS.clear()                     # as after a restart
back = client.get("/api/session/test-kindle-pre")
check("an unknown book is still unknown", back.status_code == 404)
back = client.get("/api/session/test-llm").json()
check("a saved book is read back from disk", back["chapters"][0]["html"] == html_after)
listed = client.get("/api/projects").json()
check("and listed among the projects", any(p["session_id"] == "test-llm" for p in listed))

print("\nHyphenation is the book's own setting")
check("off for a new book", back.get("hyphenate") is False)
r = client.put("/api/session/test-llm/meta", json={"hyphenate": True})
check("turned on, it is kept", r.status_code == 200 and r.json()["hyphenate"] is True
      and r.json()["book_title"] == back["book_title"])
session_store._SESSIONS.clear()
check("across a restart", client.get("/api/session/test-llm").json()["hyphenate"] is True)

print("\nThe book's look is chosen from the themes")
themes = client.get("/api/themes").json()
check("the app is told the themes, each with a sentence",
      [t["id"] for t in themes][:1] == ["klasik"] and all(t["label"] and t["about"] for t in themes))
before_css = client.get("/api/session/test-llm").json()["css"]
r = client.put("/api/session/test-llm/meta", json={"theme": "modern"})
check("a theme goes into the book's stylesheet", r.status_code == 200
      and "/* matbaa-theme:modern */" in r.json()["css"] and r.json()["css"].startswith(before_css.rstrip()))
r = client.put("/api/session/test-llm/meta", json={"theme": "klasik"})
check("and Klasik takes it out again", r.json()["css"].rstrip() == before_css.rstrip())
check("an unknown theme is refused", client.put("/api/session/test-llm/meta", json={"theme": "neon"}).status_code == 400)

print("\nSending to a Kindle: only configured, only confirmed, only a valid EPUB")
import tempfile  # noqa: E402

from app import kindle_send  # noqa: E402

kindle_send.SETTINGS_FILE = os.path.join(tempfile.mkdtemp(), "kindle.json")   # never the user's own
real_keyring = kindle_send._keyring
kindle_send._keyring = lambda: None
sent_mail = []


class FakeSMTP:
    def __init__(self, host, port, timeout=None):
        self.host = host

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        pass

    def login(self, user, password):
        self.user = user

    def send_message(self, msg):
        sent_mail.append(msg)


save_session(ConversionSession(
    session_id="test-kindle", book_title="Kitap", author="Yazar", css="", language="tr",
    chapters=[ChapterOut(id="ch_0001", index=0, title="Giriş", html="<p>Kent hakkı üzerine.</p>")],
))
real_smtp = kindle_send.smtplib.SMTP
kindle_send.smtplib.SMTP = FakeSMTP
try:
    r = client.post("/api/session/test-kindle/kindle/send", json={"confirm": True})
    check("nothing is sent before it is set up", r.status_code == 409 and not sent_mail)
    st = client.post("/api/kindle/settings", json={
        "kindle_email": "okur@kindle.com", "smtp_host": "smtp.example.com", "smtp_port": 587,
        "smtp_user": "okur@example.com", "smtp_password": "uygulama-sifresi"}).json()
    check("settings are stored, the password never echoed", st["configured"] and "uygulama" not in json.dumps(st))
    r = client.post("/api/session/test-kindle/kindle/send", json={})
    check("nothing is sent without confirmation", r.status_code == 400 and not sent_mail)
    preview = client.get("/api/session/test-kindle/kindle/preview").json()
    check("the confirmation shows file, size and validity", preview["valid"] and preview["filename"] == "Kitap.epub")
    r = client.post("/api/session/test-kindle/kindle/send", json={"confirm": True})
    att = next(sent_mail[0].iter_attachments()) if sent_mail else None
    check("confirmed, the EPUB goes to the Kindle address as an attachment",
          r.status_code == 200 and sent_mail and sent_mail[0]["To"] == "okur@kindle.com"
          and att.get_content_type() == "application/epub+zip")
finally:
    kindle_send.smtplib.SMTP = real_smtp
    kindle_send._keyring = real_keyring

print("\nKindle mail settings: a password left in the file moves to the credential store")


class FakeKeyring:
    store = {}

    @classmethod
    def set_password(cls, service, user, password):
        cls.store[(service, user)] = password

    @classmethod
    def get_password(cls, service, user):
        return cls.store.get((service, user))


with open(kindle_send.SETTINGS_FILE, "w", encoding="utf-8") as fh:
    json.dump({"kindle_email": "okur@kindle.com", "from_email": "okur@hotmail.com", "smtp_host": "smtp.gmail.com",
               "smtp_port": 587, "smtp_user": "Vona", "smtp_password": "eski-sifre", "password_in": "file"}, fh)
kindle_send._keyring = lambda: FakeKeyring
try:
    st = kindle_send.status()
    on_disk = json.load(open(kindle_send.SETTINGS_FILE, encoding="utf-8"))
    check("the password leaves the file for the credential store",
          "smtp_password" not in on_disk and on_disk["password_in"] == "keyring"
          and FakeKeyring.store.get((kindle_send.KEYRING_SERVICE, "Vona")) == "eski-sifre")
    check("a hotmail sender with a Gmail server is pointed out",
          st["warning"] and "hotmail.com" in st["warning"] and "kullanıcı adı" in st["warning"])
finally:
    kindle_send._keyring = real_keyring

print("\nOkuma Defteri: Kindle highlights into a (scratch) Obsidian vault")
from app import obsidian  # noqa: E402

os.environ["MATBAA_NOTEBOOK"] = tempfile.mkdtemp()
obsidian.SETTINGS_FILE = os.path.join(tempfile.mkdtemp(), "obsidian.json")     # never the user's own
scratch_vault = tempfile.mkdtemp(prefix="vault-")
os.makedirs(os.path.join(scratch_vault, "2 - Kaynak", "Kitap"))
os.makedirs(os.path.join(scratch_vault, "6 - Tags"))
r = client.post("/api/obsidian/settings", json={"vault": scratch_vault})
check("the vault is set", r.status_code == 200 and r.json()["vault_ok"])
save_session(ConversionSession(
    session_id="test-notebook", book_title="Kent Hakkı Defteri", css="", language="tr",
    chapters=[ChapterOut(id="ch_0001", index=0, title="Giriş",
                         html="<p>Kent hakkı üzerine bir tartışma burada başlar.</p>")],
))
clips = ("Kent Hakkı Defteri (Yazar)\n- Your Highlight on page 3 | Location 30-31 | Added on Sunday, 18 October 2026 10:00:00\n\n"
         "Kent hakkı üzerine bir tartışma burada başlar.\n==========\n"
         "Kent Hakkı Defteri (Yazar)\n- Your Note on page 3 | Location 31 | Added on Sunday, 18 October 2026 10:01:00\n\n"
         "Bu ne demek?\n==========\n")
r = client.post("/api/notebook/import", files={"file": ("My Clippings.txt", clips.encode("utf-8"), "text/plain")})
listed = r.json()
book_row = next((b for b in listed["books"] if b["kindle_title"] == "Kent Hakkı Defteri"), None)
check("an imported My Clippings lists its book, matched to the saved Matbaa book",
      r.status_code == 200 and listed["imported"] == 2 and book_row and book_row["project"] is not None)
r = client.post("/api/notebook/import", files={"file": ("My Clippings.txt", clips.encode("utf-8"), "text/plain")})
check("importing the same file again adds nothing", r.json()["imported"] == 0)
detail = client.get(f"/api/notebook/book/{book_row['key']}").json()
h0 = detail["highlights"][0]
check("each highlight comes placed in the book, its note a question",
      h0["placement"] and h0["placement"]["chapter_title"] == "Giriş" and h0["question"])
plan = client.post(f"/api/notebook/book/{book_row['key']}/plan", json={}).json()
check("the plan shows the note it would write",
      plan["note"]["exists"] is False and "Kent hakkı üzerine bir tartışma burada başlar." in plan["note"]["text"])
r = client.post(f"/api/notebook/book/{book_row['key']}/write", json={"token": "eski"})
check("a write with a stale preview is refused", r.status_code == 409)
r = client.post(f"/api/notebook/book/{book_row['key']}/write", json={"token": plan["token"]})
written = r.json().get("written", [])
check("the previewed note is written into the vault",
      r.status_code == 200 and os.path.exists(written[0])
      and written[0].startswith(os.path.join(scratch_vault, "2 - Kaynak", "Kitap"))
      and any(p.endswith("Açık Sorular.md") for p in written))

print("\nThe reader's own correction of a note (Turkish letters restored on their click)")
detail = client.get(f"/api/notebook/book/{book_row['key']}").json()
note_h = next(h for h in detail["highlights"] if h["note"])
r = client.post("/api/notebook/edits", json={"changes": {note_h["id"]: "Bu ne demek? Çok önemli"}})
check("a correction is kept", r.status_code == 200 and r.json()["saved"] == 1)
detail = client.get(f"/api/notebook/book/{book_row['key']}").json()
check("and the book now shows the corrected note",
      next(h for h in detail["highlights"] if h["id"] == note_h["id"])["note"] == "Bu ne demek? Çok önemli")
client.post("/api/notebook/edits", json={"changes": {note_h["id"]: None}})
detail = client.get(f"/api/notebook/book/{book_row['key']}").json()
check("undoing it brings the Kindle's note back",
      next(h for h in detail["highlights"] if h["id"] == note_h["id"])["note"] == "Bu ne demek?")

print("\nA Kindle that is plugged in but locked is told apart from no Kindle")
from app import kindle_usb  # noqa: E402

real_state = kindle_usb.state
try:
    kindle_usb.state = lambda: "LOCKED"
    st = client.get("/api/notebook/kindle/status").json()
    check("locked: connected, not ready, with the remedy", st["connected"] and not st["ready"]
          and "kilidini açın" in (st["message"] or ""))
    kindle_usb.state = lambda: "NO_KINDLE"
    st = client.get("/api/notebook/kindle/status").json()
    check("none: no message to act on", not st["connected"] and st["message"] is None)
finally:
    kindle_usb.state = real_state

print("\nAn idea of the reader's, grown into a note of its own")
idea_clip = ("Kent Hakkı Defteri (Yazar)\n- Your Highlight on page 4 | Location 40-41 | Added on Sunday, 18 October 2026 11:00:00\n\n"
             "Kent hakkı üzerine bir tartışma burada başlar.\n==========\n"
             "Kent Hakkı Defteri (Yazar)\n- Your Note on page 4 | Location 41 | Added on Sunday, 18 October 2026 11:00:10\n\n"
             "!Mahalle meclisleri tam olarak bunu yapıyor\n==========\n")
client.post("/api/notebook/import", files={"file": ("My Clippings.txt", idea_clip.encode("utf-8"), "text/plain")})
detail = client.get(f"/api/notebook/book/{book_row['key']}").json()
idea_view = next((h for h in detail["highlights"] if h.get("note_kind") == "idea"), None)
pre = client.post(f"/api/notebook/book/{book_row['key']}/develop/{idea_view['id']}").json() if idea_view else {}
check("the idea's note is previewed in 3 - Gelişen Notlar",
      bool(idea_view) and pre.get("name", "").startswith("Mahalle meclisleri") and "Gelişen" in pre.get("path", ""))
edited = pre["text"] + "\nBen: kendi deneyimimden bir ekleme.\n"
r = client.post(f"/api/notebook/book/{book_row['key']}/develop/{idea_view['id']}/write", json={"text": edited})
check("and written as the reader edited it, never over an existing file",
      r.status_code == 200 and open(r.json()["written"], encoding="utf-8").read().strip() == edited.strip())

print("\nAn answer to a question: pasted from ChatGPT, or proposed by a configured model")
qid = h0["id"]
r = client.post("/api/notebook/answer", json={"id": qid, "text": "Kent hakkı, Lefebvre'nin kavramıdır."})
check("a pasted answer is kept", r.status_code == 200 and r.json()["answer"].startswith("Kent hakkı"))
plan2 = client.post(f"/api/notebook/book/{book_row['key']}/plan", json={}).json()
check("and goes into the note's AI box on the next write",
      "*Kent hakkı, Lefebvre'nin kavramıdır.*" in plan2["note"]["text"] and plan2["answers"] == 1)
real_status, real_complete = llm.status, llm.complete
llm.status = lambda: {"available": True, "provider": "test", "model": "test"}
try:
    llm.complete = lambda system, prompt, max_tokens=1200: 'Yazar şöyle der: "kent hakkı herkesin doğuştan sahip olduğu bir ayrıcalıktır".'
    r = client.post(f"/api/notebook/book/{book_row['key']}/ask/{qid}")
    check("a model answer quoting words the passage does not have is refused", r.status_code == 422)
    llm.complete = lambda system, prompt, max_tokens=1200: 'Pasaj, "Kent hakkı üzerine bir tartışma burada başlar" diyerek açılıyor.'
    r = client.post(f"/api/notebook/book/{book_row['key']}/ask/{qid}")
    check("one quoting the passage itself is offered", r.status_code == 200 and "Pasaj" in r.json()["answer"])
finally:
    llm.status, llm.complete = real_status, real_complete

print("\nOnly this computer, and only Matbaa's own page, can change anything")
pdf = {"file": ("kitap.pdf", b"%PDF-1.4\n%%EOF\n", "application/pdf")}
r = client.post("/api/upload", files=pdf, headers={"origin": "https://evil.example"})
check("an upload posted from another site is refused", r.status_code == 403)
r = client.post("/api/notebook/import", files={"file": ("My Clippings.txt", b"x", "text/plain")},
                headers={"sec-fetch-site": "cross-site"})
check("a cross-site import without an Origin header is refused", r.status_code == 403)
r = client.get("/api/projects", headers={"host": "evil.example"})
check("a request for another host name (DNS rebinding) is refused, even a read", r.status_code == 403)
r = client.get("/api/projects", headers={"host": "127.0.0.1:8765"})
check("the computer's own address is served", r.status_code == 200)
r = client.post("/api/upload", files=pdf, headers={"host": "127.0.0.1:8765", "origin": "http://127.0.0.1:8765"})
check("an upload from Matbaa's own page passes the guard", r.status_code != 403)
r = client.post("/api/upload", files=pdf, headers={"origin": "http://localhost:5173"})
check("an upload from the dev server passes the guard", r.status_code != 403)

if failures:
    print(f"\n{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("\nALL CHECKS PASSED")
