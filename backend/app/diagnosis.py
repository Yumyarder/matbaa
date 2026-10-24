"""The book's own report: what kind of PDF it was, what the engine did with
it, and what it could not resolve.

The measures are the ones the library QA has been judging every change by
(tools/qa/library_one.py uses this module), so what the program tells the
reader about a book and what the developer measures are the same numbers.

An issue the rules here cannot fix — text the scanner misread, paragraphs a
broken layer cut apart, notes nothing marks — is reported with what to do
about it, and flagged when a large language model is the right tool. The
report can be exported as a bundle (report + the passages concerned) for
whichever model the user has; nothing is sent anywhere by this module.
"""
from __future__ import annotations

import html
import re
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

from app.utils.text_quality import garbage_share

TAG = re.compile(r"<[^>]+>")
LIST_ITEM = re.compile(r"^(?:[a-zçğıöşü]|[ivx]{1,4})[)\]]\s")
EM_RUN = re.compile(r"<em>(.*?)</em>", re.S)
LEADER_TITLE = re.compile(r"(\.\s*){4,}|…{2,}")
IMPRINT_TITLE = re.compile(
    r"ilk defa|yayınlanmıştır|ISBN|Sertifika|Alıntılarda|kaynak gösterilmesi|Telegram|@\w|www\.|https?://",
    re.IGNORECASE,
)


def fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", (text or "").casefold())
    return re.sub(r"[^a-z0-9]+", "", "".join(c for c in text if not unicodedata.combining(c)).replace("ı", "i"))


def _is_lower_start(plain: str) -> bool:
    return plain[:1].islower() and not LIST_ITEM.match(plain)


def measure(result) -> Dict:
    """Numbers describing a conversion result (a ConversionResult)."""
    rec: Dict = {}
    real = [c for c in result.chapters if c.kind == "chapter" and not c.is_split_continuation]
    kinds = Counter(c.kind for c in result.chapters)
    rec["chapters"] = len(real)
    rec["image_pages"] = kinds.get("image", 0)
    rec["frontmatter"] = kinds.get("frontmatter", 0)
    titles = [c.title for c in real]
    rec["titles"] = [t[:70] for t in titles[:40]]
    folded_titles = Counter(fold(t) for t in titles if fold(t))
    rec["dup_titles"] = sum(n for n in folded_titles.values() if n > 1)
    rec["imprint_titles"] = sum(1 for t in titles if IMPRINT_TITLE.search(t))
    rec["leader_titles"] = sum(1 for t in titles if LEADER_TITLE.search(t))
    rec["junk_titles"] = sum(1 for t in titles if garbage_share(t) > 0.4 or len(fold(t)) < 3)

    paras = [p for c in result.chapters for p in c.paragraphs]
    plain = [TAG.sub("", p).strip() for p in paras]
    body = "\n".join(plain)
    words = len(body.split())
    rec["words"] = words
    rec["garbage"] = garbage_share(body)
    rec["paragraphs"] = len(paras)
    # "a) …", "iv) …" items start in lower case by design, and so do an
    # index's entries ("ağ oluşturma, 49-50")
    running = [t for p, t in zip(paras, plain) if "index-entry" not in p]
    rec["lower_ratio"] = round(sum(1 for t in running if _is_lower_start(t)) / max(1, len(running)), 4)
    rec["quote_share"] = round(sum(1 for p in paras if "quote-block" in p) / max(1, len(paras)), 3)
    rec["em_per_kw"] = round(sum(p.count("<em>") for p in paras) / max(1, words) * 1000, 1)
    # Many <em> runs are an author's style; a paragraph italic from end to
    # end that is not a quotation is a body face mistaken for emphasis.
    prose = [(p, t) for p, t in zip(paras, plain) if len(t) >= 80]
    rec["em_flood_share"] = round(sum(
        1 for p, t in prose
        if len("".join(TAG.sub("", e) for e in EM_RUN.findall(p))) > 0.6 * len(t)
    ) / max(1, len(prose)), 3)
    rec["notes"] = sum(len(c.footnotes) for c in result.chapters)
    rec["note_links"] = sum(p.count('epub:type="noteref"') for p in paras)
    rec["figures"] = sum(len(c.images) for c in result.chapters)
    rec["language"] = result.detected_language
    rec["critical"] = sum(1 for w in result.warnings if w.get("severity") == "critical")
    return rec


@dataclass
class Issue:
    code: str
    severity: str                # "critical" | "warning" | "info"
    message: str                 # what is wrong, in the reader's words
    suggestion: str              # what to do about it
    llm: bool = False            # a language model is the right tool for it
    chapter_ids: List[str] = field(default_factory=list)
    samples: List[str] = field(default_factory=list)   # the passages concerned


@dataclass
class BookReport:
    kind: str                    # one line: what this PDF is
    strategy: List[str]          # what the engine did, in order
    measures: Dict
    issues: List[Issue]
    score: int                   # 0-100, a rough readiness figure

    def to_dict(self) -> Dict:
        return asdict(self)


