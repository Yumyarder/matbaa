"""Make the static faces Matbaa embeds from the variable fonts it ships with.

    python tools/make_fonts.py

A Kindle does not read a variable font's axes, so each face a book uses is
pinned once here: Literata (SIL Open Font License, Google Fonts) at its
text optical size, in regular and bold, upright and italic. The variable
sources and OFL.txt sit beside the results in backend/app/fonts/literata/;
the books get a subset of these faces at export (app/fonts.py), and the
Kindle gets them whole in its fonts/ folder.
"""
from __future__ import annotations

import os
import sys

from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FOLDER = os.path.join(REPO_ROOT, "backend", "app", "fonts", "literata")
TEXT_SIZE = 12          # the optical size of body text

FACES = {
    "Literata-Regular.ttf": ("Literata[opsz,wght].ttf", 400, "Regular"),
    "Literata-Bold.ttf": ("Literata[opsz,wght].ttf", 700, "Bold"),
    "Literata-Italic.ttf": ("Literata-Italic[opsz,wght].ttf", 400, "Italic"),
    "Literata-BoldItalic.ttf": ("Literata-Italic[opsz,wght].ttf", 700, "Bold Italic"),
}


def main() -> int:
    for out_name, (source, weight, style) in FACES.items():
        font = TTFont(os.path.join(FOLDER, source))
        static = instancer.instantiateVariableFont(font, {"wght": weight, "opsz": TEXT_SIZE},
                                                   updateFontNames=False)
        names = static["name"]
        for record in list(names.names):
            if record.nameID in (1, 16):
                record.string = "Literata"
            elif record.nameID in (2, 17):
                record.string = style
            elif record.nameID == 4:
                record.string = f"Literata {style}"
            elif record.nameID == 6:
                record.string = f"Literata-{style.replace(' ', '')}"
        static["OS/2"].usWeightClass = weight
        # the style bits, which a Kindle reading the font from its fonts/
        # folder groups the four faces by: the variable source marks every
        # instance "regular"
        bold, italic = weight >= 700, "Italic" in style
        selection = static["OS/2"].fsSelection & ~0b1100001     # italic, bold, regular
        static["OS/2"].fsSelection = selection | (1 if italic else 0) | (1 << 5 if bold else 0) | (
            1 << 6 if not (bold or italic) else 0)
        static["head"].macStyle = (1 if bold else 0) | (2 if italic else 0)
        static.save(os.path.join(FOLDER, out_name))
        print(out_name, os.path.getsize(os.path.join(FOLDER, out_name)) // 1024, "KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
