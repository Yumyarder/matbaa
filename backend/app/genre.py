"""What kind of book this is: a guess, made on this computer, that the reader
can change.

Matbaa counts the books it set by genre (the site's counter, the library's
"Türe göre" tab) and writes the genre into the EPUB (dc:subject). The guess
reads only what the book says of itself:

1. Fiction or not. The imprint and front pages naming it ("roman", "öykü",
   "şiir", a "Klasikleri" series), the share of paragraphs that open a line
   of dialogue; against it, a bibliography or an index among the chapters.
2. Fiction by origin. The language the imprint says it was translated from
   ("Rusçadan çeviren"), an original title in Cyrillic, a Russian surname;
   a translator from another language makes it world literature, none and
   a Turkish text Turkish literature.
3. Otherwise the subject whose word stems the title, the chapter titles and
   the text use most. Turkish puts its suffixes on the end, so a stem
   ("felsef") finds every form ("felsefenin", "felsefi"); it counts only
   where what follows reads as suffixes ("para" in "paranın", not in
   "paragraf").

A weak guess is "Diğer". Nothing here leaves the computer.
"""
from __future__ import annotations

import html as html_lib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from app.turkish_words import lower_tr, suffix_chain, words

GENRES: List[Tuple[str, str]] = [
    ("felsefe", "Felsefe"),
    ("siyaset", "Siyaset"),
    ("ekonomi", "Ekonomi"),
    ("tarih", "Tarih"),
    ("sosyoloji", "Sosyoloji"),
    ("psikoloji", "Psikoloji"),
    ("sanat", "Sanat ve mimari"),
    ("bilim", "Bilim"),
    ("kisisel", "Kişisel gelişim"),
    ("din", "Din ve mitoloji"),
    ("turk-edebiyati", "Türk edebiyatı"),
    ("rus-edebiyati", "Rus edebiyatı"),
    ("dunya-edebiyati", "Dünya edebiyatı"),
    ("diger", "Diğer"),
]
LABELS = dict(GENRES)
FICTION = {"turk-edebiyati", "rus-edebiyati", "dunya-edebiyati"}

