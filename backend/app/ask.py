"""Asking a book a question ("Kitapla sohbet").

The question finds its passages (app/search.py); the passages and the
question become one request, which the reader takes to ChatGPT (copied,
then the answer pasted back) or which a configured model answers
(app/llm.py). Either way the answer is checked against the book before the
reader relies on it: every quotation must be the book's own words, and the
page it is cited on must hold them (or the next or last one). What does not
hold is marked, not hidden; an answer that cites nothing is marked too.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from app.notebook import BookText, book_blocks, fold_ascii
from app.search import Hit

SYSTEM = (
    "Bir okurun okuduğu kitap hakkındaki sorusunu yanıtlıyorsun. Yalnız aşağıdaki pasajlara dayan; pasajlarda "
    "olmayan bir şeyi kitap söylüyormuş gibi yazma, yoksa \"Bu pasajlarda bulamadım\" de. Her iddianın arkasına "
    "kaynağını [s. N] biçiminde yaz (sayfası olmayan pasaj için [pasaj K]). Kitaptan alıntı yapacaksan tırnak "
    "içinde, kelimesi kelimesine yap. Kendi yorumunu kitabın söylediğinden ayır. Türkçe, kısa ve açık yaz."
)
QUOTE = re.compile(r"[“\"«]([^”\"»]{12,})[”\"»]")
CITE = re.compile(r"\[\s*(?:s\.|sayfa|pasaj|p\.)\s*([0-9]+|[ivxlcdm]+)\s*\]", re.I)


def prompt(question: str, hits: List[Hit], with_instructions: bool = True) -> str:
    """The request: the question and its passages, numbered, with pages."""
    lines = []
    if with_instructions:
        lines += [SYSTEM, ""]
    books = sorted({h.book_title for h in hits})
    if len(books) == 1:
        lines.append(f"Kitap: {books[0]}")
    lines += [f"Soru: {question.strip()}", "", "Pasajlar:"]
    for k, h in enumerate(hits, 1):
        where = [f"s. {h.page}" if h.page else f"pasaj {k}", h.chapter_title or ""]
        if len(books) > 1:
            where.insert(0, h.book_title)
        lines.append(f"[{k}] ({' · '.join(w for w in where if w)}) {h.text}")
    return "\n".join(lines)


def _near(page: Optional[str], cited: List[str]) -> bool:
    if not page:
        return False
    if page in cited:
        return True
    if page.isdigit():
        return any(c.isdigit() and abs(int(c) - int(page)) <= 1 for c in cited)
    return False


def check(answer: str, hits: List[Hit], session=None) -> Dict:
    """What of the answer holds against the book."""
    cited = [m.group(1).lower() for m in CITE.finditer(answer or "")]
    book_text = BookText(book_blocks(session)) if session is not None else None
    quotes = []
    for m in QUOTE.finditer(answer or ""):
        quote = m.group(1).strip()
        folded = fold_ascii(quote)
        page = None
        found = False
        for k, h in enumerate(hits, 1):
            if folded and folded in fold_ascii(h.text):
                found, page = True, (h.page or "").split("–")[0] or f"pasaj {k}"
                break
        if book_text is not None and len(folded) >= 12:
            # the page the quotation itself is on, from the book's page marks
            placed = book_text.find(quote)
            if placed is not None and placed.exact:
                found, page = True, placed.page or page
        quotes.append({"text": quote, "found": found, "page": page,
                       "page_ok": (_near(page, cited) if (found and cited and page and not page.startswith("pasaj"))
                                   else None)})
    return {"quotes": quotes, "cited": cited, "uncited": not cited,
            "ok": bool(cited) and all(q["found"] and q["page_ok"] is not False for q in quotes)}


# --- into the book's note ------------------------------------------------------------

SECTION = "## Kitaba sorduklarım"
MARK = "matbaa:soru"


def question_id(question: str, answer: str) -> str:
    import hashlib
    return "q-" + hashlib.sha1((question.strip() + "\n" + answer.strip()).encode("utf-8")).hexdigest()[:8]


def block(question: str, answer: str, hits: List[Hit]) -> str:
    """The question in the reader's own words, as an open task (so "Açık
    Sorular" gathers it until they tick it), and the answer in the vault's
    collapsed "Yardımcı bağlam · AI" box, with the pages it rests on."""
    lines = [f"- [ ] {' '.join(question.split())}", "> [!quote]- *Yardımcı bağlam · AI*"]
    for para in [p.strip() for p in (answer or "").strip().split("\n") if p.strip()]:
        lines.append(f"> *{para}*")
    pages = []
    for h in hits:
        label = f"s. {h.page}" if h.page else None
        if label and label not in pages:
            pages.append(label)
    if pages:
        lines.append(f"> *Pasajlar: {', '.join(pages)}*")
    lines.append(f"%% {MARK} {question_id(question, answer)} %%")
    return "\n".join(lines)


def add_to_note(text: str, entry: str) -> str:
    """The note with the question added at the end of its "Kitaba
    sorduklarım" section (made before the reader's closing notes, or at the
    end, when the note has none yet). Nothing else is touched."""
    from app.obsidian import FINAL_HEADING

    text = (text or "").replace("\r\n", "\n")
    lines = text.split("\n")
    at = next((i for i, ln in enumerate(lines) if ln.strip() == SECTION), None)
    if at is not None:
        end = next((i for i in range(at + 1, len(lines)) if lines[i].startswith("#")), len(lines))
        last = end - 1
        while last > at and not lines[last].strip():
            last -= 1
        lines[last + 1:last + 1] = ["", entry]
        out = "\n".join(lines)
    else:
        final = FINAL_HEADING.search(text)
        section = f"{SECTION}\n\n{entry}\n"
        if final:
            out = text[:final.start()].rstrip("\n") + "\n\n" + section + "\n" + text[final.start():]
        else:
            out = text.rstrip("\n") + "\n\n" + section
    return out if out.endswith("\n") else out + "\n"


def plan_note(path: str, exists: bool, question: str, answer: str, hits: List[Hit], book_title: str,
              author: str = "", today: Optional[str] = None):
    """The book note as it would be with the question added (nothing is
    written here); a FilePlan like the Okuma Defteri's."""
    import datetime as _dt

    from app.obsidian import FilePlan, _diff, _fingerprint

    today = today or _dt.date.today().isoformat()
    old = open(path, encoding="utf-8").read() if exists else ""
    if f"{MARK} {question_id(question, answer)}" in old:
        return FilePlan(path, old, exists, "", _fingerprint(old) if exists else "")
    base = old if exists else "\n".join(["---", "tags:", "  - Kitap", f"Created: {today}", "Source:",
                                         f"Author: {author}" if author else "Author:", "aliases:",
                                         "Discovered via:", "---", "", f"# {book_title}", ""])
    text = add_to_note(base, block(question, answer, hits))
    return FilePlan(path, text, exists, _diff(old, text, path), _fingerprint(old) if exists else "")
