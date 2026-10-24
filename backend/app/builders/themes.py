"""How the book looks: a theme laid over the Matbaa stylesheet.

The base stylesheet (css_template.MATBAA_CSS) is "Klasik": the chapter
opening reproduced from the printed page, titles in capitals, a rule and an
ornament. A theme is a short stylesheet appended after it, between two
marker comments, so that choosing another theme replaces only that part and
anything else in the book's stylesheet stays as it is. The simulator and the
exported book read the same stylesheet, so what the reader picks is what the
Kindle shows.

Kindle notes: only the reader's chosen font is used unless the book embeds
its own (or "Yayıncı yazı tipi" is on), so a theme speaks through size,
weight, case, alignment, spacing and rules more than through faces; the
font-family names below are the Kindle's own where it has them.
"""
from __future__ import annotations

import re
from typing import Dict

THEME_BEGIN = "/* matbaa-theme:"
THEME_END = "/* matbaa-theme-end */"
_THEME_BLOCK = re.compile(r"\n*/\* matbaa-theme:[a-z]+ \*/.*?/\* matbaa-theme-end \*/\n*", re.S)

# every arrangement the parser can give a chapter's label
_EYEBROWS = (".chapter-eyebrow, .opener .chapter-eyebrow.align-center, "
             ".opener .chapter-eyebrow.align-left, .opener .chapter-eyebrow.align-right")
_OPENERS = ".opener, .opener.drop-1, .opener.drop-2, .opener.drop-3, .opener.inline"

THEMES: Dict[str, Dict[str, str]] = {
    "klasik": {
        "label": "Klasik",
        "about": "Bölüm açılışı basılı sayfadaki gibi; büyük harfli başlık, ince çizgi ve süs.",
        "css": "",
    },
    "akademik": {
        "label": "Akademik",
        "about": "Üniversite yayınevi sayfası: başlıklar küçük ve sola yaslı, alıntılar düz, notlar okunaklı.",
        "css": f"""
body {{ line-height: 1.4; }}
h1, .opener h1, .opener h1.scale-large, .opener h1.scale-medium, .opener h1.scale-small {{
    text-align: left !important; text-transform: none !important; letter-spacing: 0 !important;
    font-size: 1.35em !important; font-weight: bold; }}
{_EYEBROWS} {{
    text-align: left !important; width: auto; border-bottom: none; padding-bottom: 0;
    margin: 1.4em 0 0.4em; font-variant: small-caps; text-transform: none; letter-spacing: 0.06em;
    font-size: 0.95em; color: #333333; }}
{_OPENERS} {{ margin-top: 1em; margin-bottom: 1.4em; }}
.opener .opener-byline, .chapter-byline {{ text-align: left !important; margin-top: 0; }}
.symbol-line, .ornamental-divider {{ border-top: none; width: auto; font-size: 1em; padding-top: 0; }}
h2.subheading {{ font-size: 1.05em; font-weight: bold; }}
.academic-blockquote {{ font-style: normal; border-left: none; margin: 0.9em 0 0.9em 1.6em; font-size: 0.92em; }}
p.quote-block {{ font-style: normal; font-size: 0.92em; margin-left: 1.6em; }}
.footnote-section {{ font-size: 0.85em; color: #333333; }}
""",
    },
    "modern": {
        "label": "Modern",
        "about": "Klasik'in düzeni, iri ve yalın başlıklarla: bölüm adı büyük ve kalın, yazıldığı gibi; "
                 "üstündeki etiketin altında ince, soluk bir çizgi.",
        # The opening is Klasik's, label, faint short rule and all, and only
        # the title is set large in a plain face, as written ("Teşekkür", not
        # "TEŞEKKÜR"). A heavy rule over the title was tried and read as a
        # stray bar over a chapter with no label above it (an "Önsöz").
        "css": f"""
h1, h2, h3, {_EYEBROWS}, .toc-section-label, .footnote-title, .index-letter {{
    font-family: "Amazon Ember", "Helvetica Neue", "Helvetica", "Arial", sans-serif; }}
h1, .opener h1, .opener h1.scale-large, .opener h1.scale-medium, .opener h1.scale-small {{
    text-transform: none !important; letter-spacing: -0.01em !important;
    font-size: 1.7em !important; font-weight: bold; line-height: 1.15; }}
h2.subheading {{ font-size: 1.1em; }}
""",
    },
    "sade": {
        "label": "Sade",
        "about": "Yalnız metin: başlıklar metnin yazı tipinde ve ölçülü, çizgi ve süs yok, yapıyı boşluk kurar.",
        "css": f"""
h1, .opener h1, .opener h1.scale-large, .opener h1.scale-medium, .opener h1.scale-small {{
    text-transform: none !important; letter-spacing: 0 !important; font-weight: normal;
    font-size: 1.4em !important; }}
{_EYEBROWS} {{ border-bottom: none; width: auto; padding-bottom: 0; color: #555555; }}
.symbol-line, .ornamental-divider {{ border-top: none; width: auto; color: #888888; padding-top: 0; }}
hr.thin-rule {{ border-top-color: #dddddd; }}
.academic-blockquote {{ border-left: none; font-style: normal; }}
.drop-cap::first-letter {{ float: none; font-size: 1em; font-weight: normal; padding: 0; }}
.footnote-section {{ border-top: none; }}
""",
    },
}
DEFAULT_THEME = "klasik"


def theme_of(css: str) -> str:
    """The theme a stylesheet carries."""
    m = re.search(r"/\* matbaa-theme:([a-z]+) \*/", css or "")
    return m.group(1) if m and m.group(1) in THEMES else DEFAULT_THEME


def apply_theme(css: str, theme: str) -> str:
    """`css` with its theme block replaced by `theme`'s (Klasik has none)."""
    if theme not in THEMES:
        raise ValueError(f"unknown theme: {theme}")
    base = _THEME_BLOCK.sub("\n", css or "").rstrip()
    body = THEMES[theme]["css"].strip()
    if not body:
        return base
    return f"{base}\n\n{THEME_BEGIN}{theme} */\n{body}\n{THEME_END}\n"


def theme_list() -> list:
    return [{"id": k, "label": v["label"], "about": v["about"]} for k, v in THEMES.items()]
