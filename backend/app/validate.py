"""Check a built EPUB before it goes to the Kindle.

Two questions, answered from the zip itself (not from the library that
wrote it, which would describe its own output kindly):

- Is it a valid EPUB 3? The container, the package document, the
  manifest and spine, well-formed XHTML, links and ids that resolve,
  images that exist, a navigation document. These are the faults
  EPUBCheck reports most and Kindle's own converter rejects or silently
  drops content over.
- Will a Kindle render it as meant? Kindle ignores or mishandles some CSS
  (viewport units, grid, multi-column, transitions), flattens navigation
  deeper than two levels, and limits what Send to Kindle accepts by size.

When Java and an EPUBCheck jar are present, EPUBCheck itself is run as
well and its messages are added. The jar: MATBAA_EPUBCHECK_JAR, any
epubcheck.jar under ~/.matbaa/epubcheck, or the `epubcheck` Python
package's. Java: MATBAA_JAVA, `java` on the PATH, or the runtime Kindle
Previewer ships with.
"""
from __future__ import annotations

import io
import json
import os
import posixpath
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional, Set
from urllib.parse import unquote

from lxml import etree

NS = {
    "c": "urn:oasis:names:tc:opendocument:xmlns:container",
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
    "x": "http://www.w3.org/1999/xhtml",
    "epub": "http://www.idpf.org/2007/ops",
}
SEND_TO_KINDLE_EMAIL_MB = 50
SEND_TO_KINDLE_WEB_MB = 200
KINDLE_NAV_DEPTH = 2
COVER_RECOMMENDED = (1600, 2560)
# CSS a Kindle ignores or renders wrongly (KDP publishing guidelines)
KINDLE_CSS = [
    (re.compile(r"\b\d+(\.\d+)?v[hw]\b"), "vh/vw birimleri Kindle'da desteklenmez"),
    (re.compile(r"display\s*:\s*grid"), "display: grid Kindle'da desteklenmez"),
    (re.compile(r"display\s*:\s*inline-block"), "display: inline-block Kindle'da tutarsız çalışır"),
    (re.compile(r"\bcolumn-(count|width)\s*:|\bcolumns\s*:"), "çok sütunlu düzen Kindle'da yok sayılır"),
    (re.compile(r"\b(transition|animation)\s*:"), "geçiş/animasyon Kindle'da yok sayılır"),
    (re.compile(r"position\s*:\s*fixed"), "position: fixed Kindle'da desteklenmez"),
]


@dataclass
class Finding:
    code: str
    severity: str        # "error" | "warning" | "info"
    message: str
    file: str = ""

    def to_dict(self) -> Dict:
        return asdict(self)


IMAGE_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF8", "image/gif"),
    (b"<svg", "image/svg+xml"),
)


def _add(out: List[Finding], code: str, severity: str, message: str, file: str = "") -> None:
    out.append(Finding(code, severity, message, file))


def _resolve(base: str, href: str) -> str:
    return posixpath.normpath(posixpath.join(posixpath.dirname(base), unquote(href)))


def _nav_depth(ol, depth: int = 1) -> int:
    deepest = depth
    for li in ol.findall("x:li", NS):
        for sub in li.findall("x:ol", NS):
            deepest = max(deepest, _nav_depth(sub, depth + 1))
    return deepest


