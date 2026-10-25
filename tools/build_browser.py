"""Build Matbaa for the browser into site/uygulama/ (matbaa.pages.dev/uygulama/).

The engine is Matbaa's own Python (backend/app) on Pyodide, run in a Web
Worker; see browser/ for the worker and the service worker, and
backend/app/browser.py for the bridge. This script puts together:

  site/uygulama/                 the frontend, `vite build --mode browser`
  site/uygulama/sw.js            browser/sw.js
  site/uygulama/engine.worker.js browser/engine.worker.js
  site/uygulama/engine.json      what the worker loads, in order
  site/uygulama/matbaa-<h>.zip   backend/app with EbookLib and python-multipart
  site/uygulama/pyodide-<v>/     Pyodide's core and the packages Matbaa uses,
                                 PyMuPDF as the project's own WebAssembly wheel

Pyodide's files come from its CDN and PyMuPDF's wheel from PyPI, once, into
.matbaa-work/browser-cache; every file is checked against a SHA-256 pinned
here (core files, PyMuPDF) or in the pinned pyodide-lock.json (packages).
A changed file stops the build.

Run: backend/.venv/Scripts/python tools/build_browser.py [--skip-frontend]
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "uygulama"
CACHE = ROOT / ".matbaa-work" / "browser-cache"

PYODIDE_VERSION = "0.29.4"
PYODIDE_CDN = f"https://cdn.jsdelivr.net/pyodide/v{PYODIDE_VERSION}/full/"
CORE = {
    "pyodide.js": "7be9e63eddf6bd8786a5ab71c8689c35731d187e3415fe58d7cb95423b50421a",
    "pyodide.asm.js": "fe75e97ef2c7a10c41f23b96344c553c7c1c62821bb206080dbb24941c06d5f3",
    "pyodide.asm.wasm": "10090fe41e019ae669d512e1f747021a8db2aaab0f6dd6f85fa9368c55d681e3",
    "python_stdlib.zip": "92cb24faa546818f3ef4050fd5bd2b6487bd2042efed2113af141d035f30efb4",
    "pyodide-lock.json": "14d2c2dba101277999e17135e653d8f15389ad1437f53eae213bf0c3cdff723d",
}
# The same PyMuPDF as the desktop app (backend/requirements.txt).
PYMUPDF_WHEEL = "pymupdf-1.28.2-cp313-abi3-pyemscripten_2025_0_wasm32.whl"
PYMUPDF_URL = ("https://files.pythonhosted.org/packages/58/8c/d897dcd32a25b58186c968b15ce4324ca029e9d96460de12325314e390be/"
               + PYMUPDF_WHEEL)
PYMUPDF_SHA256 = "2e1b574c0fd2cb238021033fd3c0f9c4388816638df064e4bfb56d9d81736dc8"
# What backend/app imports, as Pyodide names its builds; their own
# dependencies follow from the lock.
PACKAGES = ["lxml", "pillow", "fonttools", "pydantic", "fastapi", "six", "sqlite3", "pyodide-http"]
# Pure-Python packages Pyodide does not build, copied from the desktop venv
# into the app's archive (the same versions as backend/requirements.txt).
VENDORED = ["ebooklib", "python_multipart", "multipart"]
# backend/app parts the browser has no use for.
SKIP_DIRS = {"__pycache__", "frontend_dist"}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(url: str, dest: Path, expected: str) -> bytes:
    if dest.exists():
        data = dest.read_bytes()
        if sha256(data) == expected:
            return data
    print(f"  downloading {url.rsplit('/', 1)[-1]}")
    with urllib.request.urlopen(url, timeout=120) as resp:  # noqa: S310 — pinned hosts, checked below
        data = resp.read()
    if sha256(data) != expected:
        sys.exit(f"SHA-256 mismatch for {url}: refusing to build")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return data


def resolve(lock: dict, names: list) -> list:
    """Package names with everything they depend on, dependencies first."""
    order: list = []
    seen: set = set()

    def visit(name: str) -> None:
        key = re.sub(r"[-_.]+", "-", name).lower()  # the lock's keys are normalised names
        if key in seen:
            return
        seen.add(key)
        entry = lock["packages"][key]
        for dep in entry.get("depends", []):
            if dep.lower() != "pymupdf":
                visit(dep)
        order.append(key)

    for n in names:
        visit(n)
    return order


def app_archive(venv_site: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        app = ROOT / "backend" / "app"
        for path in sorted(app.rglob("*")):
            rel = path.relative_to(app.parent)
            if path.is_dir() or SKIP_DIRS & set(rel.parts) or path.suffix == ".pyc":
                continue
            z.write(path, rel.as_posix())
        for name in VENDORED:
            src = venv_site / name
            if not src.is_dir():
                sys.exit(f"{name} is not installed in the desktop venv")
            for path in sorted(src.rglob("*")):
                if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                    z.write(path, path.relative_to(venv_site).as_posix())
    return buf.getvalue()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-frontend", action="store_true", help="keep the last vite build")
    args = ap.parse_args()

    if not args.skip_frontend:
        print("frontend (vite build --mode browser)")
        npm = "npm.cmd" if os.name == "nt" else "npm"
        subprocess.run([npm, "run", "build", "--", "--mode", "browser"], cwd=ROOT / "frontend", check=True)
    if not (OUT / "index.html").exists():
        sys.exit("site/uygulama/index.html is missing: build the frontend first")

    print(f"Pyodide {PYODIDE_VERSION}")
    cache = CACHE / f"pyodide-{PYODIDE_VERSION}"
    pyodide_dir = OUT / f"pyodide-{PYODIDE_VERSION}"
    if pyodide_dir.exists():
        shutil.rmtree(pyodide_dir)
    pyodide_dir.mkdir(parents=True)
    for name, digest in CORE.items():
        (pyodide_dir / name).write_bytes(fetch(PYODIDE_CDN + name, cache / name, digest))
    lock = json.loads((pyodide_dir / "pyodide-lock.json").read_text(encoding="utf-8"))
    names = resolve(lock, PACKAGES)
    for key in names:
        entry = lock["packages"][key]
        data = fetch(PYODIDE_CDN + entry["file_name"], cache / entry["file_name"], entry["sha256"])
        (pyodide_dir / entry["file_name"]).write_bytes(data)
    (pyodide_dir / PYMUPDF_WHEEL).write_bytes(fetch(PYMUPDF_URL, CACHE / PYMUPDF_WHEEL, PYMUPDF_SHA256))

    print("Matbaa's Python")
    venv_site = ROOT / "backend" / ".venv" / "Lib" / "site-packages"
    archive = app_archive(venv_site)
    app_name = f"matbaa-{sha256(archive)[:12]}.zip"
    for old in OUT.glob("matbaa-*.zip"):
        old.unlink()
    (OUT / app_name).write_bytes(archive)

    for name in ("sw.js", "engine.worker.js"):
        shutil.copyfile(ROOT / "browser" / name, OUT / name)
    manifest = {
        "pyodide": f"./pyodide-{PYODIDE_VERSION}/",
        "packages": names + [PYMUPDF_WHEEL],
        "app": app_name,
    }
    (OUT / "engine.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    total = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file())
    biggest = max((p for p in OUT.rglob("*") if p.is_file()), key=lambda p: p.stat().st_size)
    print(f"site/uygulama: {total / 1048576:.1f} MB; largest {biggest.name} {biggest.stat().st_size / 1048576:.1f} MB")
    if biggest.stat().st_size > 25 * 1048576:
        sys.exit("a file is over Cloudflare Pages' 25 MiB limit")
    print("packages:", ", ".join(names))


if __name__ == "__main__":
    main()
