"""Answer the one question a changed content metric always raises: *which
words* did this change add to the book, and which did it take away?

    python tools/difftext.py old.epub new.epub
    python tools/difftext.py old.epub new.epub --context   # show whole paragraphs

`run_qa.py` reports that `epub_letters` fell by 49. That number alone cannot
distinguish a paragraph that vanished from a column of print page numbers
that was correctly dropped, and those two demand opposite responses — one is
a regression to revert, the other a baseline to accept. Reading the two books
side by side does not scale, and an ordinary line diff is worse than useless
here: moving a chapter boundary re-aligns every following paragraph, so a
purely structural change prints as hundreds of lines added and removed.

So the comparison is a *multiset of tokens*, which is invariant under
everything structural — reordering, re-chaptering, re-paragraphing — and
sensitive to exactly the thing being asked about: a word that is in one book
and not the other. Both sides run through the harness's own normalisation, so
quote style, ligatures and Turkish case folding cannot masquerade as content
change; and both sides exclude the navigation document, for the reason given
in `epubinspect.plain_text`.
"""

from __future__ import annotations

import argparse
import collections
import os
import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tools.qa.epubinspect import inspect_epub   # noqa: E402
from tools.qa import textnorm                   # noqa: E402


def token_bag(epub_path: str) -> collections.Counter:
    info = inspect_epub(epub_path)
    if not info.ok:
        raise SystemExit(f"{epub_path}: unreadable EPUB — {'; '.join(info.errors[:3])}")
    return collections.Counter(textnorm.words(info.plain_text))


def paragraphs(epub_path: str):
    """Reading-order paragraphs, kept in original spelling for display."""
    info = inspect_epub(epub_path)
    out = []
    for name in sorted(info.text_by_file):
        for line in info.text_by_file[name].split("\n"):
            line = " ".join(line.split())
            if line:
                out.append((name, line))
    return out


def _report(title: str, bag: collections.Counter, limit: int) -> None:
    total = sum(bag.values())
    print(f"{title}: {total} tokens, {len(bag)} distinct")
    for token, n in bag.most_common(limit):
        print(f"   {token!r} x{n}" if n > 1 else f"   {token!r}")
    if len(bag) > limit:
        print(f"   ... and {len(bag) - limit} more distinct tokens")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument("--limit", type=int, default=80, help="distinct tokens to list per side")
    ap.add_argument("--context", action="store_true",
                    help="also print the paragraphs those tokens came from")
    args = ap.parse_args()

    old, new = token_bag(args.old), token_bag(args.new)
    lost, gained = old - new, new - old

    print(f"old: {args.old}  ({sum(old.values())} tokens)")
    print(f"new: {args.new}  ({sum(new.values())} tokens)\n")
    _report("LOST  (in old, not in new)", lost, args.limit)
    print()
    _report("GAINED (in new, not in old)", gained, args.limit)

    if args.context:
        for label, path, bag in (("LOST", args.old, lost), ("GAINED", args.new, gained)):
            if not bag:
                continue
            print(f"\n--- paragraphs containing {label} tokens, in {os.path.basename(path)}")
            seen = 0
            for name, line in paragraphs(path):
                if seen >= 25:
                    print("    ... (truncated)")
                    break
                if bag & collections.Counter(textnorm.words(line)):
                    print(f"  {os.path.basename(name)}  {line[:300]}")
                    seen += 1

    if not lost and not gained:
        print("\nno text difference.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