# subject stems: (stem, weight); a weak weight for a word every kind of book uses
TR_STEMS: Dict[str, List[Tuple[str, float]]] = {
    "felsefe": [("felsef", 1.5), ("filozof", 1.5), ("ontoloj", 2), ("epistemoloj", 2), ("metafizi", 1.5),
                ("fenomenoloj", 2), ("diyalekti", 0.8), ("materyalis", 0.8), ("idealis", 1.2), ("varlık", 0.8),
                ("akıl", 0.6), ("akl", 0.6), ("ahlak", 1.0), ("etik", 0.8), ("mantık", 0.8), ("töz", 1.5),
                ("kant", 1.2), ("hegel", 1.5), ("nietzsche", 1.5), ("spinoza", 1.5), ("aristoteles", 1.5),
                ("platon", 1.5), ("sokrates", 1.5), ("heidegger", 1.5), ("descartes", 1.5), ("düşünür", 0.8),
                ("teori", 0.4), ("pratik", 0.4), ("bilinç", 0.5), ("çelişki", 0.8)],
    "siyaset": [("siyas", 1.0), ("politik", 1.0), ("devlet", 0.8), ("iktidar", 0.9), ("parti", 1.0),
                ("devrim", 1.2), ("ihtilal", 1.2), ("demokra", 0.8), ("emperyal", 1.2), ("faşi", 1.0),
                ("sosyalis", 1.0), ("komünis", 1.0), ("proletarya", 1.5), ("burjuva", 1.2), ("işçi", 0.7),
                ("sınıf", 0.7), ("hükümet", 0.8), ("lenin", 1.2), ("marksis", 1.0), ("oportünis", 1.5),
                ("reformis", 1.2), ("örgüt", 0.8), ("sendika", 1.0), ("kitle", 0.5), ("darbe", 1.0),
                ("cunta", 1.2), ("fraksiyon", 1.5), ("program", 0.4), ("strateji", 0.5)],
    "ekonomi": [("ekonomi", 1.2), ("iktisa", 1.5), ("sermaye", 1.2), ("kapital", 0.9), ("piyasa", 1.2),
                ("faiz", 1.5), ("enflasyon", 1.5), ("para", 0.6), ("ücret", 1.0), ("fiyat", 1.0),
                ("üretim", 0.7), ("meta", 0.8), ("kriz", 0.8), ("finans", 1.2), ("ticaret", 1.0), ("banka", 1.0),
                ("ihracat", 1.2), ("ithalat", 1.2), ("borç", 0.8), ("yatırım", 1.0), ("gelir", 0.6),
                ("vergi", 1.0), ("sanayi", 0.8), ("tarım", 0.6), ("kâr", 0.8), ("ekonomik", 0.6)],
    "tarih": [("tarih", 0.35), ("yüzyıl", 0.8), ("osmanlı", 1.5), ("imparatorluk", 1.2), ("hanedan", 1.5),
              ("padişah", 1.5), ("sultan", 1.0), ("antik", 0.8), ("ortaçağ", 1.5), ("savaş", 0.5),
              ("meşrutiyet", 1.5), ("ittihat", 1.2), ("kronoloj", 1.0), ("tarihçi", 1.2), ("dönem", 0.4),
              ("bizans", 1.5), ("selçuklu", 1.5), ("cumhuriyet", 0.4)],
    "sosyoloji": [("sosyoloj", 1.5), ("toplum", 0.6), ("kent", 0.9), ("gündelik", 0.8), ("kimlik", 0.8),
                  ("kültür", 0.6), ("modernite", 1.2), ("cemaat", 0.8), ("aile", 0.4), ("göç", 0.8),
                  ("mahalle", 0.8), ("müşterek", 1.2), ("kamusal", 1.0), ("sosyal", 0.6), ("mekân", 0.6),
                  ("mekan", 0.6), ("kentsel", 0.8), ("cinsiyet", 0.9), ("toplumsal", 0.4)],
    "psikoloji": [("psikoloj", 2), ("psikiyatr", 1.5), ("terapi", 1.5), ("bilişsel", 1.5), ("depresyon", 1.5),
                  ("kaygı", 1.0), ("anksiyete", 1.5), ("travma", 1.2), ("duygu", 0.8), ("davranış", 0.8),
                  ("nevroz", 1.5), ("psikanaliz", 2), ("bilinçdışı", 1.5), ("freud", 1.5), ("özgüven", 1.5),
                  ("utangaç", 1.5), ("şema", 1.2), ("zihin", 0.8), ("zihn", 0.8), ("stres", 1.2),
                  ("panik", 1.0), ("öfke", 1.0), ("beyin", 0.6), ("danışan", 1.5)],
    "sanat": [("sanat", 1.0), ("estetik", 1.0), ("mimar", 1.5), ("resim", 1.0), ("ressam", 1.5),
              ("heykel", 1.5), ("sinema", 1.2), ("film", 0.8), ("müzik", 1.2), ("tiyatro", 1.2),
              ("fotoğraf", 1.0), ("bina", 0.8), ("beden", 0.5), ("görsel", 0.8), ("tasarım", 1.0),
              ("duyu", 0.5), ("inşa", 0.6), ("tablo", 0.6), ("yapıt", 0.8), ("eser", 0.4)],
    "bilim": [("bilim", 0.6), ("fizik", 1.5), ("kimya", 1.5), ("biyoloj", 1.5), ("evrim", 1.0), ("deney", 1.0),
              ("genetik", 1.5), ("hücre", 1.5), ("atom", 1.2), ("molekül", 1.5), ("evren", 1.0),
              ("nöron", 1.5), ("matematik", 1.2), ("astronomi", 1.5), ("newton", 1.5), ("einstein", 1.5),
              ("mekanik", 1.0), ("teknoloj", 0.6), ("galile", 1.5)],
    "kisisel": [("alışkanlık", 2), ("motivasyon", 1.5), ("hedef", 1.0), ("başarı", 0.8), ("verimli", 1.5),
                ("üretken", 1.5), ("odak", 1.0), ("rutin", 1.5), ("disiplin", 0.6), ("yaratıcı", 0.8),
                ("ilham", 1.0), ("kariyer", 1.5), ("ertele", 1.5), ("mutlu", 0.8), ("dikkat", 0.5),
                ("zaman", 0.3), ("adım", 0.4), ("egzersiz", 1.0)],
    "din": [("allah", 1.5), ("tanrı", 1.2), ("peygamber", 1.5), ("kuran", 1.5), ("islam", 1.5),
            ("müslüman", 1.2), ("hristiyan", 1.5), ("incil", 1.5), ("tevrat", 1.5), ("yahudi", 1.0),
            ("kilise", 1.2), ("cami", 1.0), ("ibadet", 1.5), ("mezhep", 1.5), ("tasavvuf", 1.5),
            ("mitoloj", 1.5), ("ilah", 1.2), ("kutsal", 1.0), ("vahiy", 1.5), ("şeriat", 1.2),
            ("teoloj", 1.5), ("ilahiyat", 1.5), ("dinsel", 1.2), ("dinler", 0.6)],
}
EN_STEMS: Dict[str, List[Tuple[str, float]]] = {
    "felsefe": [("philosoph", 1.5), ("ontolog", 2), ("metaphys", 1.5), ("epistem", 1.5), ("hegel", 1.5),
                ("nietzsche", 1.5), ("aristotle", 1.5), ("plato", 1.2), ("ethic", 0.8)],
    "siyaset": [("politic", 1.0), ("revolution", 1.2), ("democra", 0.8), ("socialis", 1.0), ("communis", 1.0),
                ("imperialis", 1.2), ("parliament", 1.0), ("election", 0.8), ("government", 0.8)],
    "ekonomi": [("econom", 1.2), ("capital", 0.8), ("market", 0.8), ("inflation", 1.5), ("wage", 1.0),
                ("financ", 1.2), ("trade", 0.6)],
    "tarih": [("histor", 0.6), ("century", 0.8), ("empire", 1.2), ("dynast", 1.5), ("medieval", 1.5)],
    "sosyoloji": [("sociolog", 1.5), ("societ", 0.8), ("urban", 1.0), ("communit", 0.8)],
    "psikoloji": [("psycholog", 2), ("therap", 1.5), ("anxiety", 1.5), ("anxious", 1.5), ("depress", 1.5),
                  ("cognitive", 1.5), ("emotion", 0.8), ("shy", 1.2), ("fear", 0.6), ("trauma", 1.2),
                  ("panic", 1.0)],
    "sanat": [("artist", 1.0), ("aesthet", 1.0), ("paint", 0.8), ("architect", 1.5), ("design", 0.6),
              ("museum", 1.0), ("music", 0.8)],
    "bilim": [("scien", 0.8), ("physic", 1.5), ("chemist", 1.5), ("biolog", 1.5), ("evolution", 1.0),
              ("neuron", 1.5), ("brain", 0.6)],
    "kisisel": [("habit", 1.5), ("productiv", 1.5), ("goal", 1.0), ("motivat", 1.2), ("procrastinat", 1.5),
                ("focus", 1.0), ("routine", 1.2), ("creativ", 0.8), ("career", 1.2), ("success", 0.8),
                ("weeks", 0.4), ("time", 0.3)],
    "din": [("religio", 1.5), ("theolog", 1.5), ("god", 0.8), ("church", 1.2), ("islam", 1.5),
            ("christian", 1.5), ("bible", 1.5), ("myth", 1.2)],
}