def _pdf_kind(context: Dict) -> str:
    if context.get("ocr_reason") == "unreadable":
        return "Metin katmanı bozuk bir PDF (karakter eşlemesi kırık); sayfalar OCR ile yeniden okundu."
    if context.get("ocr_pages"):
        return f"Taranmış kitap; {context['ocr_pages']} sayfa OCR ile okundu."
    producer = (context.get("producer") or "").lower()
    if any(k in producer for k in ("abbyy", "finereader", "paper capture", "clearscan", "scan")):
        return "Taranmış kitap; taramayı yapan programın kendi metin katmanı kullanıldı."
    return "Dijital olarak dizilmiş kitap; metin katmanı doğrudan okundu."


def _strategy(decisions: Dict) -> List[str]:
    out: List[str] = []
    source = decisions.get("structure")
    if source == "printed_toc":
        if decisions.get("toc_sequential"):
            out.append("Bölümler basılı İçindekiler sayfasından alındı. Sayfa numaraları bu PDF'e "
                       "uymadığı için (başka bir baskıdan) her başlık kitapta sırayla arandı.")
        else:
            out.append("Bölümler basılı İçindekiler sayfasından, sayfa numaralarıyla eşlenerek alındı.")
        if decisions.get("toc_unmatched"):
            out.append(f"İçindekiler'deki {decisions['toc_unmatched']} başlık kitapta bulunamadı; "
                       "bu bölümler öncekiyle birleşmiş olabilir.")
    elif source == "outline":
        out.append("Bölümler PDF'in yer imlerinden (outline) alındı.")
    else:
        out.append("Kullanılabilir bir İçindekiler ya da yer imi bulunamadı; bölümler yazı "
                   "boyutu ve biçiminden tahmin edildi.")
    if decisions.get("running_removed"):
        out.append(f"Sayfa üst/alt başlıkları ve folyolar ayıklandı ({decisions['running_removed']} satır).")
    if decisions.get("words_repaired"):
        out.append(f"{decisions['words_repaired']} paragrafta tarayıcının yanlış okuduğu kelimeler, kitabın "
                   "başka yerde doğru yazdığı biçimle düzeltildi (ör. kaynakçada düşen baş harf, harfe dönmüş yıl).")
    if decisions.get("printed_pages"):
        out.append(f"Basılı sayfa numaraları kenardaki numaralardan okundu ({decisions['printed_pages']} sayfa); "
                   "Kindle kitabın kendi sayfa numaralarını gösterir, alıntılar basılı sayfaya göre olur.")
    if decisions.get("rescaled_pages"):
        out.append(f"{decisions['rescaled_pages']} sayfada metin katmanı yazı boyutunu yanlış bildiriyordu; "
                   "satır aralığına göre düzeltildi.")
    return out


def _sample_lowercase(result, limit: int = 3) -> (List[str], List[str]):
    chapter_ids: List[str] = []
    samples: List[str] = []
    for c in result.chapters:
        prev = None
        for p in c.paragraphs:
            t = html.unescape(TAG.sub("", p)).strip()
            if prev is not None and _is_lower_start(t) and "page-aside" not in p and "index-entry" not in p:
                if c.id not in chapter_ids:
                    chapter_ids.append(c.id)
                if len(samples) < limit:
                    samples.append(f"…{prev[-80:]} ¶ {t[:80]}…")
            prev = t
    return chapter_ids, samples


