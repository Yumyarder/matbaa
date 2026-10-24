"""The Kindle on a cable (backend/app/kindle_usb.py), through a folder that
stands in for it (MATBAA_KINDLE_DIR), and the faces it is given (fonts.py).

    python tools/test_kindle_usb.py

Exit code is 1 if anything fails.
"""
from __future__ import annotations

import os
import sys
import tempfile

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "backend"))
os.environ["MATBAA_PROJECTS"] = tempfile.mkdtemp()
os.environ["MATBAA_NOTEBOOK"] = tempfile.mkdtemp()
os.environ["MATBAA_SOZLUK"] = tempfile.mkdtemp()

from fastapi.testclient import TestClient  # noqa: E402
from fontTools.ttLib import TTFont  # noqa: E402

from app import fonts, kindle_usb, main  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        failures.append(name)


kindle = tempfile.mkdtemp()
os.makedirs(os.path.join(kindle, "documents"))
os.makedirs(os.path.join(kindle, "system", "vocabulary"))
os.makedirs(os.path.join(kindle, "fonts"))
with open(os.path.join(kindle, "documents", "My Clippings.txt"), "w", encoding="utf-8") as f:
    f.write("Kitap (Yazar)\n- Your Highlight on page 1 | Location 1-2 | Added on Sunday, 18 October 2026 10:00:00\n\n"
            "Bir vurgu.\n==========\n")
with open(os.path.join(kindle, "system", "vocabulary", "vocab.db"), "wb") as f:
    f.write(b"SQLite format 3\x00" + b"\x00" * 100)
with open(os.path.join(kindle, "fonts", "Readme.txt"), "w", encoding="utf-8") as f:
    f.write("the Kindle's own note")
os.environ[kindle_usb.LOCAL_ENV] = kindle

print("\nReading")
check("a Kindle is there", kindle_usb.state() == "READY" and kindle_usb.connected())
check("My Clippings.txt is copied off it", b"Bir vurgu." in kindle_usb.fetch_clippings())
copy = kindle_usb.fetch_file("system/vocabulary/vocab.db")
check("so is any other file, into a scratch folder", os.path.getsize(copy) == 116
      and not copy.startswith(kindle))
listing = kindle_usb.list_folder("fonts")
check("a folder is listed with sizes", [(i.name, i.size, i.folder) for i in listing] == [("Readme.txt", 21, False)])
check("a folder that is not there is None", kindle_usb.list_folder("documents/dictionaries") is None)
try:
    kindle_usb.fetch_file("documents/nothing.txt")
    check("a missing file is said to be missing", False)
except FileNotFoundError:
    check("a missing file is said to be missing", True)

print("\nAdding")
src = tempfile.mkdtemp()
a, b = os.path.join(src, "Yeni.ttf"), os.path.join(src, "Readme.txt")
for path, text in ((a, "new face"), (b, "a different readme")):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
done = kindle_usb.put_files("fonts", [a, b])
check("a new file is copied", done.get("Yeni.ttf") == "OK"
      and open(os.path.join(kindle, "fonts", "Yeni.ttf"), encoding="utf-8").read() == "new face")
check("a file of the same name is left exactly as it was", done.get("Readme.txt") == "SKIP"
      and open(os.path.join(kindle, "fonts", "Readme.txt"), encoding="utf-8").read() == "the Kindle's own note")
done = kindle_usb.put_files("documents/dictionaries", [a])
check("a folder that is missing is made", done.get("Yeni.ttf") == "OK"
      and os.path.isfile(os.path.join(kindle, "documents", "dictionaries", "Yeni.ttf")))
remade = os.path.join(tempfile.mkdtemp(), "Yeni.ttf")
with open(remade, "w", encoding="utf-8") as f:
    f.write("new face, made again with more")
done = kindle_usb.put_files("documents/dictionaries", [remade, b], replace=("Yeni.ttf",))
check("a file Matbaa made, made again, takes the old one's place", done.get("Yeni.ttf") == "OK"
      and open(os.path.join(kindle, "documents", "dictionaries", "Yeni.ttf"), encoding="utf-8").read()
      == "new face, made again with more")
done = kindle_usb.put_files("fonts", [b], replace=("Yeni.ttf",))
check("and nothing else is replaced", done.get("Readme.txt") == "SKIP"
      and open(os.path.join(kindle, "fonts", "Readme.txt"), encoding="utf-8").read() == "the Kindle's own note")
done = kindle_usb.put_files("documents/dictionaries", [remade], replace=("Yeni.ttf",))
check("the same make again is not copied twice", done.get("Yeni.ttf") == "SAME")

print("\nNo Kindle, or one without its documents")
os.environ[kindle_usb.LOCAL_ENV] = os.path.join(kindle, "not-there")
check("nothing plugged in", kindle_usb.state() == "NO_KINDLE" and not kindle_usb.connected())
try:
    kindle_usb.put_files("fonts", [a])
    check("and nothing is written", False)
except kindle_usb.KindleNotFound:
    check("and nothing is written", True)
bare = tempfile.mkdtemp()
os.environ[kindle_usb.LOCAL_ENV] = bare
check("a Kindle without documents/", kindle_usb.state() == "NO_DOCS")
try:
    kindle_usb.fetch_clippings()
    check("is told so when the notes are asked for", False)
except kindle_usb.KindleNotFound as exc:
    check("is told so when the notes are asked for", "documents" in str(exc))

