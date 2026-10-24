"""Structural inspection of a built .epub, read from the zip itself.

Deliberately does not use ebooklib to read the file back. ebooklib is what
*wrote* it; asking it to describe its own output would hide exactly the
class of defect we care about (an item written to the manifest but not the
spine, a nav document polluted with entries that were never meant to be
there, XHTML that only parses because lxml is lenient). This reads the
container, the OPF and the XHTML directly.
"""

from __future__ import annotations

import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from lxml import etree

NS = {
    "c": "urn:oasis:names:tc:opendocument:xmlns:container",
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
    "x": "http://www.w3.org/1999/xhtml",
    "epub": "http://www.idpf.org/2007/ops",
    "ncx": "http://daisy.org/z3986/2005/ncx/",
}

_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class EpubInfo:
    ok: bool = True
    errors: List[str] = field(default_factory=list)
    language: Optional[str] = None
    title: Optional[str] = None
    creator: Optional[str] = None
    manifest_count: int = 0
    spine_count: int = 0
    spine_ids: List[str] = field(default_factory=list)
    xhtml_count: int = 0
    image_count: int = 0
    has_cover_image: bool = False
    cover_in_spine: bool = False
    nav_toc_entries: int = 0
    nav_toc_titles: List[str] = field(default_factory=list)
    nav_pagelist_entries: int = 0
    ncx_navpoints: int = 0
    xhtml_parse_errors: int = 0
    dangling_noterefs: int = 0
    duplicate_ids: int = 0
    footnote_asides: int = 0
    noteref_links: int = 0
    text_by_file: Dict[str, str] = field(default_factory=dict)
    nav_text: str = ""

    @property
    def plain_text(self) -> str:
        """Text of the book's content documents.

        The navigation document is deliberately excluded. Its text is a
        rendering of structure, not content: every chapter title in it is
        already present in the chapter it points at, so counting it inflates
        every content measure, and a generated page-list can add thousands
        of characters of element ids that were never words at all. Content
        loss has to be measured against what the reader actually reads.
        """
        return "\n".join(self.text_by_file[k] for k in sorted(self.text_by_file))


# Markup the converter writes rather than reads off the page: a note's
# marker is re-emitted as a span, the notes list gets a "Notlar" label and
# each note a "↩" backlink. None of the three is in any PDF. They are a
# rendering of structure, the same thing the navigation document is, and
# `plain_text` already excludes that for the same reason — except these move
# for a second reason the nav does not: re-filing a line from a footnote to
# a paragraph deletes a marker and, for the last note in a chapter, the
# label too, without changing one word of the book. Counted, that shows up
# as `epub_letters` falling by a few hundred, which is the one hard
# content-loss guard reporting a loss that did not happen. A hard guard that
# has to be waved through stops being a guard.
GENERATED_CHROME_CLASSES = {"footnote-marker", "footnote-title", "footnote-back"}


def _text_of(el) -> str:
    """Text a reader would read, with the converter's own furniture dropped."""
    out: List[str] = []

    def walk(node, with_tail: bool) -> None:
        if set((node.get("class") or "").split()) & GENERATED_CHROME_CLASSES:
            # The tail still belongs to the parent: it is the text printed
            # *after* this element, not part of it.
            if with_tail and node.tail:
                out.append(node.tail)
            return
        if node.text:
            out.append(node.text)
        for child in node:
            walk(child, True)
        if with_tail and node.tail:
            out.append(node.tail)

    walk(el, False)
    return "".join(out)