DIALOGUE_OPENERS = tuple("—–-\"“«‘'")
# a line of speech says who spoke, or breaks for it with a second dash
SPEECH = re.compile(r"\b(?:de(?:di|dim|din|diler|dikten|mişti)|diye(?:rek)?|sor(?:du|dum|dular|arak)|"
                    r"söyle(?:di|dim|yince)|bağır(?:dı|dım|arak)|fısılda\w*|yanıtla(?:dı|dım)|cevap\s+verdi|"
                    r"said|asked|replied|cried|whispered)\b")
# a cover or imprint names a literary genre on a line of its own ("Roman");
# the same words in a blurb ("bu kitabın hikâyesi") say nothing
FICTION_LINE = re.compile(r"^(roman|romanlar|öykü|öyküler|hikâye|hikâyeler|hikaye|hikayeler|şiir|şiirler|"
                          r"novella|anlatı|edebiyat|novel|stories|poems)$")
SERIES_LINE = re.compile(r"klasikleri|klasikler|edebiyat(?:ı)?\s+dizisi")
NOT_FICTION_SERIES = re.compile(r"felsefe|düşünce|bilim|tarih|siyaset|iktisat|sosyoloji|psikoloji|inceleme|"
                                r"araştırma|kuram")
NONFICTION_CHAPTERS = re.compile(r"^\s*(kaynakça|kaynaklar|bibliyografya|bibliografya|dizin|indeks|"
                                 r"bibliography|references|index)\b", re.I)
