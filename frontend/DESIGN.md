---
name: Matbaa — Haşiye
description: An annotated edition on bone paper — iron ink, one rubric red, Garamond, rules that cross at the corners, books as cloth-bound editions.
colors:
  bone: "#f3eee3"
  sheet: "#faf7f0"
  desk: "#ebe4d6"
  iron: "#1a1a1a"
  slate: "#5f5e5b"
  slate-light: "#6b6b6b"
  ash: "#b7b7b7"
  rubric: "#c23a2a"
  rubric-ink: "#b0321f"
  rubric-deep: "#a32c1c"
  rubric-tint: "#f1e3d6"
  good: "#3f6b3f"
  cloth-bone: "#d8c9ad"
  cloth-iron: "#343332"
  cloth-chalk: "#e6e1d6"
  cloth-rubric: "#a63829"
typography:
  display:
    fontFamily: "EB Garamond, Garamond, serif"
    fontSize: "3.5rem"
    fontWeight: 400
    lineHeight: 1.08
    letterSpacing: "-0.01em"
  title:
    fontFamily: "EB Garamond, Garamond, serif"
    fontSize: "2.5rem"
    fontWeight: 400
    lineHeight: 1.12
  heading:
    fontFamily: "EB Garamond, Garamond, serif"
    fontSize: "1.5rem"
    fontWeight: 500
    lineHeight: 1.25
  reading:
    fontFamily: "EB Garamond, Garamond, serif"
    fontSize: "max(16px, 1.1875rem)"
    fontWeight: 400
    lineHeight: 1.5
  body:
    fontFamily: "EB Garamond, Garamond, serif"
    fontSize: "max(15px, 1rem)"
    fontWeight: 400
    lineHeight: 1.5
  small:
    fontFamily: "EB Garamond, Garamond, serif"
    fontSize: "max(13px, 0.875rem)"
    fontWeight: 400
    lineHeight: 1.4
  caps:
    fontFamily: "EB Garamond, Garamond, serif"
    fontSize: "max(10px, 0.7188rem)"
    fontWeight: 500
    letterSpacing: "0.17em"
rounded:
  none: "0"
  tome: "1px 4px 4px 1px"
spacing:
  s-1: "0.25rem"
  s-2: "0.5rem"
  s-3: "0.75rem"
  s-4: "1rem"
  s-5: "1.25rem"
  s-6: "1.5rem"
  s-8: "2rem"
  s-10: "2.5rem"
  s-12: "3rem"
  s-16: "4rem"
components:
  button-primary:
    backgroundColor: "{colors.rubric}"
    textColor: "{colors.bone}"
    typography: "{typography.caps}"
    rounded: "{rounded.none}"
    padding: "0.5625rem 1rem 0.5rem"
  button-primary-hover:
    backgroundColor: "{colors.rubric-deep}"
  button-secondary:
    backgroundColor: "transparent"
    textColor: "{colors.iron}"
    typography: "{typography.caps}"
    rounded: "{rounded.none}"
    padding: "0.5625rem 1rem 0.5rem"
  card:
    backgroundColor: "transparent"
    textColor: "{colors.iron}"
    rounded: "{rounded.none}"
    padding: "1.25rem"
  tome:
    backgroundColor: "{colors.cloth-bone}"
    rounded: "{rounded.tome}"
    width: "6.75rem"
---

# Matbaa — Haşiye

Two design languages, chosen at the top of every screen (`frontend/src/theme.js`):

- **Gece Matbaası** — the print shop at night: charcoal, brass, the vertical type ruler. `src/styles/app.css`, unchanged since it was first made; its header comment is its record.
- **Haşiye** — this document. `src/styles/hasiye.css`, `src/styles/fonts.css`, and the markup only Haşiye renders: `HasiyeStart.jsx` (start screen), `Tome.jsx` (books), `MarginNotes.jsx` (warnings in the editor's margin).

Each language is a whole stylesheet; only the chosen one is on the page. A third language is a third sheet and a third entry in `UiSwitch.jsx` / `theme.js`.

## Overview

*Haşiye* is a marginal note. The app is set as an annotated scholarly edition: what is being worked on sits at its measure on bone paper, and the apparatus — printed page numbers, warnings, counts, the reader's notes — hangs in the margin beside what it concerns, in a red bracket. The reader chose this world from its picture (the impeccable catalogue's "wide-margin reference setting"); its palette is that picture's, taken from the reference board.

The memorable things: Garamond at display size, the red cross on a rule, rules that run past their corners and cross like a ruled page, and the user's books drawn as cloth-bound editions with the PDF cover tipped in as a plate.

## Colors

One accent. Rubric red marks what acts (the primary button), what is current (the active entry, the detent), and the apparatus (margin notes, the alphabet rail, labels of series). Everything else is iron ink on bone.

- `bone` is the page; `sheet` a lighter leaf for the editor's page and thumbnails; the rails (contents, Kindle, book list) take a warm tint of `desk`.
- Small red type uses `rubric-ink` and small grey type `slate`: on the rail tint the lighter `rubric`/`slate-light` fall under 4.5:1.
- The highlighter is a pale rubric wash under the passage (`rgba(194,58,42,.16)`), not yellow.
- Book cloth: bone linen, iron black, chalk white, rubric red — chosen by the title's hash so a book always wears the same cloth.