def inspect_epub(path: str) -> EpubInfo:
    info = EpubInfo()
    try:
        zf = zipfile.ZipFile(path)
    except Exception as exc:  # noqa: BLE001
        info.ok = False
        info.errors.append(f"cannot open zip: {exc}")
        return info

    with zf:
        names = set(zf.namelist())

        if "mimetype" not in names:
            info.errors.append("missing mimetype entry")
        try:
            container = etree.fromstring(zf.read("META-INF/container.xml"))
            opf_path = container.findall(".//c:rootfile", NS)[0].get("full-path")
        except Exception as exc:  # noqa: BLE001
            info.ok = False
            info.errors.append(f"cannot resolve OPF from container.xml: {exc}")
            return info

        base = posixpath.dirname(opf_path)

        def resolve(href: str) -> str:
            return posixpath.normpath(posixpath.join(base, href)) if base else href

        try:
            opf = etree.fromstring(zf.read(opf_path))
        except Exception as exc:  # noqa: BLE001
            info.ok = False
            info.errors.append(f"cannot parse OPF: {exc}")
            return info

        def meta_text(tag: str) -> Optional[str]:
            els = opf.findall(f".//dc:{tag}", NS)
            return _text_of(els[0]).strip() if els else None

        info.language = meta_text("language")
        info.title = meta_text("title")
        info.creator = meta_text("creator")

        manifest: Dict[str, dict] = {}
        nav_href = None
        for item in opf.findall(".//opf:manifest/opf:item", NS):
            iid = item.get("id")
            href = item.get("href")
            media = item.get("media-type") or ""
            props = (item.get("properties") or "").split()
            manifest[iid] = {"href": href, "media": media, "props": props}
            full = resolve(href)
            if full not in names:
                info.errors.append(f"manifest item missing from archive: {href}")
            if media.startswith("image/"):
                info.image_count += 1
                if "cover-image" in props:
                    info.has_cover_image = True
            if "nav" in props:
                nav_href = full
        info.manifest_count = len(manifest)

        # ebooklib writes the legacy <meta name="cover"> pointer too; either
        # signal counts as "this book has a cover".
        for m in opf.findall(".//opf:metadata/opf:meta", NS):
            if m.get("name") == "cover":
                info.has_cover_image = True

        cover_ids = {iid for iid, it in manifest.items()
                     if "cover" in (it["href"] or "").lower() and it["media"].startswith("application/xhtml")}

        for ref in opf.findall(".//opf:spine/opf:itemref", NS):
            idref = ref.get("idref")
            info.spine_ids.append(idref)
            if idref not in manifest:
                info.errors.append(f"spine references unknown manifest id: {idref}")
            if idref in cover_ids:
                info.cover_in_spine = True
        info.spine_count = len(info.spine_ids)

        parser = etree.XMLParser(resolve_entities=False, recover=False)
        all_ids = set()
        noterefs: List[str] = []
        for iid, it in sorted(manifest.items()):
            if not it["media"].startswith("application/xhtml"):
                continue
            full = resolve(it["href"])
            if full not in names:
                continue
            info.xhtml_count += 1
            raw = zf.read(full)
            try:
                tree = etree.fromstring(raw, parser)
            except Exception as exc:  # noqa: BLE001
                info.xhtml_parse_errors += 1
                info.errors.append(f"XHTML not well-formed: {it['href']}: {exc}")
                info.text_by_file[full] = _TAG_RE.sub(" ", raw.decode("utf-8", "replace"))
                continue

            body = tree.find(".//x:body", NS)
            text = _text_of(body if body is not None else tree)
            if full == nav_href:
                info.nav_text = text
            else:
                info.text_by_file[full] = text

            # Duplicate ids inside one document are invalid, and — worse —
            # they fail silently: the XHTML parses, the link resolves, and
            # the reader simply lands on the first note with that id every
            # time. Nothing else in this inspector can see that.
            seen_here = set()
            for el in tree.iter():
                eid = el.get("id")
                if eid:
                    if eid in seen_here:
                        info.duplicate_ids += 1
                    seen_here.add(eid)
                    all_ids.add(eid)
                etype = el.get("{http://www.idpf.org/2007/ops}type")
                if etype == "footnote":
                    info.footnote_asides += 1
                if etype == "noteref":
                    info.noteref_links += 1
                    href = el.get("href") or ""
                    if href.startswith("#"):
                        noterefs.append(href[1:])

            if nav_href and full == nav_href:
                for nav in tree.findall(".//x:nav", NS):
                    ntype = nav.get("{http://www.idpf.org/2007/ops}type")
                    links = nav.findall(".//x:a", NS)
                    if ntype == "toc":
                        info.nav_toc_entries = len(links)
                        info.nav_toc_titles = [_text_of(a).strip() for a in links]
                    elif ntype == "page-list":
                        info.nav_pagelist_entries = len(links)

        info.dangling_noterefs = sum(1 for t in noterefs if t not in all_ids)

        for iid, it in manifest.items():
            if it["media"] == "application/x-dtbncx+xml":
                try:
                    ncx = etree.fromstring(zf.read(resolve(it["href"])))
                    info.ncx_navpoints = len(ncx.findall(".//ncx:navPoint", NS))
                except Exception as exc:  # noqa: BLE001
                    info.errors.append(f"cannot parse NCX: {exc}")

    info.ok = info.xhtml_parse_errors == 0 and not any(
        e.startswith(("cannot", "manifest item missing", "spine references")) for e in info.errors
    )
    return info