# "Rusçadan çeviren", "İngilizce aslından çeviren", "Japonca aslından çeviri"
TRANSLATED_FROM = re.compile(r"(?P<lang>[a-zçğıöşü]{2,}?(?:ce|ca|çe|ça))(?:dan|den|tan|ten)?\s+"
                             r"(?:(?:aslından|asıllarından|orijinalinden|özgün\s+dilinden)\s+)?"
                             r"(?:çevirenler|çeviren|çeviri|türkçeleştiren|tercüme\s+eden)")
CYRILLIC = re.compile(r"[Ѐ-ӿ]")
RUSSIAN_SURNAME = re.compile(r"(?:ski|sky|skiy|vski|ov|ova|ev|eva|yev|yeva|enko|viç|vich|in)$", re.I)
RUSSIAN_NAMES = {"tolstoy", "tolstoi", "gogol", "puşkin", "pushkin", "gorki", "gorky", "bunin", "babel",
                 "çehov", "chekhov", "dostoyevski", "turgenyev", "bulgakov", "nabokov", "lermontov",
                 "goncarov", "gonçarov", "şolohov", "platonov", "pasternak", "zamyatin", "harms"}
TAG = re.compile(r"<[^>]+>")
# a stem that is also the start of a different word with a suffix-like tail
OTHER_WORDS = {"deney": ("deneyim",), "evren": ("evrensel",), "kent": ("kentaur",), "meta": ("metafor",)}
MIN_SCORE = 3.0          # weighted subject hits per thousand words below which the guess is "Diğer"
MIN_STEMS = 3            # a subject is several of its words, not one word said often
WEAK_SUBJECT = 8.0       # below this, one sign of fiction is enough
BODY_LIMIT = 400_000     # characters of text read; plenty to tell a subject


@dataclass
class Guess:
    key: str
    label: str
    confidence: float    # 0.5 (a toss-up) .. 1.0
    reason: str          # one line for the book's report

    def to_dict(self) -> Dict:
        return {"key": self.key, "label": self.label, "confidence": round(self.confidence, 2),
                "reason": self.reason}


def label(key: Optional[str]) -> str:
    return LABELS.get(key or "", "Diğer")


def plain(html_text: str) -> str:
    return html_lib.unescape(TAG.sub(" ", html_text or ""))


def _index(table: Dict[str, List[Tuple[str, float]]]):
    by_stem: Dict[str, List[Tuple[str, float]]] = defaultdict(list)
    for genre, stems in table.items():
        for stem, weight in stems:
            by_stem[stem].append((genre, weight))
    return by_stem, sorted({len(s) for s in by_stem})


_TR = _index(TR_STEMS)
_EN = _index(EN_STEMS)


def _subject_hits(tokens: Iterable[str], english: bool) -> Tuple[Dict[str, float], Dict[str, Counter]]:
    by_stem, lengths = _EN if english else _TR
    score: Dict[str, float] = defaultdict(float)
    found: Dict[str, Counter] = defaultdict(Counter)
    for w in tokens:
        for n in lengths:
            if n > len(w):
                break
            stem = w[:n]
            if stem not in by_stem:
                continue
            rest = w[n:]
            if rest and not english and not suffix_chain(rest):
                continue
            if w.startswith(OTHER_WORDS.get(stem, ())):
                continue
            for genre, weight in by_stem[stem]:
                score[genre] += weight
                found[genre][stem] += 1
    return score, found


