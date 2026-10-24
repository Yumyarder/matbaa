"""Convert a folder of PDFs to Kindle EPUBs with the app's defaults.

    python tools/batch_convert.py <folder> [--out <folder>] [--no-ocr] [--only <text>]

Every PDF under <folder> (sub-folders too) becomes an EPUB in --out
(default: <folder>/EPUB), mirroring the sub-folders. A report is written
next to them — rapor.html, one line per book with its readiness score,
what the engine did and what is left to look at, and whether the EPUB
passed its check — and rapor.json for tools. A book that fails does not
stop the rest.
"""
from __future__ import annotations

import argparse
import html
import io
import json
import os
import sys
import traceback

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "backend"))

from app.pipeline import convert_file  # noqa: E402


def find_pdfs(root: str, skip: str, only: str | None) -> list:
    found = []
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if os.path.abspath(os.path.join(folder, d)) != os.path.abspath(skip)]
        for name in sorted(files):
            if name.lower().endswith(".pdf") and (not only or only.lower() in name.lower()):
                found.append(os.path.join(folder, name))
    return found


def write_report(out_dir: str, rows: list) -> str:
    def cell(row):
        if row.get("error"):
            return f'<td colspan="4" class="bad">Dönüştürülemedi: {html.escape(row["error"])}</td>'
        rep, val = row["report"], row["validation"]
        issues = "".join(f"<li>{html.escape(i['message'])}</li>" for i in rep["issues"]) or "<li>sorun yok</li>"
        strategy = "".join(f"<li>{html.escape(s)}</li>" for s in rep["strategy"])
        ok = "geçerli" if val["valid"] else f'<span class="bad">{val["counts"]["error"]} hata</span>'
        return (f'<td>{rep["score"]}</td><td>{row["chapters"]}</td>'
                f'<td><ul>{strategy}</ul><ul class="issues">{issues}</ul></td><td>{ok}</td>')

    body = "".join(
        f'<tr><td><b>{html.escape(r.get("title") or os.path.basename(r["pdf"]))}</b><br>'
        f'<small>{html.escape(r.get("author") or "")} · {html.escape(os.path.basename(r["pdf"]))}</small></td>{cell(r)}</tr>'
        for r in rows
    )
    page = f"""<!doctype html><html lang="tr"><meta charset="utf-8"><title>Matbaa toplu dönüştürme</title>
<style>body{{font:14px system-ui;margin:24px;color:#201d18;background:#f4efe3}}table{{border-collapse:collapse;width:100%}}
td,th{{border-bottom:1px solid #d8cfbd;padding:8px;vertical-align:top;text-align:left}}ul{{margin:0;padding-left:16px}}
.issues{{color:#7a4a1c}}.bad{{color:#b03a2e}}</style>
<h1>Toplu dönüştürme · {len(rows)} kitap</h1>
<table><tr><th>Kitap</th><th>Puan</th><th>Bölüm</th><th>Strateji ve kalanlar</th><th>EPUB</th></tr>{body}</table></html>"""
    path = os.path.join(out_dir, "rapor.html")
    io.open(path, "w", encoding="utf-8").write(page)
    io.open(os.path.join(out_dir, "rapor.json"), "w", encoding="utf-8").write(
        json.dumps(rows, ensure_ascii=False, indent=1))
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description="Bir klasördeki PDF'leri Kindle EPUB'larına dönüştürür.")
    ap.add_argument("folder")
    ap.add_argument("--out")
    ap.add_argument("--no-ocr", action="store_true")
    ap.add_argument("--only")
    args = ap.parse_args()
    root = os.path.abspath(args.folder)
    out_dir = os.path.abspath(args.out or os.path.join(root, "EPUB"))
    work_dir = os.path.join(out_dir, ".ocr")
    pdfs = find_pdfs(root, out_dir, args.only)
    print(f"{len(pdfs)} PDF → {out_dir}")
    rows = []
    for n, pdf in enumerate(pdfs, 1):
        rel = os.path.relpath(pdf, root)
        target = os.path.join(out_dir, os.path.splitext(rel)[0] + ".epub")
        print(f"[{n}/{len(pdfs)}] {rel}")
        try:
            row = convert_file(pdf, target, work_dir, use_ocr=not args.no_ocr)
            print(f"  {row['title']} — {row['chapters']} bölüm, puan {row['report']['score']}, "
                  f"EPUB {'geçerli' if row['validation']['valid'] else 'HATALI'} ({row['seconds']} sn)")
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            row = {"pdf": pdf, "error": str(exc)[:300]}
        rows.append(row)
    print(f"\nRapor: {write_report(out_dir, rows)}")
    return 0 if all(not r.get("error") for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
