"""A zip of Matbaa to give to someone else, with nothing of yours in it.

    python tools/make_share_package.py [output.zip]

Only the committed source goes in (git archive): no books (test-corpus/ and
.matbaa-work/ are never committed), no OCR copies, no virtual environment,
and not the list of your library's books (tools/qa/baselines/library.json,
marked export-ignore in .gitattributes). Your notes were never in the
folder: the Okuma Defteri keeps the Kindle highlights in ~/Matbaa/notebook,
the vault and Kindle settings in ~/.matbaa, the books in ~/Matbaa/projects —
each person's own home folder. On another computer the app starts with an
empty notebook and asks for that person's Obsidian vault (it suggests the
one Obsidian last opened there).

The person needs Python 3.12 and Node.js, then runs Matbaa.bat once; it
installs what it needs. Uncommitted changes are not included.
"""
from __future__ import annotations

import os
import subprocess
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.expanduser("~"), "Desktop", "Matbaa-paylasim.zip")
    dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=REPO_ROOT,
                           capture_output=True, text=True).stdout.strip()
    subprocess.run(["git", "archive", "--format=zip", "--prefix=Matbaa/", "-o", out, "HEAD"], cwd=REPO_ROOT, check=True)
    print(f"{out}  ({os.path.getsize(out) // 1024} KB)")
    if dirty:
        print("Not: commit'lenmemiş değişiklikler pakete girmedi.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
