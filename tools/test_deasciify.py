"""Turkish letters for a note typed without them (backend/app/deasciify.py).

    python tools/test_deasciify.py

Exit code is 1 if anything fails.
"""
from __future__ import annotations

import os
import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "backend"))

from app import deasciify  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        failures.append(name)


print("\nThe word list built from the library")
t = deasciify.table()
check("it is there and large", len(t) > 5000)
check("common words have their Turkish spelling", t.get("cok") == "çok" and t.get("degil") == "değil")

print("\nRestoring a Kindle-typed note")
new, changes = deasciify.restore("Cok hos otesi hos bir aciklama esasen")
check("letters come back where the books are sure", new == "Çok hoş ötesi hoş bir açıklama esasen")
check("and every change is reported", ("Cok", "Çok") in changes and ("hos", "hoş") in changes)
check("a capital stays a capital, all caps stay all caps",
      deasciify.restore("ISCI sinifi")[0].startswith("İŞÇİ"))
new, changes = deasciify.restore("Bu üç duzeyi unutmamak istiyorum")
check("a word the reader already spelled with Turkish letters is left alone",
      new.startswith("Bu üç düzeyi") and ("üç", "üç") not in changes)
check("a name or a word the books do not know is left alone",
      deasciify.restore("Krupskaya ve Sikmabas")[0] == "Krupskaya ve Sikmabas")
check("a word written as it is in the books is not changed", deasciify.restore("bir kitap")[0] == "bir kitap")
check("nothing to restore gives back the text and no changes", deasciify.restore("") == ("", []))

if failures:
    print(f"\n{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("\nALL CHECKS PASSED")
