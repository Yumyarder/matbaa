"""Which class names the interface uses that a stylesheet never mentions.

Each look is a whole stylesheet (frontend/src/theme.js), so an element the
new one forgets is left in browser defaults. This lists, for each sheet,
the classes the JSX uses and the sheet has no rule for.

    backend/.venv/Scripts/python tools/design_coverage.py [sheet.css ...]
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "frontend", "src")
SHEETS = [os.path.join(SRC, "styles", name) for name in ("app.css", "hasiye.css")]

# className="a b", className={`a ${x ? "b" : ""}`}, and plain strings
# inside such expressions; a template part like `foo--${kind}` is a family.
_LITERAL = re.compile(r"""className=(?:"([^"]*)"|\{`([^`]*)`\}|\{([^}]*)\})""")
_WORD = re.compile(r"[a-z][a-z0-9_-]*(?:--|__)?[a-z0-9_-]*")


def used_classes():
    found = {}
    for folder, _, files in os.walk(SRC):
        for name in files:
            if not name.endswith(".jsx"):
                continue
            path = os.path.join(folder, name)
            text = open(path, encoding="utf-8").read()
            for m in _LITERAL.finditer(text):
                chunk = next(g for g in m.groups() if g is not None)
                chunk = re.sub(r"\$\{[^}]*\}", "*", chunk)
                for token in re.findall(r"[A-Za-z][\w-]*\*?|\*", chunk):
                    if "-" in token or "_" in token or token.islower() and len(token) > 2:
                        found.setdefault(token, os.path.relpath(path, SRC))
    # words that are JS, not classes
    for js in ("is", "active", "true", "false", "null", "join", "filter", "Boolean", "map"):
        found.pop(js, None)
    return found


def sheet_classes(path):
    text = open(path, encoding="utf-8").read()
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return set(re.findall(r"\.([A-Za-z][\w-]*)", text))


def main(argv):
    sheets = argv or SHEETS
    used = used_classes()
    for sheet in sheets:
        have = sheet_classes(sheet)
        missing = []
        for cls, where in sorted(used.items()):
            if cls.endswith("*"):
                stem = cls[:-1]
                if not any(h.startswith(stem) for h in have):
                    missing.append((cls, where))
            elif cls not in have:
                missing.append((cls, where))
        print(f"{os.path.relpath(sheet, ROOT)}: {len(missing)} of {len(used)} classes without a rule")
        for cls, where in missing:
            print(f"  {cls:42} {where}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
