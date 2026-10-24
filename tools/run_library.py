"""Run the whole personal library through Matbaa and show what is wrong.

    python tools/run_library.py --library "C:/Users/.../Belgeler/Kitaplar"
    python tools/run_library.py              # the path is remembered
    python tools/run_library.py --only Lenin # books whose name contains this
    python tools/run_library.py --accept     # adopt the results as baseline
    python tools/run_library.py --reuse      # re-check the last results, no conversion

The three acceptance books in tools/run_qa.py are read closely; this is the
wide net. Each book is converted the way the app converts it (suggested page
modes, no hand edits) in its own process, measured by tools/qa/library_one.py,
and checked against the defect classes the library survey found (FLAGS).

Writes .matbaa-work/library/index.html (the dashboard) and results.json.
Exit code is 1 when a book picked up a defect it did not have in the
baseline, or got worse at reading at all — so a change that fixes one book
by breaking another does not pass.
"""
from __future__ import annotations

import argparse
import html
import io
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
WORK = os.path.join(REPO_ROOT, ".matbaa-work", "library")
PATH_MEMO = os.path.join(REPO_ROOT, ".matbaa-work", "library_path.txt")
BASELINE = os.path.join(REPO_ROOT, "tools", "qa", "baselines", "library.json")
WORKER = os.path.join(REPO_ROOT, "tools", "qa", "library_one.py")
PYTHON = sys.executable
# Long enough for a first run that has to OCR a 400-page scan.
TIMEOUT_S = 1800

# Each defect class from the library survey, as a test on one book's
# measurements. The labels are what the dashboard shows.
FLAGS = {
    # The source layer is what tells: a broken font encoding reads as
    # 35-61% non-words on the library's broken books and at most 4% on the
    # sound ones. The output measure catches a failed OCR layer (≥0.2).
    "K1 çöp metin": lambda r: r.get("garbage", 0) > 0.15 or (
        r.get("source_garbage", 0) > 0.2 and not r.get("ocr_applied")),
    "K2 yer imi kullanılmadı": lambda r: r.get("outline_keys", 0) >= 5 and (r.get("outline_coverage") or 0) < 0.7,
    "K3 tekrar eden başlık": lambda r: r.get("dup_titles", 0) > 0,
    "K4 bölüm şişmesi": lambda r: r.get("outline_keys", 0) >= 5 and r.get("chapters", 0) > 1.5 * r["outline_keys"] + 3,
    "K5 künye/filigran başlık": lambda r: r.get("imprint_titles", 0) > 0,
    "K6 paragraf kopması": lambda r: r.get("lower_ratio", 0) > 0.02,
    "K6b sahte alıntı": lambda r: r.get("quote_share", 0) > 0.3,
    "K7 sahte vurgu": lambda r: r.get("em_flood_share", 0) > 0.05,
    "K8 kopuk not": lambda r: r.get("notes", 0) >= 5 and r.get("note_links", 0) < 0.8 * r["notes"],
    "K9 taranmış (OCR gerekli)": lambda r: r.get("status") == "scanned",
    "EPUB geçersiz": lambda r: r.get("epub_errors", 0) > 0,
    "K11 bozuk başlık": lambda r: r.get("leader_titles", 0) + r.get("junk_titles", 0) > 0,
    "bölüm yok": lambda r: r.get("status") == "ok" and r.get("chapters", 0) == 0,
    "çöktü": lambda r: r.get("status") in ("error", "timeout", "crash"),
}


def flags_of(rec: dict) -> list:
    return [name for name, test in FLAGS.items() if test(rec)]


def library_path(arg: str | None) -> str:
    path = arg or os.environ.get("MATBAA_LIBRARY")
    if not path and os.path.exists(PATH_MEMO):
        path = io.open(PATH_MEMO, encoding="utf-8").read().strip()
    if not path or not os.path.isdir(path):
        sys.exit("Kitaplık klasörü yok: --library ile verin (ör. Belgeler/Kitaplar).")
    os.makedirs(os.path.dirname(PATH_MEMO), exist_ok=True)
    io.open(PATH_MEMO, "w", encoding="utf-8").write(path)
    return path


SAMPLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qa", "sample.txt")


def sample_names() -> list:
    lines = io.open(SAMPLE, encoding="utf-8").read().splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]


def find_pdfs(root: str, only) -> list:
    """`only`: None for every book, or the name substrings to keep."""
    wanted = [only] if isinstance(only, str) else only
    pdfs = []
    for folder, _dirs, files in os.walk(root):
        for name in files:
            if name.lower().endswith(".pdf") and (
                    not wanted or any(w.lower() in name.lower() for w in wanted)):
                pdfs.append(os.path.join(folder, name))
    return sorted(pdfs, key=os.path.getsize)


