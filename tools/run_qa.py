"""Matbaa regression harness — run the real pipeline over the whole corpus
and compare the result against the accepted baselines.

    python tools/run_qa.py                  # run everything, compare, report
    python tools/run_qa.py --book tenin     # one book
    python tools/run_qa.py --accept         # adopt current results as baseline
    python tools/run_qa.py --detail         # also list missing-content examples

Exit code is 1 if any hard guard regressed, so this is usable as a
pre-commit gate.

Guard policy
------------
Hard guards are the ones where a worse number can only mean the book got
worse for a reader: text disappearing, XHTML that won't parse, footnote
links pointing at nothing, paragraphs left dangling mid-word. Those fail the
run.

Soft guards are structural counts — chapter count, footnote count, nav
entries. A change there can be an improvement (splitting a wrongly-merged
chapter) or a regression (losing a boundary), and nothing but reading the
output can tell which. Those are reported loudly and never fail the run.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# Turkish book titles and sample text go straight to the console; the default
# Windows code page mangles them into '?' and makes the report unreadable.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tools.qa import corpus, measure                          # noqa: E402
from tools.qa.reference import compare_against_reference      # noqa: E402
from tools.qa.run import convert_book                         # noqa: E402

BASELINE_DIR = os.path.join(os.path.dirname(__file__), "qa", "baselines")
OUT_DIR = os.path.join(corpus.REPO_ROOT, ".matbaa-work", "qa")

# metric -> (direction, severity). "lower"/"higher" = better.
GUARDS = {
    "probe_missing":              ("lower", "hard"),
    "epub_xhtml_parse_errors":    ("lower", "hard"),
    "epub_dangling_noterefs":     ("lower", "hard"),
    "epub_duplicate_ids":         ("lower", "hard"),
    "epub_validation_errors":     ("lower", "hard"),
    "paragraphs_dangling_hyphen": ("lower", "hard"),
    "epub_letters":               ("higher", "hard"),
    # Words is soft on purpose: rejoining a word split across a line break
    # is a fix that lowers the count. epub_letters is the hard content-loss
    # guard, because a join leaves it untouched.
    "epub_words":                 ("higher", "soft"),
    "paragraphs_lowercase_start": ("lower", "soft"),
    "chapters_under_200_chars":   ("lower", "soft"),
    "chapters_real":              ("higher", "soft"),
    "chapters_total":             ("higher", "soft"),
    "footnotes_total":            ("higher", "soft"),
    "paragraphs_total":           ("higher", "soft"),
    "epub_nav_toc_entries":       ("higher", "soft"),
    "epub_image_count":           ("higher", "soft"),
    # The document-level sanity gate must stay silent on a healthy book:
    # a gate that starts crying wolf on the corpus is a gate the person
    # will learn to scroll past, which is the same as not having one.
    "warnings_count":             ("lower", "soft"),
    # New (this severity taxonomy hasn't been battle-tested yet), so soft
    # rather than hard for now — but this is the one number that should
    # move only when content loss or a structural defect actually appears.
    "warnings_critical_count":    ("lower", "soft"),
}
BOOL_GUARDS = {"epub_ok": "hard", "epub_has_cover": "soft"}


def _baseline_path(key: str) -> str:
    return os.path.join(BASELINE_DIR, f"{key}.json")


def load_baseline(key: str):
    p = _baseline_path(key)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def save_baseline(key: str, sig: dict) -> None:
    os.makedirs(BASELINE_DIR, exist_ok=True)
    with open(_baseline_path(key), "w", encoding="utf-8") as fh:
        json.dump(sig, fh, ensure_ascii=False, indent=1, sort_keys=True)


def compare(base: dict, cur: dict):
    """Returns (regressions, improvements, changes) as lists of strings."""
    regressions, improvements, changes = [], [], []

    for metric, (direction, severity) in GUARDS.items():
        if metric not in base or metric not in cur:
            continue
        b, c = base[metric], cur[metric]
        if b == c:
            continue
        worse = (c > b) if direction == "lower" else (c < b)
        line = f"{metric}: {b} -> {c}"
        if worse:
            (regressions if severity == "hard" else changes).append(
                ("HARD " if severity == "hard" else "soft ") + line
            )
        else:
            improvements.append(line)

    for metric, severity in BOOL_GUARDS.items():
        if metric not in base or metric not in cur:
            continue
        b, c = base[metric], cur[metric]
        if b == c:
            continue
        line = f"{metric}: {b} -> {c}"
        if b and not c:
            (regressions if severity == "hard" else changes).append(
                ("HARD " if severity == "hard" else "soft ") + line
            )
        else:
            improvements.append(line)

    if base.get("epub_language") != cur.get("epub_language"):
        changes.append(f"soft epub_language: {base.get('epub_language')} -> {cur.get('epub_language')}")

    bt, ct = base.get("chapter_titles") or [], cur.get("chapter_titles") or []
    if bt != ct:
        changes.append(f"soft chapter_titles differ ({len(bt)} -> {len(ct)} entries)")

    return regressions, improvements, changes


def run_one(book, detail: bool):
    if not book.pdf_path:
        print(f"  UNAVAILABLE — {book.pdf_name} not found in {corpus.CORPUS_DIR}")
        return None

    run = convert_book(book.pdf_path, OUT_DIR, book.key)
    probes = measure.collect_probes(book.pdf_path, run.modes.skipped_pages())
    sig = measure.measure(book.key, run, probes).to_json()

    with open(os.path.join(OUT_DIR, f"{book.key}.signature.json"), "w", encoding="utf-8") as fh:
        json.dump(sig, fh, ensure_ascii=False, indent=1, sort_keys=True)

    print(f"  pages {sig['page_count']}  chapters {sig['chapters_total']} "
          f"(real {sig['chapters_real']}, image {sig['chapters_image']})  "
          f"footnotes {sig['footnotes_total']}")
    print(f"  warnings {sig['warnings_count']} ({sig['warnings_critical_count']} critical)")
    print(f"  content: probes {sig['probe_total'] - sig['probe_missing']}/{sig['probe_total']} present"
          f"   word recovery {sig['word_recovery']:.3f}"
          f"   ({sig['epub_words']} of {sig['pdf_words']} words)")
    print(f"  paragraphs {sig['paragraphs_total']} (median {sig['paragraph_median_chars']} chars, "
          f"{sig['paragraphs_lowercase_start']} lowercase-start, "
          f"{sig['paragraphs_dangling_hyphen']} dangling hyphen)")
    print(f"  epub: {sig['epub_bytes']:,}B  lang={sig['epub_language']}  spine={sig['epub_spine_count']}"
          f"  nav_toc={sig['epub_nav_toc_entries']}  page_list={sig['epub_nav_pagelist_entries']}"
          f"  notes={sig['epub_footnote_asides']}/{sig['epub_noteref_links']} refs"
          f"  parse_errors={sig['epub_xhtml_parse_errors']}")
    if sig["diagnostics"]:
        print(f"  diagnostics: {json.dumps(sig['diagnostics'], ensure_ascii=False)}")
    if detail and sig["probe_missing_examples"]:
        print("  missing content samples:")
        for ex in sig["probe_missing_examples"][:12]:
            print(f"    p{ex['page']:>3}  {ex['source']}")

    if book.reference_epub_path:
        cmp = compare_against_reference(book.reference_epub_path, run.epub_path)
        print(f"  vs historical EPUB: words {cmp.cur_words}/{cmp.ref_words} ({cmp.word_ratio:.1%}), "
              f"nav {sig['epub_nav_toc_entries']}/{cmp.ref_nav_entries}, "
              f"footnotes {sig['epub_footnote_asides']}/{cmp.ref_footnote_asides}, "
              f"reference passages absent now: {cmp.missing_from_current}")
        for note in cmp.notes:
            print(f"    note: {note}")
        if detail:
            for ex in cmp.missing_examples[:10]:
                print(f"    absent: {ex}")
        sig["reference"] = cmp.to_json()

    return sig


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", action="append", help="corpus key (tenin/hessen/dazai)")
    ap.add_argument("--accept", action="store_true", help="write current results as the new baseline")
    ap.add_argument("--detail", action="store_true")
    args = ap.parse_args()

    books = [corpus.BY_KEY[k] for k in args.book] if args.book else corpus.BOOKS
    os.makedirs(OUT_DIR, exist_ok=True)

    failed = False
    for book in books:
        print(f"\n=== {book.key}: {book.label}")
        print(f"    role: {book.role}")
        sig = run_one(book, args.detail)
        if sig is None:
            continue

        if args.accept:
            save_baseline(book.key, sig)
            print("  baseline updated.")
            continue

        base = load_baseline(book.key)
        if base is None:
            print("  no baseline yet — run with --accept to record one.")
            continue

        regressions, improvements, changes = compare(base, sig)
        for line in improvements:
            print(f"  IMPROVED  {line}")
        for line in changes:
            print(f"  CHANGED   {line}")
        for line in regressions:
            print(f"  REGRESSED {line}")
            failed = True
        if not (regressions or improvements or changes):
            print("  no change against baseline.")

    print("\n" + ("FAIL — hard guard regressed." if failed else "OK"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