print("\nThe faces the Kindle gets")
files = fonts.kindle_files()
check("four faces of each family", len(files) == 8 and all(os.path.isfile(p) for _, p in files))
STYLES = {"Regular": (400, False, False), "Italic": (400, False, True),
          "Bold": (700, True, False), "BoldItalic": (700, True, True)}
for name, path in files:
    font = TTFont(path)
    family, style = name[:-4].split("-")
    weight, bold, italic = STYLES[style]
    sel, mac = font["OS/2"].fsSelection, font["head"].macStyle
    check(f"{name}: family and style marked so the Kindle groups it",
          font["name"].getDebugName(1) == family and font["OS/2"].usWeightClass == weight
          and bool(sel & 1) == italic and bool(sel & 32) == bold and bool(sel & 64) == (not bold and not italic)
          and bool(mac & 1) == bold and bool(mac & 2) == italic)
    cmap = font.getBestCmap()
    check(f"{name}: every Turkish letter", all(ord(c) in cmap for c in "çğıİöşüÇĞÖŞÜâîû“”’…–—"))
for folder in fonts.KINDLE_FAMILIES:
    check(f"{folder}: its licence travels with it", os.path.isfile(os.path.join(fonts.FONT_DIR, folder, "OFL.txt")))

print("\nReadying the Kindle (the API)")
client = TestClient(main.app)
fresh = tempfile.mkdtemp()
for folder in ("documents", "fonts"):
    os.makedirs(os.path.join(fresh, folder))
with open(os.path.join(fresh, "fonts", "Readme.txt"), "w", encoding="utf-8") as f:
    f.write("the Kindle's own note")
os.environ[kindle_usb.LOCAL_ENV] = fresh
dev = client.get("/api/kindle/device").json()
check("a fresh Kindle has none of Matbaa's faces", dev["ready"] and dev["fonts"]
      and not any(f["installed"] for f in dev["fonts"]))
r = client.post("/api/kindle/fonts")
check("one request puts them all there", r.status_code == 200
      and sorted(r.json()["files"].values()) == ["OK"] * 8 and all(f["installed"] for f in r.json()["fonts"]))
check("beside the Kindle's own file, untouched", "Readme.txt" in os.listdir(os.path.join(fresh, "fonts"))
      and open(os.path.join(fresh, "fonts", "Readme.txt"), encoding="utf-8").read() == "the Kindle's own note")
r = client.post("/api/kindle/fonts")
check("asked again, nothing is copied twice", sorted(r.json()["files"].values()) == ["SKIP"] * 8)
os.environ[kindle_usb.LOCAL_ENV] = os.path.join(fresh, "gone")
dev = client.get("/api/kindle/device").json()
check("no Kindle: said so, nothing listed", not dev["connected"] and dev["fonts"] == [])
check("and the request to install is refused", client.post("/api/kindle/fonts").status_code == 404)

print("\nThe dictionary made again with new books")
import time  # noqa: E402

from app import dictionary, dictionary_build  # noqa: E402

made = os.path.join(dictionary.DATA_DIR, dictionary.DEVICE_NAME)
with open(made, "w", encoding="utf-8") as f:
    f.write("dictionary, first make")
kin = tempfile.mkdtemp()
os.makedirs(os.path.join(kin, "documents", "dictionaries"))
with open(os.path.join(kin, "documents", "dictionaries", dictionary.DEVICE_NAME), "w", encoding="utf-8") as f:
    f.write("dictionary, first make")
os.environ[kindle_usb.LOCAL_ENV] = kin
time.sleep(1.1)
with open(os.path.join(os.environ["MATBAA_PROJECTS"], "new-book.json"), "w", encoding="utf-8") as f:
    f.write('{"chapters": []}')
dev = client.get("/api/kindle/device").json()["matbaa_dictionary"]
check("a book saved since the dictionary was made is counted", dev["on_kindle"] and not dev["outdated"]
      and dev["new_books"] == 1)
steps = []


def fake_rebuild(progress):
    for step in ("Vikisözlük okunuyor", "kindlegen derliyor"):
        progress(step)
        steps.append(step)
    with open(made, "w", encoding="utf-8") as fh:
        fh.write("dictionary, second make with the new book's words")
    return {"headwords": 3, "book_forms": 1, "size": os.path.getsize(made), "seconds": 0}


real_rebuild = dictionary_build.rebuild
dictionary_build.rebuild = fake_rebuild
try:
    r = client.post("/api/kindle/dictionary/refresh").json()
    check("the remake runs in the background", r["state"] in ("running", "done"))
    for _ in range(50):
        st = client.get("/api/kindle/dictionary/refresh").json()
        if st["state"] != "running":
            break
        time.sleep(0.1)
    check("made again and put in place of the Kindle's", st["state"] == "done" and steps
          and st["result"]["kindle"] == {dictionary.DEVICE_NAME: "OK"}
          and open(os.path.join(kin, "documents", "dictionaries", dictionary.DEVICE_NAME), encoding="utf-8").read()
          == "dictionary, second make with the new book's words")
    with open(made, "w", encoding="utf-8") as f:
        f.write("a third make, the Kindle not plugged in for it")
    dev = client.get("/api/kindle/device").json()["matbaa_dictionary"]
    check("an older make on the Kindle is seen", dev["outdated"])
    client.post("/api/kindle/dictionary")
    check("and replaced on request", open(os.path.join(kin, "documents", "dictionaries", dictionary.DEVICE_NAME),
                                          encoding="utf-8").read() == "a third make, the Kindle not plugged in for it")
finally:
    dictionary_build.rebuild = real_rebuild

if failures:
    print(f"\n{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("\nALL CHECKS PASSED")