def translated_from(text: str) -> Optional[str]:
    """The language an imprint says the book was translated from: "Rusça"."""
    m = TRANSLATED_FROM.search(lower_tr(text or ""))
    if not m:
        return None
    lang = m.group("lang")
    return {"i": "İ", "ı": "I"}.get(lang[:1], lang[:1].upper()) + lang[1:]


def _russian_author(author: str) -> bool:
    names = [n for n in re.split(r"[\s,.]+", lower_tr(author or "")) if len(n) > 2]
    if not names:
        return False
    surname = names[-1]
    return surname in RUSSIAN_NAMES or any(n in RUSSIAN_NAMES for n in names) or bool(
        RUSSIAN_SURNAME.search(surname) and len(surname) > 4 and not re.search(r"[ğış]", surname))


def _spoken(text: str) -> bool:
    if not text.startswith(DIALOGUE_OPENERS):
        return False
    lowered = lower_tr(text)
    return (bool(SPEECH.search(lowered)) or text.count("—") >= 2 or text.count("–") >= 2
            or text.count('"') >= 4 or text.count("“") >= 2)


def _dialogue_share(paragraphs: Sequence[str]) -> float:
    """The share of paragraphs that are a line of speech; a list's dashes
    ("- birinci madde") are not."""
    texts = [p.strip() for p in paragraphs if len(p.strip()) >= 3]
    if len(texts) < 30:
        return 0.0
    return sum(1 for t in texts if _spoken(t)) / len(texts)


def _names_fiction(front_lower: str) -> Tuple[int, Optional[str]]:
    """2 for a genre named on its own line, 1 for a literary series."""
    lines = [re.sub(r"[^\wçğıöşüâîû ]", "", ln).strip() for ln in front_lower.splitlines()]
    for ln in lines:
        if FICTION_LINE.match(ln):
            return 2, ln
    for ln in lines:
        if SERIES_LINE.search(ln) and not NOT_FICTION_SERIES.search(ln) and len(ln) < 60:
            return 1, ln
    return 0, None


def subject_scores(title: str, bodies: Sequence[Tuple[str, str]], english: bool):
    """Each subject's score, best first: its weighted stems per thousand words
    of text, with the title's and the chapter titles' added on top."""
    body_text = " ".join(plain(h) for _, h in bodies)[:BODY_LIMIT]
    tokens = list(words(body_text))
    score, found = _subject_hits(tokens, english)
    per_thousand = {g: s * 1000 / max(len(tokens), 1) for g, s in score.items()}
    title_score, title_found = _subject_hits(words(title or ""), english)
    chapter_score, _ = _subject_hits(words(" ".join(t or "" for t, _ in bodies)), english)
    total = {g: per_thousand.get(g, 0) + 25 * title_score.get(g, 0) + min(40.0, 4 * chapter_score.get(g, 0))
             for g in set(per_thousand) | set(title_score) | set(chapter_score)}
    return sorted(total.items(), key=lambda kv: -kv[1]), found, title_found


