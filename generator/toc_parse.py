"""Reconstruct an edition's song list from a generated PDF's Table of Contents.

Historical songbooks predate the JSON manifest (and carry no native PDF outline),
so their song list can only be recovered from the *rendered* TOC page text. Each
TOC entry reads ``<difficulty glyph> <short title><optional marker><postfix>``
followed by a page number on the next line. We only need the *set* of titles, so
ordering and page numbers are ignored — which also sidesteps multi-column
text-extraction ordering quirks.
"""

import logging
import re
from typing import Any, Optional

import fitz

from .common.config import get_settings
from .worker.toc import difficulty_symbol

# Unicode categories for trailing "marker" characters to strip from a TOC entry:
# symbols/emoji (So, Sk) and format joiners / variation selectors (Cf). Song
# titles never legitimately end in these, but historical editions appended
# themed postfixes we don't have config for, so strip them generically.
_ASCII_ALNUM = re.compile(r"[A-Za-z0-9]")

logger = logging.getLogger(__name__)

# Glyphs that prefix every TOC entry (difficulty bins 1-5); see difficulty_symbol.
DIFFICULTY_GLYPHS = "".join(difficulty_symbol(b) for b in range(1, 6))
_HEADER = "table of contents"
_ELLIPSES = ("...", "…")


def _is_themed_marker(ch: str) -> bool:
    """True for the exotic glyphs historical editions append as themed postfixes.

    Covers emoji / supplementary symbols (codepoint >= U+1F000) and the Greek
    Extended block (U+1F00-U+1FFF), where observed markers like ``Ἴ``/``Ἳ`` live.
    Deliberately excludes BMP symbols (♥ ★ ♪) and the difficulty glyphs (U+25xx)
    so legitimate title characters are left alone.
    """
    o = ord(ch)
    return o >= 0x1F000 or 0x1F00 <= o <= 0x1FFF


def find_toc_pages(
    doc: "fitz.Document",
    page_indices: Optional[dict[str, Any]] = None,
    scan_pages: int = 10,
) -> list[int]:
    """Return the 0-based indices of the PDF's TOC pages.

    Prefers ``page_indices.table_of_contents`` (1-based, from the manifest) when
    available; otherwise scans the first ``scan_pages`` and returns the pages
    that carry difficulty-glyph entry lines (falling back to pages bearing the
    "Table of Contents" header for editions rendered without difficulty glyphs).
    """
    if page_indices:
        toc = page_indices.get("table_of_contents") or {}
        first, last = toc.get("first_page"), toc.get("last_page")
        if first and last:
            return list(range(first - 1, last))

    glyph_pages: list[int] = []
    header_pages: list[int] = []
    for i in range(min(scan_pages, doc.page_count)):
        lines = [ln.strip() for ln in doc.load_page(i).get_text().splitlines()]
        if any(ln[:1] in DIFFICULTY_GLYPHS for ln in lines if ln):
            glyph_pages.append(i)
        elif any(_HEADER in ln.lower() for ln in lines if ln):
            header_pages.append(i)
    return glyph_pages or header_pages


def _clean_entry(text: str, postfixes: list[str]) -> str:
    """Reduce a raw TOC entry to a clean (shortened) song title.

    The leading difficulty glyph is stripped by the caller. Here we:
    1. Cut everything from the first themed-marker glyph onward — this removes
       trailing postfixes like ``Ἴ`` and the page number that can render glued to
       them (e.g. ``- John Lennon, Yoko Ono Ἴ104`` -> ``- John Lennon, Yoko Ono``).
    2. Strip trailing truncation ellipses, the WIP ``*`` marker, configured
       postfixes, and short non-ASCII decorative tokens, in any combination.
    Note: a page number glued on *without* a marker (e.g. ``- Ramones172``) is
    left intact here; the caller's prefix matching tolerates that trailing junk.
    """
    text = text.strip()
    for i, ch in enumerate(text):
        if _is_themed_marker(ch):
            text = text[:i].rstrip()
            break
    changed = True
    while changed:
        changed = False
        for suf in _ELLIPSES:
            if text.endswith(suf):
                text = text[: -len(suf)].rstrip()
                changed = True
        if text.endswith("*"):
            text = text[:-1].rstrip()
            changed = True
        for p in postfixes:
            if p and text.endswith(p):
                text = text[: -len(p)].rstrip()
                changed = True
        head, _, last = text.rpartition(" ")
        if head and 0 < len(last) <= 2 and not _ASCII_ALNUM.search(last):
            text = head.rstrip()
            changed = True
    return text.strip()


def extract_songs_from_lines(lines: list[str], postfixes: list[str]) -> list[str]:
    """Pure line classifier: turn raw TOC text lines into cleaned song titles.

    A glyph-prefixed line is an entry; a glyph-less "Title - Artist" line is also
    taken (covers songs with no difficulty assigned and editions rendered without
    glyphs). Header, page-number and dot-leader lines are ignored. Result is
    de-duplicated, order-preserving.
    """
    seen: set[str] = set()
    out: list[str] = []
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if s[0] in DIFFICULTY_GLYPHS:
            title = _clean_entry(s[1:], postfixes)
        elif _HEADER not in s.lower() and " - " in s:
            title = _clean_entry(s, postfixes)
        else:
            continue
        if title and title not in seen:
            seen.add(title)
            out.append(title)
    return out


def parse_toc_songs(
    doc: "fitz.Document",
    page_indices: Optional[dict[str, Any]] = None,
    toc_config: Any = None,
) -> list[str]:
    """Extract the de-duplicated list of song titles from a PDF's TOC pages.

    Titles are cleaned (no difficulty glyph, WIP marker, or postfix) but remain
    in the *shortened* form the TOC renders.
    """
    config = toc_config or get_settings().toc
    postfixes = [
        badge.text.strip()
        for decoration in (config.decorations or [])
        for badge in decoration.badges
        if badge.text
    ]

    lines: list[str] = []
    for i in find_toc_pages(doc, page_indices):
        lines.extend(doc.load_page(i).get_text().splitlines())
    return extract_songs_from_lines(lines, postfixes)