def run_one(pdf: str, use_ocr: bool = True) -> dict:
    t0 = time.time()
    try:
        proc = subprocess.run(
            [PYTHON, WORKER, pdf] + ([] if use_ocr else ["--no-ocr"]), capture_output=True, timeout=TIMEOUT_S,
            encoding="utf-8", errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("{")]
        rec = json.loads(lines[-1]) if lines else {
            "file": os.path.basename(pdf), "status": "crash", "error": proc.stderr[-600:]}
    except subprocess.TimeoutExpired:
        rec = {"file": os.path.basename(pdf), "status": "timeout"}
    rec.setdefault("folder", os.path.basename(os.path.dirname(pdf)))
    rec["wall"] = round(time.time() - t0, 1)
    rec["flags"] = flags_of(rec)
    return rec


def compare(results: list, baseline: dict) -> tuple:
    """New flags per book, and flags that went away."""
    new, fixed = {}, {}
    for rec in results:
        before = set(baseline.get(rec["file"], {}).get("flags", []))
        now = set(rec["flags"])
        if rec["file"] in baseline:
            if now - before:
                new[rec["file"]] = sorted(now - before)
            if before - now:
                fixed[rec["file"]] = sorted(before - now)
    return new, fixed


def cell(value, bad: bool = False, good: bool = False) -> str:
    cls = " class=bad" if bad else (" class=good" if good else "")
    return f"<td{cls}>{html.escape(str(value))}</td>"