## Typography

EB Garamond throughout (self-hosted, Latin and Latin Extended: every Turkish letter). Display 3.5rem regular; headings 1.5–2.5rem at 400–500; reading text (passages, highlights) 1.1875rem; body 1rem; apparatus in letterspaced capitals (0.72rem, 0.17em, uppercase, `lang="tr"` so i becomes İ). Oldstyle figures in running text, lining figures in counts and labels.

Small and reading sizes have floors (`max(15px, 1rem)` and so on) so the fluid scale below never takes text under a readable size. The book's own text inside the editor and the Kindle preview keeps its own stylesheet and size.

## Layout

**The page scales with the window** (studied 2026-10-24). The reader found Haşiye looked best at 80–90% browser zoom; their laptop is 2560×1600 at 150% Windows scaling, about 1707×900 CSS px at 100%. The root size is a straight line between two poles, after utopia.fyi's fluid scales:

```css
html { font-size: clamp(13px, min(0.53125rem + 0.3513vw, 0.53125rem + 0.667vh), 16px); }
```

13px at 1280 wide, 16px from about 2130 wide (or 1125 tall); 14.5px at 1707×900, which is the proportions of 90% zoom. Spacing and layout widths are in rem, so the whole composition scales together. Measured: the start screen fits 1707×900 and 1920×950 in one view; a short-window layout (`max-height: 760px`) keeps the shelf in view at 1280×650.

- Start screen: a running head; a 15.5–17rem contents column at left; a lead of three columns (the call · the alphabet rail · the last book read) and the shelf below. Under 1366px the side column narrows and the margin note drops under its passage; under 900px everything stacks.
- Workbench: contents rail · the page (a sheet at most 48.75rem, wide outer margin for page numbers at left and warning keys at right) · the Kindle.
- Okuma Defteri: book list · the column centred at 58rem, each passage's page in a bracket in the right margin.
- One spacing scale (4px steps in rem); more space above a heading than below.

## Elevation & Depth

Flat paper. Depth only where an object lifts: the dialog sheet (`--lift`), the drop overlay, and the books, whose shadow is a soft drop with the hinge's shadow and light at the spine; a book rises 4px with a slight turn on hover. No glows, no hard offset shadows.

## Shapes

No radius anywhere except a book's boards (1px at the spine, 4px at the fore-edge). Rules are one pixel. Buttons, cards and dialogs are ruled frames whose lines run 5px past the corners and cross (a `::before` with four 1px gradients, coloured by `--tick`). The red cross is a ruled plus (two 1px bars).

## Components

- **Buttons**: secondary a ruled frame in iron; primary filled rubric with an inner paper hairline (`inset 0 0 0 3px rubric, inset 0 0 0 4px bone/60%`). In a crowded head (the workbench) the book's own work is words in capitals without frames; only "send to Kindle" is ruled and "make the EPUB" filled.
- **Labels**: letterspaced capitals; anything that rides inside a capitals label (a count, a hint) is set in plain italic.
- **Margin note**: a red bracket (`border` on three sides of a 7–8px box) with a red tick at its middle; page number roman, detail italic.
- **Tome** (`Tome.jsx`): cloth, linen weave (two 1px repeating gradients), spine hinge gradient, plate (the PDF cover) at 19%/13% insets, or a title label; a red cross stamped below.
- **Shelf card**: ruled frame; tome at left; red series line, title, short red rule, italic author, "Kitabı aç" and a ruled plus; cards rise in, 70ms apart.
- **Alphabet rail**: the Turkish alphabet; letters that begin a book are red and filter the shelf; red square detents at its ends.
- **Contact sheet** (page review): plain text pages quiet; the cover double-ruled red, an image page ruled in ink, contents in green, an excluded page struck through.
- **Margin notes in the editor** (`MarginNotes.jsx`): a chapter warning that quotes its paragraph is placed beside it as a key; a click opens the note under the paragraph and marks the paragraph.

## Do's and Don'ts

- Do keep one accent: rubric for action, current and apparatus — never for decoration of body text.
- Do put the apparatus in the margin, beside what it concerns, in the bracket.
- Do give capitals buttons room: their ruled corners must not touch (≥1.25rem between frames).
- Do test at the reader's real sizes: 1707×900 (laptop, 100%), 1920×950 (external monitor), 1280×650 (small/short); `frontend/dev/design_check.js` measures contrast, sizes and line length in the browser, `tools/design_coverage.py` that every class has a rule.
- Don't change `app.css`: Gece Matbaası is a finished language.
- Don't restyle the book: the editor's text and the Kindle preview show the EPUB's own stylesheet.
- Don't use rounded corners, colored side bars, glows, gradients on text, or emoji/unicode glyphs as icons where `Icon.jsx` has a drawn mark.
- Don't let the fluid scale take text under its floors.

Sources: NN/g on scanning patterns and visual hierarchy; Butterick, *Practical Typography*; Tschichold/Van de Graaf page canon; utopia.fyi fluid type and space; the impeccable catalogue's reference-setting board (palette and component grammar); Refero (Literal, Readwise).
