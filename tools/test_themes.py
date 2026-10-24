"""How the book looks: themes over the Matbaa stylesheet (backend/app/builders/themes.py).

    python tools/test_themes.py

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

from app.builders.css_template import book_css  # noqa: E402
from app.builders.epub_builder import build_epub  # noqa: E402
from app.builders.themes import DEFAULT_THEME, THEMES, apply_theme, theme_list, theme_of  # noqa: E402
from app.models import ChapterOut  # noqa: E402
from app.validate import check_epub  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        failures.append(name)


base = book_css("indented")
mine = base + "\n.my-rule { color: #123456; }"

print("\nChoosing a theme")
check("a book starts as Klasik", theme_of(base) == DEFAULT_THEME == "klasik")
modern = apply_theme(mine, "modern")
check("a theme is laid over the stylesheet", theme_of(modern) == "modern" and modern.startswith(mine.rstrip()))
switched = apply_theme(modern, "akademik")
check("choosing another replaces it, never stacks", theme_of(switched) == "akademik"
      and switched.count("matbaa-theme:") == 1 and "Amazon Ember" not in switched)
check("back to Klasik is the stylesheet as it was", apply_theme(switched, "klasik").rstrip() == mine.rstrip())
check("the book's own rules are kept through every change", all(
    ".my-rule { color: #123456; }" in apply_theme(mine, t) for t in THEMES))
try:
    apply_theme(base, "neon")
    check("an unknown theme is refused", False)
except ValueError:
    check("an unknown theme is refused", True)
check("the list the app shows names each with a sentence",
      [t["id"] for t in theme_list()] == list(THEMES) and all(t["about"] for t in theme_list()))

print("\nModern: Klasik's opening, a large plain title")
modern_css = THEMES["modern"]["css"]
check("no heavy rule over the title (it stood alone over an Önsöz)", "border-top" not in modern_css)
check("the label keeps Klasik's faint short rule (Modern leaves it alone)", "border-bottom" not in modern_css)
check("the title large and as written", "font-size: 1.7em !important" in modern_css
      and "text-transform: none !important" in modern_css)

print("\nA book saved with an older theme block gets the theme as it is now")
import tempfile as _tempfile  # noqa: E402

os.environ["MATBAA_PROJECTS"] = _tempfile.mkdtemp()
from app import session_store  # noqa: E402
from app.models import ConversionSession  # noqa: E402

old_block = "\n\n/* matbaa-theme:modern */\n.opener h1 { border-top: 2px solid #000000; }\n/* matbaa-theme-end */\n"
session_store.save_session(ConversionSession(session_id="test-theme", book_title="T", css=base + old_block,
                                             chapters=[ChapterOut(id="ch_0001", index=0, title="Giriş", html="<p>x</p>")]))
session_store._SESSIONS.clear()
reread = session_store.get_session("test-theme").css
check("its block is replaced, the theme kept", theme_of(reread) == "modern" and "border-top: 2px" not in reread
      and "font-size: 1.7em" in reread)

print("\nEvery theme makes a valid book a Kindle can show")
chapter = ChapterOut(id="ch_0001", index=0, title="Giriş", eyebrow="BİRİNCİ BÖLÜM",
                     html="<p>Kent hakkı üzerine bir tartışma burada başlar.</p>"
                          '<p class="symbol-line ornamental-divider">*</p><p>Ve sürer.</p>')
work = tempfile.mkdtemp()
for theme in THEMES:
    out = os.path.join(work, f"{theme}.epub")
    build_epub(book_title="Tema", author="Yazar", chapters=[chapter], css=apply_theme(base, theme),
               output_path=out, language="tr")
    findings = check_epub(out)
    check(f"{theme}: valid, and nothing in it a Kindle ignores",
          not [f for f in findings if f.severity == "error" or f.code == "kindle-css"])

if failures:
    print(f"\n{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("\nALL CHECKS PASSED")