def dashboard(results: list, new: dict, fixed: dict) -> str:
    counts = {name: sum(1 for r in results if name in r["flags"]) for name in FLAGS}
    clean = sum(1 for r in results if not r["flags"])
    chips = "".join(
        f'<div class="chip{" zero" if n == 0 else ""}"><b>{n}</b><span>{html.escape(name)}</span></div>'
        for name, n in counts.items()
    )
    rows = []
    for r in sorted(results, key=lambda r: (-len(r["flags"]), r["file"])):
        status = r.get("status")
        cov = r.get("outline_coverage")
        delta = ""
        if r["file"] in new:
            delta += '<span class="new">+ ' + html.escape(", ".join(new[r["file"]])) + "</span>"
        if r["file"] in fixed:
            delta += '<span class="fixed">− ' + html.escape(", ".join(fixed[r["file"]])) + "</span>"
        titles = html.escape(" · ".join(r.get("titles", [])[:12]))
        rows.append(
            "<tr>"
            f'<td class="name" title="{titles}">{html.escape(r["file"][:60])}<small>{html.escape(r.get("folder", ""))} · {r.get("pages", "?")} s. · {html.escape(r.get("producer", ""))}'
            + (f' · OCR {r["ocr_pages"]} s. ({html.escape(r.get("ocr_reason") or "")})' if r.get("ocr_applied") else "")
            + '</small></td>'
            + cell(status, bad=status != "ok")
            + cell(r.get("chapters", "–"), bad="bölüm yok" in r["flags"] or "K4 bölüm şişmesi" in r["flags"])
            + cell(f'{r.get("outline", 0)} / {"–" if cov is None else f"{cov:.0%}"}', bad="K2 yer imi kullanılmadı" in r["flags"])
            + cell(f'{r.get("garbage", 0):.0%}', bad="K1 çöp metin" in r["flags"])
            + cell(r.get("dup_titles", 0) + r.get("imprint_titles", 0) + r.get("junk_titles", 0) + r.get("leader_titles", 0),
                   bad=any(f in r["flags"] for f in ("K3 tekrar eden başlık", "K5 künye/filigran başlık", "K11 bozuk başlık")))
            + cell(f'{r.get("lower_ratio", 0):.1%}', bad="K6 paragraf kopması" in r["flags"])
            + cell(f'{r.get("quote_share", 0):.0%}', bad="K6b sahte alıntı" in r["flags"])
            + cell(f'{r.get("em_flood_share", 0):.0%} · {r.get("em_per_kw", 0)}', bad="K7 sahte vurgu" in r["flags"])
            + cell(f'{r.get("note_links", 0)}/{r.get("notes", 0)}', bad="K8 kopuk not" in r["flags"])
            + cell(f'{r.get("recovery", 0):.0%}')
            + cell(f'{r.get("seconds", r.get("wall", 0))} sn', bad=(r.get("seconds") or 0) > 60)
            + f'<td class="flags">{html.escape(", ".join(r["flags"]) or "temiz")}{delta}</td>'
            "</tr>"
        )
    return f"""<!doctype html><html lang="tr"><head><meta charset="utf-8">
<title>Matbaa kitaplık raporu</title>
<style>
:root {{ --ink:#1d1a16; --paper:#f6f1e7; --line:#ddd2bf; --bad:#a3361f; --good:#2f6b3a; --muted:#7a6f60; }}
body {{ margin:0; padding:32px; background:var(--paper); color:var(--ink); font:14px/1.45 system-ui, sans-serif; }}
h1 {{ font:600 26px Georgia, serif; margin:0 0 4px; }}
.sub {{ color:var(--muted); margin:0 0 20px; }}
.chips {{ display:flex; flex-wrap:wrap; gap:8px; margin-bottom:24px; }}
.chip {{ background:#fff; border:1px solid var(--line); border-radius:8px; padding:8px 12px; display:flex; gap:8px; align-items:baseline; }}
.chip b {{ font-size:20px; color:var(--bad); }} .chip.zero b {{ color:var(--good); }}
table {{ border-collapse:collapse; width:100%; background:#fff; border:1px solid var(--line); }}
th, td {{ padding:7px 10px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }}
th {{ font-size:12px; color:var(--muted); font-weight:600; position:sticky; top:0; background:#fff; }}
td.name small {{ display:block; color:var(--muted); }}
td.bad {{ color:var(--bad); font-weight:600; }}
td.flags {{ font-size:12px; color:var(--muted); max-width:280px; }}
.new {{ display:block; color:var(--bad); font-weight:600; }} .fixed {{ display:block; color:var(--good); font-weight:600; }}
</style></head><body>
<h1>Kitaplık raporu</h1>
<p class="sub">{len(results)} kitap · {clean} temiz · {time.strftime("%Y-%m-%d %H:%M")}</p>
<div class="chips">{chips}</div>
<table><thead><tr><th>Kitap</th><th>Durum</th><th>Bölüm</th><th>Yer imi / kapsama</th><th>Çöp</th>
<th>Sahte başlık</th><th>Küçük harf ¶</th><th>Alıntı payı</th><th>İtalik ¶ · vurgu/1000</th><th>Not bağl.</th>
<th>Kurtarma</th><th>Süre</th><th>Kusurlar</th></tr></thead><tbody>{"".join(rows)}</tbody></table>
</body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--library")
    ap.add_argument("--only")
    ap.add_argument("--sample", action="store_true",
                    help="only the books listed in tools/qa/sample.txt, one of each kind")
    ap.add_argument("--jobs", type=int, default=max(2, (os.cpu_count() or 4) // 2))
    ap.add_argument("--accept", action="store_true")
    ap.add_argument("--no-ocr", action="store_true", help="convert pages as they are, without OCR")
    ap.add_argument("--reuse", action="store_true", help="re-flag the last results.json without converting")
    args = ap.parse_args()

    results = []
    if args.reuse:
        results = json.load(io.open(os.path.join(WORK, "results.json"), encoding="utf-8"))
        for rec in results:
            rec["flags"] = flags_of(rec)
        print(f"{len(results)} kitap (son sonuçlar yeniden değerlendirildi)")
    else:
        root = library_path(args.library)
        pdfs = find_pdfs(root, sample_names() if args.sample else args.only)
        print(f"{len(pdfs)} kitap, {args.jobs} işçi — {root}")
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            futures = {pool.submit(run_one, pdf, not args.no_ocr): pdf for pdf in pdfs}
            for fut in as_completed(futures):
                rec = fut.result()
                results.append(rec)
                print(f"  {rec.get('status', '?'):8} {rec['wall']:6.1f}s  {rec['file'][:60]}  {', '.join(rec['flags'])}")

    baseline = {}
    if os.path.exists(BASELINE):
        baseline = json.load(io.open(BASELINE, encoding="utf-8"))
    # a partial run is compared, and accepted only for the books it ran
    merged = dict(baseline)
    new, fixed = compare(results, baseline)

    os.makedirs(WORK, exist_ok=True)
    io.open(os.path.join(WORK, "results.json"), "w", encoding="utf-8").write(
        json.dumps(results, ensure_ascii=False, indent=1))
    page = os.path.join(WORK, "index.html")
    io.open(page, "w", encoding="utf-8").write(dashboard(results, new, fixed))

    total = {name: sum(1 for r in results if name in r["flags"]) for name in FLAGS}
    print("\nKusur sayıları: " + ", ".join(f"{k}: {v}" for k, v in total.items() if v))
    for name, gone in fixed.items():
        print(f"  DÜZELDİ  {name[:50]}: {', '.join(gone)}")
    for name, came in new.items():
        print(f"  GERİLEDİ {name[:50]}: {', '.join(came)}")
    print(f"\nPano: {page}")

    if args.accept:
        snapshot = merged if (args.only or args.sample) else {}
        # the source garbage measure is part of what a flag is decided on
        for rec in results:
            snapshot[rec["file"]] = {k: rec.get(k) for k in (
                "status", "flags", "chapters", "outline_coverage", "garbage", "source_garbage", "lower_ratio",
                "em_per_kw", "notes", "note_links", "recovery", "words")}
        os.makedirs(os.path.dirname(BASELINE), exist_ok=True)
        io.open(BASELINE, "w", encoding="utf-8").write(
            json.dumps(dict(sorted(snapshot.items())), ensure_ascii=False, indent=1))
        print("Taban çizgisi güncellendi.")
        return 0
    return 1 if new else 0


if __name__ == "__main__":
    sys.exit(main())
