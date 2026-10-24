"""
The "Matbaa" (Print) CSS architecture.

This is the single source of truth for how the converted book looks on a
Kindle e-ink screen. It is injected into the EPUB as stylesheet.css AND
reused verbatim by the frontend Kindle Simulator so that what the user edits
is pixel-identical to what ships in the .epub.
"""

MATBAA_CSS = """
@namespace epub "http://www.idpf.org/2007/ops";

html, body {
    margin: 0;
    padding: 0;
    background: #ffffff;
    color: #000000;
}

body {
    margin-left: 6%;
    margin-right: 6%;
    text-align: justify !important;
    line-height: 1.45;
    font-family: "Bookerly", "Georgia", "Palatino Linotype", serif;
    font-size: 1em;
    -webkit-hyphens: auto;
    hyphens: auto;
    orphans: 2;
    widows: 2;
}

h1, h2, h3 {
    font-family: "Bookerly", "Georgia", serif;
    text-align: center;
    font-weight: bold;
    margin-top: 1.6em;
    margin-bottom: 1em;
    line-height: 1.2;
    page-break-before: always;
}

h1 { font-size: 1.6em; letter-spacing: 0.02em; text-transform: uppercase; }
h2 { font-size: 1.3em; }
h3 { font-size: 1.1em; font-style: italic; }

p {
    margin: 0;
    padding: 0;
    text-indent: 1.3em;
    text-align: justify !important;
    orphans: 2;
    widows: 2;
}

/* The "First Paragraph" Rule: no indent directly after a heading or a
   decorative symbol line. */
h2 + p,
h3 + p,
h1 + p,
.symbol-line + p,
.chapter-byline + p,
.chapter-eyebrow + h1 {
    text-indent: 0 !important;
}

/* Section-label eyebrow above a chapter title, e.g. "BİRİNCİ BÖLÜM" or
   "[SUNUŞ YERİNE]" — small caps, letter-spaced, muted, centered, with a
   thin rule underneath separating it from the title below. */
.chapter-eyebrow {
    text-align: center !important;
    text-indent: 0 !important;
    font-size: 0.78em;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: #55565a;
    margin: 2.4em auto 1em;
    padding-bottom: 0.7em;
    border-bottom: 0.75px solid #b7b3a6;
    width: 58%;
}

/* Author/byline directly under a chapter title + ornament, e.g. "Paul
   Blackledge" — small italic, centered. */
.chapter-byline {
    text-align: center !important;
    text-indent: 0 !important;
    font-style: italic;
    font-size: 0.92em;
    color: #3a3a3a;
    margin: 0 0 1.6em;
}

/* Decorative section-break glyphs (e.g. ❖ or ***), doubling as the
   ornamental rule directly under a chapter title — a thin rule above the
   glyph itself, matching the "rule / rule / ornament" print layout. */
.symbol-line,
.ornamental-divider {
    text-align: center !important;
    font-size: 1.3em;
    margin: 0.8em auto 1.2em;
    text-indent: 0 !important;
    letter-spacing: 0.3em;
    color: #6b6b6b;
    padding-top: 0.6em;
    border-top: 0.75px solid #b7b3a6;
    width: 42%;
}

/* Manually-insertable plain divider (Live Editor "İnce Çizgi Ekle" tool) —
   a quiet horizontal rule that can be dropped in anywhere in the text. */
hr.thin-rule {
    border: none;
    border-top: 0.75px solid #b7b3a6;
    width: 40%;
    margin: 1.6em auto;
}

/* Academic block quotations: short, centrally-positioned paragraphs in the
   source PDF are re-flowed here to mimic an indented printed quote block.
   Also manually applicable from the Live Editor toolbar ("Blok Alıntı"). */
.academic-blockquote {
    margin: 1em 8%;
    padding: 0.4em 0.6em;
    text-indent: 0 !important;
    font-size: 0.95em;
    font-style: italic;
    border-left: 2px solid #999999;
    text-align: justify;
}
.academic-blockquote p { text-indent: 0 !important; margin: 0.3em 0; text-align: justify !important; }
/* Fixes a real specificity bug: .academic-blockquote p (class+element,
   0,1,1) otherwise always beats .text-center alone (0,1,0) — meaning
   toggling "Ortala" on blockquote-nested content silently had no visual
   effect, even though the class was correctly applied in the DOM. This
   compound selector (0,2,1) wins over both. */
.academic-blockquote.text-center,
.academic-blockquote.text-center p { text-align: center !important; }

/* Poetry / verse / letter-style stanza — centered, no first-line indent,
   a little extra line-height so lines of a stanza breathe. Applied via
   the Live Editor toolbar ("Şiir / Mektup"). */
.verse-block {
    text-align: center !important;
    text-indent: 0 !important;
    font-style: italic;
    line-height: 1.7;
    margin: 1.4em 0;
}

/* Classic large drop-cap on a chapter's opening letter. Applied via the
   Live Editor toolbar ("Büyük Harf Başlangıcı") — toggles on the block
   directly following the title. */
.drop-cap::first-letter {
    float: left;
    font-family: "Bookerly", "Georgia", serif;
    font-weight: 700;
    font-size: 3.2em;
    line-height: 0.8;
    padding-right: 0.08em;
    padding-top: 0.05em;
}

/* Automatically-detected typographic variants ------------------------- */
.text-muted {
    color: #5c5c5c;
    opacity: 0.86;
}
.text-italic { font-style: italic; }
.text-bold { font-weight: 700 !important; }
.text-center {
    text-align: center !important;
    text-indent: 0 !important;
}
/* A line off a page that sets no prose of its own: a plate's caption, an
   index entry, an imprint line. It sits in the reading order where the
   book printed it, but it is not a paragraph of the text and should not
   open with a paragraph indent or claim body-text weight. */
.page-aside {
    font-size: 0.86em;
    text-indent: 0 !important;
    margin: 0.5em 0;
}

/* A printed index: one entry a line, a long entry's later lines hanging
   under its first, a sub-entry set in; the page numbers are links to the
   printed pages, so they read as numbers, not as underlined links. */
.index-entry {
    text-align: left !important;
    text-indent: -1.5em !important;
    margin: 0 0 0 1.5em;
    font-size: 0.92em;
}
.index-sub { margin-left: 3em; }
.index-letter {
    text-indent: 0 !important;
    font-weight: bold;
    margin: 0.9em 0 0.2em;
    page-break-after: avoid;
}
.index-entry a, .page-link { text-decoration: none; color: inherit; }

/* Figure + caption locked together so Kindle's paginator never splits
   them onto separate screens — ready for whenever inline images land. */
.figure-lock {
    page-break-inside: avoid;
    break-inside: avoid;
    text-align: center;
    margin: 1.4em 0;
}
.figure-lock figcaption {
    font-size: 0.82em;
    color: #55565a;
    text-indent: 0 !important;
    margin-top: 0.5em;
}

/* EPUB3 popup footnotes: readers that support epub:type asides show
   these as a tap-to-read popup instead of jumping away; everyone else
   still sees a normal endnote list at the end of the chapter. */
.footnote-section aside {
    display: block;
}

/* Footnote reference marker inside body text */
.footnote-ref a {
    text-decoration: none;
    color: inherit;
}
.footnote-ref {
    vertical-align: super;
    font-size: 0.7em;
    line-height: 0;
    margin-left: 0.05em;
}

/* Footnotes / endnotes, gathered at the end of the chapter rather than
   inline — thin rule, small, quietly faded, exactly like a printed page. */
.footnote-section {
    margin-top: 2.6em;
    padding-top: 0.7em;
    border-top: 0.5px solid #bbbbbb;
    font-size: 0.78em;
    line-height: 1.35;
    text-indent: 0;
    color: #55565a;
}
.footnote-section .footnote-title {
    font-weight: 600;
    text-transform: uppercase;
    font-size: 0.82em;
    letter-spacing: 0.1em;
    margin-bottom: 0.7em;
    text-align: left;
    color: #333333;
}
.footnote-section p {
    text-indent: 0;
    margin: 0 0 0.6em 0;
}
.footnote-marker {
    font-weight: 600;
    margin-right: 0.35em;
}
.footnote-back {
    text-decoration: none;
    color: #999999;
    margin-left: 0.3em;
    font-size: 0.85em;
}

/* Table of contents page --------------------------------------------- */
.toc-page h1 { margin-bottom: 1.4em; }
.toc-section-label {
    text-align: center !important;
    text-indent: 0 !important;
    font-size: 0.8em;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: #666666;
    margin: 1.4em 0 0.2em;
}
.toc-entry {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    text-indent: 0 !important;
    margin: 0 0 0.9em;
    font-size: 0.95em;
}
.toc-entry .toc-title { flex: 1; padding-right: 1em; }
.toc-entry .toc-page {
    color: #777777;
    font-size: 0.85em;
    flex-shrink: 0;
}

/* Front-matter pages (half-title, translator's note, colophon...) — more
   generous whitespace, no forced first-paragraph indent, quieter type. */
.frontmatter-page {
    padding-top: 8%;
}
.frontmatter-page h1 {
    text-transform: none;
    font-size: 1.35em;
}

/* Full-page image pages (covers, ornamental title pages, anything marked
   "görsel" in Page Review) — rendered pixel-for-pixel as a picture, not
   reflowed text. No body margins here so the image can go edge-to-edge. */
body.image-page {
    margin: 0;
    padding: 0;
}
.image-page-wrapper {
    text-align: center;
    margin: 0;
    padding: 0;
}
.image-page-wrapper img {
    width: 100%;
    height: auto;
    display: block;
    margin: 0 auto;
}

/* An in-page figure from the PDF Editor's "Görsel" region marker — sits
   inline with ordinary text, unlike the edge-to-edge full-page image
   above, so it keeps normal body margins and reads as part of the page. */
.region-figure {
    margin: 1.4em 0;
    text-align: center;
}
.region-figure img {
    max-width: 100%;
    height: auto;
    display: block;
    margin: 0 auto;
}
.region-figure figcaption {
    font-size: 0.85em;
    color: #555;
    margin-top: 0.5em;
    font-style: italic;
}

/* Chapter openings measured off the printed page --------------------- */
/* Each chapter is its own file, so it already starts on a fresh screen;
   what is reproduced is the page's arrangement: where the section label
   and title sit, how large they are, and how much white space comes
   before the text. */
.opener { margin: 0 0 1.2em; }
.opener h1 { page-break-before: auto; margin-top: 0.4em; text-transform: none; letter-spacing: 0.01em; }
.opener.drop-1 { margin-bottom: 1.2em; }
.opener.drop-2 { margin-bottom: 2.6em; }
.opener.drop-3 { margin-top: 1.5em; margin-bottom: 5em; }
.opener.inline { margin-top: 0.4em; }
.opener.inline h1 { font-size: 1.2em; }

.opener .chapter-eyebrow.align-right,
.opener .chapter-eyebrow.align-left,
.opener .chapter-eyebrow.align-center {
    width: auto;
    border-bottom: none;
    padding-bottom: 0;
    margin: 0 0 1.4em;
    color: #333333;
}
.opener .chapter-eyebrow.gap-2 { margin-bottom: 2.6em; }
.opener .chapter-eyebrow.gap-3 { margin-bottom: 5em; }
.opener .chapter-eyebrow.scale-large { font-size: 1.3em; letter-spacing: 0.16em; }
.opener .chapter-eyebrow.scale-medium { font-size: 1em; letter-spacing: 0.12em; }

.opener h1.scale-large { font-size: 1.6em; }
.opener h1.scale-medium { font-size: 1.3em; }
.opener h1.scale-small { font-size: 1.1em; }
.opener.inline h1.scale-medium,
.opener.inline h1.scale-large { font-size: 1.2em; }

.opener .opener-byline {
    font-style: italic;
    font-size: 0.95em;
    margin: -0.4em 0 0;
}
.opener.align-left .opener-byline { text-align: left !important; }
.opener.align-right .opener-byline { text-align: right !important; }
.opener + p { text-indent: 0 !important; }

.align-left { text-align: left !important; }
.align-right { text-align: right !important; }
.align-center { text-align: center !important; }

/* A heading inside a section, set where the book sets it — not a new
   chapter and not a new screen. */
h2.subheading {
    page-break-before: auto;
    text-align: left;
    font-size: 1.15em;
    margin: 1.6em 0 0.6em;
}
h2.subheading + p { text-indent: 0 !important; }

/* Contents entries nested the way the book nests them. */
.toc-entry.toc-level-1 { padding-left: 0; }
.toc-entry.toc-level-2 { padding-left: 1.4em; }
.toc-entry a { color: inherit; text-decoration: none; }
.toc-section-label.toc-level-1 { text-align: left !important; padding-left: 0.4em; }

/* A plate: its pictures, the line naming it, and one numbered caption
   box per picture, stacked. */
figure.plate {
    margin: 1.5em 0;
    page-break-inside: auto;
}
figure.plate .plate-image {
    text-align: center;
    margin: 0 0 0.8em;
}
figure.plate .plate-image img {
    max-width: 100%;
}
figure.plate figcaption {
    text-align: left;
    font-style: normal;
}
p.plate-title {
    text-align: center !important;
    text-indent: 0 !important;
    font-size: 0.8em;
    letter-spacing: 0.08em;
    margin: 0.4em 0 1em;
}
div.plate-caption {
    margin: 0 0 0.9em;
    padding-left: 0.6em;
    border-left: 1px solid #999;
    font-size: 0.85em;
    page-break-inside: avoid;
}
div.plate-caption p {
    text-indent: 0 !important;
    text-align: left !important;
    margin: 0 0 0.3em;
}
div.plate-caption p.plate-num {
    font-weight: bold;
    margin-bottom: 0.15em;
}

/* A quotation set inside the column, and its source set flush right. */
p.quote-block {
    margin: 0.9em 0 0.9em 2em;
    text-indent: 0 !important;
    font-style: italic;
}
p.quote-block + p.quote-block { margin-top: 0; }
p.attribution {
    text-align: right !important;
    text-indent: 0 !important;
    font-size: 0.82em;
    margin: 0.2em 0 1.4em;
}
p.quote-block + p.attribution { margin-top: -0.5em; }

/* Silent auto-split continuation marker (visually invisible, semantic only) */
.chapter-continues::after {
    content: "";
}

.page-break {
    page-break-after: always;
}
""".strip()

# Added for a book that separates its paragraphs with white space and no
# first-line indent, as measured by pdf_parser._build_style_profile.
SPACED_PARAGRAPHS_CSS = """
p {
    text-indent: 0 !important;
    margin: 0 0 0.75em 0;
}
""".strip()


def book_css(paragraph_style: str) -> str:
    return MATBAA_CSS + ("\n\n" + SPACED_PARAGRAPHS_CSS if paragraph_style == "spaced" else "")