def guess(title: str, author: str = "", chapters: Sequence[Tuple[str, str, str]] = (),
          imprint: Optional[dict] = None, language: str = "tr", front_text: str = "") -> Guess:
    """`chapters`: (title, html, kind) in order; `front_text`: the PDF's first
    and last pages as text (where an imprint says what the book is)."""
    imprint = imprint or {}
    english = (language or "").lower().startswith("en")
    bodies = [(t, h) for t, h, k in chapters if k == "chapter"]
    front = " ".join([front_text] + [plain(h) for t, h, k in chapters if k == "frontmatter"])
    front_lower = lower_tr(front)
    for name in re.split(r"\s+", lower_tr(author or "")):
        if len(name) > 2:
            front_lower = front_lower.replace(name, " ")

    ranked, found, title_found = subject_scores(title, bodies, english)

    # 1. fiction or not; a single sign of it is enough where no subject's
    # vocabulary stands out (a novel speaks of everything a little)
    paragraphs: List[str] = []
    for _, h in bodies:
        paragraphs.extend(plain(p) for p in re.split(r"</p>", h or ""))
    dialogue = _dialogue_share(paragraphs)
    named, named_line = _names_fiction(front_lower)
    scholarly = any(NONFICTION_CHAPTERS.match(t or "") for t, _, _ in chapters)
    fiction = named + (2 if dialogue >= 0.06 else 1 if dialogue >= 0.03 else 0) - (2 if scholarly else 0)
    weak_subject = not ranked or ranked[0][1] < WEAK_SUBJECT
    if fiction >= 2 or (fiction == 1 and weak_subject):
        why = []
        if named:
            why.append(f"ön sayfalarda “{named_line}”")
        if dialogue >= 0.03:
            why.append(f"paragrafların %{round(dialogue * 100)}'i konuşma")
        source = (imprint.get("source_language") or translated_from(front) or "").lower()
        if source.startswith("rus") or CYRILLIC.search(imprint.get("original_title") or "") or _russian_author(author):
            key, origin = "rus-edebiyati", "Rusça aslından" if source.startswith("rus") else "Rus yazar"
        elif source or imprint.get("translator") or english:
            key, origin = "dunya-edebiyati", f"{source.capitalize()} aslından" if source else "çeviri"
        else:
            key, origin = "turk-edebiyati", "çevirmen yok, Türkçe metin"
        return Guess(key, label(key), 0.8 if fiction >= 3 else 0.65, "; ".join(why + [origin]))

    # 2. subject
    ranked = [(g, s) for g, s in ranked
              if len(set(found.get(g, Counter())) | set(title_found.get(g, Counter()))) >= MIN_STEMS
              or title_found.get(g)]
    if not ranked or ranked[0][1] < MIN_SCORE:
        return Guess("diger", label("diger"), 0.5, "konusunu gösteren sözcükler az")
    top, top_score = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    confidence = top_score / (top_score + second) if top_score + second else 1.0
    words_seen = [s for s, _ in (title_found.get(top, Counter()) + found.get(top, Counter())).most_common(3)]
    return Guess(top, label(top), confidence, "en çok geçenler: " + ", ".join(words_seen))


def decide(local: Guess, online) -> Guess:
    """The local guess and what Wikidata said (app/genre_lookup.Found, or
    None) as one: the book's own entry wins; its author's, unless that only
    calls them a novelist while the book reads clearly as non-fiction; a
    plain writer leaves the reading to decide, giving a novel the writer's
    country."""
    if online is None:
        return local
    if online.key is None:
        if local.key in FICTION:
            from app.genre_lookup import _origin
            origin = _origin(online.description)
            if origin and origin != local.key:
                return Guess(origin, label(origin), local.confidence, f"{local.reason}; {online.reason}")
        return local
    if (online.level == "author" and online.fiction and local.key not in FICTION
            and local.key != "diger" and local.confidence >= 0.75):
        return local
    return Guess(online.key, label(online.key), 0.85, online.reason)


def front_pages_text(pdf_path: str, front: int = 4, back: int = 2) -> str:
    """The text of a PDF's first and last pages, where a book names itself."""
    import fitz

    try:
        doc = fitz.open(pdf_path)
    except Exception:  # noqa: BLE001
        return ""
    with doc:
        n = doc.page_count
        wanted = sorted(set(range(min(front, n))) | set(range(max(0, n - back), n)))
        return "\n".join(doc[i].get_text() for i in wanted)


def guess_session(session, front_text: str = "") -> Guess:
    return guess(session.book_title, session.author,
                 [(c.title, c.html, c.kind) for c in session.chapters],
                 session.imprint, session.language, front_text)


def scale(confidence: float) -> str:
    """How sure, in a word, for the workbench: "tahmin" or "zayıf tahmin"."""
    return "tahmin" if confidence >= 0.62 else "zayıf tahmin"