def check_epub(path: str) -> List[Finding]:
    out: List[Finding] = []
    size_mb = os.path.getsize(path) / 1e6
    if size_mb > SEND_TO_KINDLE_WEB_MB:
        _add(out, "size", "error", f"EPUB {size_mb:.0f} MB; Kindle'a gönderme sınırı {SEND_TO_KINDLE_WEB_MB} MB.")
    elif size_mb > SEND_TO_KINDLE_EMAIL_MB:
        _add(out, "size", "warning",
             f"EPUB {size_mb:.0f} MB; e-postayla Kindle'a gönderme sınırı {SEND_TO_KINDLE_EMAIL_MB} MB "
             "(web yükleyici 200 MB'a kadar kabul eder).")
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        _add(out, "zip", "error", "Dosya geçerli bir ZIP/EPUB değil.")
        return out
    names = z.namelist()
    infos = z.infolist()

    # --- container ---------------------------------------------------------
    if not infos or infos[0].filename != "mimetype":
        _add(out, "mimetype-first", "error", "mimetype dosyası arşivin ilk dosyası değil.")
    elif infos[0].compress_type != zipfile.ZIP_STORED:
        _add(out, "mimetype-stored", "error", "mimetype dosyası sıkıştırılmış; sıkıştırmasız olmalı.")
    elif z.read("mimetype").strip() != b"application/epub+zip":
        _add(out, "mimetype-value", "error", "mimetype içeriği application/epub+zip değil.")
    try:
        container = etree.fromstring(z.read("META-INF/container.xml"))
        opf_path = container.find(".//c:rootfile", NS).get("full-path")
        opf = etree.fromstring(z.read(opf_path))
    except Exception as exc:  # noqa: BLE001
        _add(out, "container", "error", f"Paket belgesi okunamadı: {exc}")
        return out

    # --- package metadata -------------------------------------------------------
    for tag, label in (("identifier", "tanımlayıcı"), ("title", "başlık"), ("language", "dil")):
        el = opf.find(f".//dc:{tag}", NS)
        if el is None or not (el.text or "").strip():
            _add(out, f"meta-{tag}", "error", f"Kitap bilgilerinde {label} (dc:{tag}) yok.", opf_path)
    if opf.find(".//opf:meta[@property='dcterms:modified']", NS) is None:
        _add(out, "meta-modified", "error", "dcterms:modified tarihi yok (EPUB 3 zorunlu).", opf_path)
    if opf.find(".//opf:meta[@property='schema:accessMode']", NS) is None:
        _add(out, "a11y-metadata", "info", "Erişilebilirlik üstverisi (schema:accessMode vb.) yok.", opf_path)
    title = (opf.findtext(".//dc:title", default="", namespaces=NS) or "").strip()
    if title in ("Untitled Book", ""):
        _add(out, "meta-untitled", "warning", "Kitabın adı girilmemiş; Kindle kitaplığında 'Untitled Book' görünecek.")
    creator = (opf.findtext(".//dc:creator", default="", namespaces=NS) or "").strip()
    if creator in ("Unknown", ""):
        _add(out, "meta-author", "info", "Yazar adı girilmemiş.")

    # --- manifest ------------------------------------------------------------------
    manifest: Dict[str, Dict[str, str]] = {}
    hrefs: Set[str] = set()
    for item in opf.findall(".//opf:manifest/opf:item", NS):
        iid, href = item.get("id"), item.get("href")
        full = _resolve(opf_path, href or "")
        if iid in manifest:
            _add(out, "manifest-dup-id", "error", f"Manifestte aynı kimlik iki kez: {iid}", opf_path)
        manifest[iid] = {"href": full, "type": item.get("media-type", ""), "props": item.get("properties", "")}
        hrefs.add(full)
        if full not in names:
            _add(out, "manifest-missing", "error", f"Manifestteki dosya arşivde yok: {full}", opf_path)
    for name in names:
        if name in ("mimetype", opf_path) or name.startswith("META-INF/") or name.endswith("/"):
            continue
        if name not in hrefs:
            _add(out, "manifest-unlisted", "warning", f"Arşivde manifestte olmayan dosya: {name}")
    if not any("nav" in m["props"].split() for m in manifest.values()):
        _add(out, "nav-missing", "error", "Gezinme belgesi (nav) yok.", opf_path)
    # An image declared as one format and stored as another: Amazon's
    # converter rejects the whole book over it, with no message.
    for m in manifest.values():
        if not m["type"].startswith("image/") or m["href"] not in names:
            continue
        head = z.read(m["href"])[:8]
        actual = next((t for magic, t in IMAGE_MAGIC if head.startswith(magic)), None)
        if actual and actual != m["type"]:
            _add(out, "image-type", "error",
                 f"Resim {m['type']} diye bildirilmiş ama aslında {actual}: {m['href']}", opf_path)

    # --- spine ------------------------------------------------------------------------
    itemrefs = opf.findall(".//opf:spine/opf:itemref", NS)
    spine = [i.get("idref") for i in itemrefs]
    non_linear = [i.get("idref") for i in itemrefs if i.get("linear") == "no"]
    if not spine:
        _add(out, "spine-empty", "error", "Okuma sırası (spine) boş.", opf_path)
    for idref in spine:
        if idref not in manifest:
            _add(out, "spine-unknown", "error", f"Okuma sırasında manifestte olmayan öğe: {idref}", opf_path)
        elif manifest[idref]["type"] != "application/xhtml+xml":
            _add(out, "spine-type", "error", f"Okuma sırasında XHTML olmayan öğe: {idref}", opf_path)

    # --- content documents ------------------------------------------------------------
    docs: Dict[str, etree._Element] = {}
    ids_by_doc: Dict[str, Set[str]] = {}
    for m in manifest.values():
        if m["type"] != "application/xhtml+xml" or m["href"] not in names:
            continue
        try:
            root = etree.fromstring(z.read(m["href"]))  # strict: no recovery
        except etree.XMLSyntaxError as exc:
            _add(out, "xhtml-malformed", "error", f"XHTML iyi biçimli değil: {exc}", m["href"])
            continue
        docs[m["href"]] = root
        ids = [el.get("id") for el in root.iter() if el.get("id")]
        seen: Set[str] = set()
        for i in ids:
            if i in seen:
                _add(out, "xhtml-dup-id", "error", f"Aynı kimlik iki kez: {i}", m["href"])
            seen.add(i)
        ids_by_doc[m["href"]] = seen

    linked: Set[str] = set()
    for doc_path, root in docs.items():
        for a in root.iter("{%s}a" % NS["x"]):
            href = a.get("href")
            if not href or re.match(r"^[a-z]+:", href):
                continue
            target, _, frag = href.partition("#")
            target_path = _resolve(doc_path, target) if target else doc_path
            if target_path != doc_path:
                linked.add(target_path)
            if target_path not in docs:
                _add(out, "link-file", "error", f"Bağlantı var olmayan dosyaya gidiyor: {href}", doc_path)
            elif frag and frag not in ids_by_doc.get(target_path, set()):
                _add(out, "link-id", "error", f"Bağlantı var olmayan bir yere gidiyor: {href}", doc_path)
        for img in root.iter("{%s}img" % NS["x"]):
            src = img.get("src") or ""
            if not src.startswith("data:") and _resolve(doc_path, src) not in hrefs:
                _add(out, "img-missing", "error", f"Resim dosyası yok: {src}", doc_path)
            if img.get("alt") is None:
                _add(out, "img-alt", "info", f"Resimde alt metin yok: {src}", doc_path)

    # A page taken out of the reading order must be reachable by a link, or
    # no reader can get to it (EPUBCheck OPF-096) — Amazon's converter
    # holds a book to EPUBCheck.
    for idref in non_linear:
        if idref in manifest and manifest[idref]["href"] not in linked:
            _add(out, "spine-unreachable", "error",
                 f"Okuma sırası dışındaki sayfaya hiçbir bağlantı yok: {manifest[idref]['href']}", opf_path)

    # --- navigation -------------------------------------------------------------------
    nav_path = next((m["href"] for m in manifest.values() if "nav" in m["props"].split()), None)
    nav = docs.get(nav_path) if nav_path else None
    if nav is not None:
        toc = next((n for n in nav.iter("{%s}nav" % NS["x"])
                    if n.get("{%s}type" % NS["epub"]) == "toc"), None)
        if toc is None:
            _add(out, "nav-toc", "error", "Gezinme belgesinde içindekiler (toc) yok.", nav_path)
        else:
            ol = toc.find("x:ol", NS)
            if ol is not None and _nav_depth(ol) > KINDLE_NAV_DEPTH:
                _add(out, "nav-depth", "warning",
                     f"İçindekiler {_nav_depth(ol)} düzey derin; Kindle en fazla {KINDLE_NAV_DEPTH} düzey gösterir.",
                     nav_path)

    # --- Kindle CSS ---------------------------------------------------------------------
    for m in manifest.values():
        if m["type"] != "text/css" or m["href"] not in names:
            continue
        css = re.sub(r"/\*.*?\*/", "", z.read(m["href"]).decode("utf-8", "replace"), flags=re.S)
        for pattern, why in KINDLE_CSS:
            if pattern.search(css):
                _add(out, "kindle-css", "warning", why, m["href"])

    # --- cover ------------------------------------------------------------------------------
    cover = next((m for m in manifest.values() if "cover-image" in m["props"].split()), None)
    if cover is None:
        _add(out, "cover-missing", "warning", "Kapak resmi yok; Kindle kitaplığında boş kapak görünecek.")
    elif cover["href"] in names:
        try:
            from PIL import Image
            w, h = Image.open(io.BytesIO(z.read(cover["href"]))).size
            if w < COVER_RECOMMENDED[0] * 0.5 or h < COVER_RECOMMENDED[1] * 0.5:
                _add(out, "cover-small", "info",
                     f"Kapak {w}×{h} piksel; Kindle için önerilen {COVER_RECOMMENDED[0]}×{COVER_RECOMMENDED[1]}.")
        except Exception:  # noqa: BLE001
            pass

    out.extend(_run_epubcheck(path))
    return out