def build_report(result, context: Optional[Dict] = None) -> BookReport:
    """`context`: what the caller knows about the source PDF — producer,
    ocr_pages, ocr_reason — and `decisions` the engine recorded."""
    context = context or {}
    m = measure(result)
    decisions = getattr(result, "decisions", None) or {}
    issues: List[Issue] = []

    if m["garbage"] > 0.15:
        issues.append(Issue(
            "noisy_text", "critical",
            f"Metnin yaklaşık %{round(m['garbage'] * 100)}'i okunaklı kelime değil (OCR gürültüsü ya da bozuk karakterler).",
            "Sayfaları daha iyi bir OCR ile yeniden okutun; kalan bozuk pasajları bir dil modeline "
            "'yalnız OCR hatalarını düzelt, metni değiştirme' talimatıyla verin.",
            llm=True))
    elif m["garbage"] > 0.05:
        issues.append(Issue(
            "some_noise", "warning",
            f"Metnin %{round(m['garbage'] * 100)}'i kadarı okunaklı kelime değil.",
            "Kitabı okurken göze batan pasajları düzenleyicide düzeltin ya da bir dil modeline verin.",
            llm=True))

    # Lines off notes and index pages ("page-aside", "index-entry") start where they start;
    # the reader is told only about running text.
    running = [p for c in result.chapters for p in c.paragraphs if "page-aside" not in p and "index-entry" not in p]
    n = sum(1 for p in running if _is_lower_start(TAG.sub("", p).strip()))
    if n:
        ids, samples = _sample_lowercase(result)
        issues.append(Issue(
            "broken_paragraphs", "warning" if n > 0.02 * max(1, len(running)) else "info",
            f"{n} paragraf küçük harfle başlıyor; büyük olasılıkla bir cümle sayfa geçişinde ikiye bölündü.",
            "Düzenleyicide bu paragrafları bir öncekiyle birleştirin. Çok sayıdaysa bölüm metnini bir dil "
            "modeline 'yalnız bölünmüş paragrafları birleştir' talimatıyla verin.",
            llm=n > 20, chapter_ids=ids, samples=samples))

    if m["notes"] >= 5 and m["note_links"] < 0.8 * m["notes"]:
        unlinked_in = [c.id for c in result.chapters
                       if c.footnotes and sum(p.count('epub:type="noteref"') for p in c.paragraphs) < len(c.footnotes)]
        issues.append(Issue(
            "unlinked_notes", "warning",
            f"{m['notes']} notun {m['note_links']}'i metindeki atfına bağlanabildi.",
            "Atıf işaretleri metinde ayırt edilemiyor (OCR ya da biçim). Notlar kitabın sonunda okunabilir; "
            "bağlantılar için not listesi ve bölüm metni bir dil modeline eşleştirtilebilir.",
            llm=True, chapter_ids=unlinked_in))

    bad_titles = m["junk_titles"] + m["leader_titles"] + m["imprint_titles"]
    if bad_titles:
        issues.append(Issue(
            "bad_titles", "warning",
            f"{bad_titles} bölüm başlığı bozuk görünüyor (gürültü, nokta dizisi ya da künye satırı).",
            "Bölüm listesinde bu başlıkları yeniden adlandırın ya da bölümü öncekiyle birleştirin."))
    if m["dup_titles"]:
        issues.append(Issue(
            "repeated_titles", "info",
            f"{m['dup_titles']} bölüm aynı başlığı paylaşıyor.",
            "Kitabın gerçekten tekrar eden bölüm adları olabilir (ör. her kısımda 'Giriş'); değilse birleştirin."))
    if m["chapters"] == 0:
        issues.append(Issue(
            "no_chapters", "critical", "Kitapta hiç bölüm bulunamadı; bütün metin tek parça.",
            "Sayfa incelemede İçindekiler sayfasını 'İçindekiler' olarak işaretleyip yeniden dönüştürün."))
    elif m["words"] and m["chapters"] <= 2 and m["words"] > 15000:
        issues.append(Issue(
            "few_chapters", "warning",
            f"{m['words']} kelimelik kitap yalnız {m['chapters']} bölüm olarak çıktı.",
            "Sayfa incelemede İçindekiler sayfasını işaretleyin; Kindle'da bölümler arası gezinme için gerekli."))
    if m["em_flood_share"] > 0.05:
        issues.append(Issue(
            "italic_flood", "info",
            "Paragrafların bir kısmı baştan sona italik görünüyor.",
            "Kitabın gövde yazısı italik bir yazı tipiyle dizilmiş olabilir; düzenleyiciden düzeltin."))

    penalty = sum({"critical": 30, "warning": 10, "info": 2}[i.severity] for i in issues)
    return BookReport(
        kind=_pdf_kind(context),
        strategy=_strategy(decisions),
        measures={k: v for k, v in m.items() if k != "titles"},
        issues=issues,
        score=max(0, 100 - penalty),
    )


def _chapter_text(c) -> str:
    paragraphs = getattr(c, "paragraphs", None)
    if paragraphs is None:
        paragraphs = re.split(r"(?<=</p>)|(?<=</div>)|(?<=</h2>)", getattr(c, "html", "") or "")
    return html.unescape("\n\n".join(t for t in (TAG.sub("", p).strip() for p in paragraphs) if t))


def llm_bundle(report: Dict, chapters, book_title: str = "") -> Dict:
    """Everything a language model needs to work on the open issues, as one
    JSON-ready dict: the report, and for each issue the passages concerned.
    `report` is BookReport.to_dict(); `chapters` anything with id, title and
    paragraphs or html. Nothing is sent from here; the user decides where."""
    chapters = {c.id: c for c in chapters}
    tasks = []
    for issue in report.get("issues", []):
        if not issue.get("llm"):
            continue
        passages = []
        for cid in issue.get("chapter_ids", [])[:5]:
            c = chapters.get(cid)
            if c is not None:
                passages.append({"chapter": c.title, "text": _chapter_text(c)[:20000]})
        tasks.append({"issue": issue["code"], "problem": issue["message"], "instruction": issue["suggestion"],
                      "samples": issue.get("samples", []), "passages": passages})
    return {"book": book_title, "kind": report.get("kind"), "strategy": report.get("strategy", []),
            "tasks": tasks}