def _epubcheck_jar() -> Optional[str]:
    jar = os.environ.get("MATBAA_EPUBCHECK_JAR")
    if jar and os.path.exists(jar):
        return jar
    for root, _dirs, files in os.walk(os.path.join(os.path.expanduser("~"), ".matbaa", "epubcheck")):
        if "epubcheck.jar" in files:
            return os.path.join(root, "epubcheck.jar")
    try:
        import epubcheck  # type: ignore
        base = os.path.dirname(epubcheck.__file__)
        for root, _dirs, files in os.walk(base):
            for f in files:
                if f == "epubcheck.jar":
                    return os.path.join(root, f)
    except ImportError:
        pass
    return None


def _java() -> Optional[str]:
    candidates = [os.environ.get("MATBAA_JAVA"), shutil.which("java")]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(os.path.join(local, "Amazon", "Kindle Previewer 3", "lib", "fc", "jre", "bin", "java.exe"))
    return next((c for c in candidates if c and os.path.exists(c)), None)


def _run_epubcheck(path: str) -> List[Finding]:
    java, jar = _java(), _epubcheck_jar()
    if not java or not jar:
        return []
    report = os.path.join(tempfile.mkdtemp(), "report.json")
    try:
        subprocess.run([java, "-jar", jar, path, "--json", report], capture_output=True, timeout=300)
        data = json.load(open(report, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    out = []
    for msg in data.get("messages", []):
        sev = {"FATAL": "error", "ERROR": "error", "WARNING": "warning"}.get(msg.get("severity"), "info")
        loc = (msg.get("locations") or [{}])[0].get("path", "")
        out.append(Finding("epubcheck-" + msg.get("ID", ""), sev, msg.get("message", ""), loc))
    return out


def summary(findings: List[Finding]) -> Dict:
    count = {s: sum(1 for f in findings if f.severity == s) for s in ("error", "warning", "info")}
    return {"valid": count["error"] == 0, "counts": count,
            "epubcheck": any(f.code.startswith("epubcheck-") for f in findings)}
