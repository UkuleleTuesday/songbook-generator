"""PPTX generation for song presentations.

Generates a PowerPoint presentation from a song's text content, using a style
matching the Ukulele Tuesday template: black background, circular content area
with a blue (#38B6FF) border, and white Open Sans text.
"""

import re
from pathlib import Path
from typing import List, Optional

from lxml import etree
from pptx import Presentation
from pptx.util import Emu

# ── Slide dimensions (matches the Love_Me_Do.pptx template) ──────────────────
_SLIDE_WIDTH = Emu(13716000)
_SLIDE_HEIGHT = Emu(10287000)

# ── XML namespaces ────────────────────────────────────────────────────────────
_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
_XML_NS = "http://www.w3.org/XML/1998/namespace"

_nsmap = {
    "a": _A_NS,
    "p": _P_NS,
}


def _a(tag: str) -> str:
    return f"{{{_A_NS}}}{tag}"


def _p(tag: str) -> str:
    return f"{{{_P_NS}}}{tag}"


# ── Circle geometry constants (child-coordinate space 812800×812800) ──────────
_CIRCLE_SIZE = 812800
_CIRCLE_R = _CIRCLE_SIZE // 2  # 406400 – radius
# Bezier control points for a circle (kappa ≈ 0.5523)
_K = 181951  # ≈ 406400 * (1 - 0.5523)

# ── Text-box child-coordinate offsets ────────────────────────────────────────
_TB_X = 76200
_TB_Y = -9525
_TB_W = 660400
_TB_H = 746125
_TB_MARGIN = 50800

# ── Group position / size on the slide ───────────────────────────────────────
_GROUP_LEFT = 1714500
_GROUP_TOP = 0
_GROUP_SIZE = 10287000  # width == height (square)

# ── Typography ────────────────────────────────────────────────────────────────
_FONT_REGULAR = "Open Sans"
_FONT_BOLD = "Open Sans Bold"
_FONT_SIZE = "4899"  # hundredths of a point (≈ 48.99 pt)
_LINE_SPACING = "6859"  # hundredths of a point
_TEXT_COLOR = "FFFFFF"
_BG_COLOR = "000000"
_BORDER_COLOR = "38B6FF"
_BORDER_WIDTH = 38100  # EMU


# ─────────────────────────────────────────────────────────────────────────────
# Public helpers
# ─────────────────────────────────────────────────────────────────────────────


def parse_sections(text: str) -> List[List[str]]:
    """Parse song plain-text into a list of sections.

    A section is a block of consecutive non-blank lines.  Sections are
    separated by one or more blank lines.

    Args:
        text: Plain-text content of the Google Doc.

    Returns:
        List of sections; each section is a list of (non-empty) line strings.
    """
    raw_sections = re.split(r"\n[ \t]*\n", text.strip())
    sections: List[List[str]] = []
    for raw in raw_sections:
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        if lines:
            sections.append(lines)
    return sections


def generate_song_pptx(
    song_name: str,
    text: str,
    output_path: Path,
) -> None:
    """Generate a PPTX presentation for a song and write it to *output_path*.

    Args:
        song_name: Song title (used as the bold heading on the first slide).
        text: Plain-text song content (chords + lyrics), exported from Google
            Docs.  Sections are separated by blank lines.
        output_path: Destination path for the generated ``.pptx`` file.
    """
    sections = parse_sections(text)

    prs = Presentation()
    prs.slide_width = _SLIDE_WIDTH
    prs.slide_height = _SLIDE_HEIGHT

    # Use the blank slide layout (index 6 in the built-in layouts)
    blank_layout = prs.slide_layouts[6]

    for idx, section_lines in enumerate(sections):
        slide = prs.slides.add_slide(blank_layout)
        title = song_name if idx == 0 else None
        _populate_slide(slide, title=title, lines=section_lines)

    # If no sections were found (empty document), create a single title slide
    if not sections:
        slide = prs.slides.add_slide(blank_layout)
        _populate_slide(slide, title=song_name, lines=[])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(output_path))


# ─────────────────────────────────────────────────────────────────────────────
# Private slide-building helpers
# ─────────────────────────────────────────────────────────────────────────────


def _populate_slide(slide, title: Optional[str], lines: List[str]) -> None:
    """Fill *slide* with a black background and a circle text area."""
    _set_black_background(slide)
    _clear_placeholder_shapes(slide)
    _add_group_shape(slide, title=title, lines=lines)


def _set_black_background(slide) -> None:
    """Set the slide background to solid black."""
    # Access the slide XML's <p:cSld> element
    cSld = slide._element.find(_p("cSld"))
    bg = etree.SubElement(cSld, _p("bg"))
    bgPr = etree.SubElement(bg, _p("bgPr"))
    solidFill = etree.SubElement(bgPr, _a("solidFill"))
    srgbClr = etree.SubElement(solidFill, _a("srgbClr"))
    srgbClr.set("val", _BG_COLOR)
    # Move bg before spTree (if spTree already exists)
    spTree = cSld.find(_p("spTree"))
    if spTree is not None:
        cSld.remove(bg)
        spTree.addprevious(bg)


def _clear_placeholder_shapes(slide) -> None:
    """Remove any placeholder shapes from the blank layout."""
    spTree = slide.shapes._spTree
    # Remove all <p:sp> children (placeholders) but keep nvGrpSpPr / grpSpPr
    for sp in spTree.findall(_p("sp")):
        spTree.remove(sp)


def _add_group_shape(slide, title: Optional[str], lines: List[str]) -> None:
    """Add the group containing the circle and text box to the slide."""
    spTree = slide.shapes._spTree

    grpSp = etree.SubElement(spTree, _p("grpSp"))

    # Non-visual properties
    nvGrpSpPr = etree.SubElement(grpSp, _p("nvGrpSpPr"))
    cNvPr = etree.SubElement(nvGrpSpPr, _p("cNvPr"))
    cNvPr.set("name", "Group 2")
    cNvPr.set("id", "2")
    etree.SubElement(nvGrpSpPr, _p("cNvGrpSpPr"))
    etree.SubElement(nvGrpSpPr, _p("nvPr"))

    # Group transform: maps child coords (0‥812800) → slide position
    grpSpPr = etree.SubElement(grpSp, _p("grpSpPr"))
    xfrm = etree.SubElement(grpSpPr, _a("xfrm"))
    xfrm.set("rot", "0")
    off = etree.SubElement(xfrm, _a("off"))
    off.set("x", str(_GROUP_LEFT))
    off.set("y", str(_GROUP_TOP))
    ext = etree.SubElement(xfrm, _a("ext"))
    ext.set("cx", str(_GROUP_SIZE))
    ext.set("cy", str(_GROUP_SIZE))
    chOff = etree.SubElement(xfrm, _a("chOff"))
    chOff.set("x", "0")
    chOff.set("y", "0")
    chExt = etree.SubElement(xfrm, _a("chExt"))
    chExt.set("cx", str(_CIRCLE_SIZE))
    chExt.set("cy", str(_CIRCLE_SIZE))

    grpSp.append(_make_circle_shape())
    grpSp.append(_make_text_box(title=title, lines=lines))


def _make_circle_shape() -> etree._Element:
    """Build the black filled circle with a blue border."""
    sp = etree.Element(_p("sp"))

    nvSpPr = etree.SubElement(sp, _p("nvSpPr"))
    cNvPr = etree.SubElement(nvSpPr, _p("cNvPr"))
    cNvPr.set("name", "Freeform 3")
    cNvPr.set("id", "3")
    etree.SubElement(nvSpPr, _p("cNvSpPr"))
    etree.SubElement(nvSpPr, _p("nvPr"))

    spPr = etree.SubElement(sp, _p("spPr"))

    xfrm = etree.SubElement(spPr, _a("xfrm"))
    xfrm.set("flipH", "false")
    xfrm.set("flipV", "false")
    xfrm.set("rot", "0")
    off = etree.SubElement(xfrm, _a("off"))
    off.set("x", "0")
    off.set("y", "0")
    ext = etree.SubElement(xfrm, _a("ext"))
    ext.set("cx", str(_CIRCLE_SIZE))
    ext.set("cy", str(_CIRCLE_SIZE))

    # Custom circle geometry (four cubic Bézier curves)
    custGeom = etree.SubElement(spPr, _a("custGeom"))
    etree.SubElement(custGeom, _a("avLst"))
    etree.SubElement(custGeom, _a("gdLst"))
    etree.SubElement(custGeom, _a("ahLst"))
    etree.SubElement(custGeom, _a("cxnLst"))
    rect = etree.SubElement(custGeom, _a("rect"))
    rect.set("r", "r")
    rect.set("b", "b")
    rect.set("t", "t")
    rect.set("l", "l")
    pathLst = etree.SubElement(custGeom, _a("pathLst"))
    path = etree.SubElement(pathLst, _a("path"))
    path.set("h", str(_CIRCLE_SIZE))
    path.set("w", str(_CIRCLE_SIZE))

    def _pt(x: int, y: int) -> etree._Element:
        pt = etree.Element(_a("pt"))
        pt.set("x", str(x))
        pt.set("y", str(y))
        return pt

    def _moveTo(x: int, y: int) -> etree._Element:
        mt = etree.Element(_a("moveTo"))
        mt.append(_pt(x, y))
        return mt

    def _cubicBezTo(*coords) -> etree._Element:
        cb = etree.Element(_a("cubicBezTo"))
        for x, y in coords:
            cb.append(_pt(x, y))
        return cb

    r = _CIRCLE_R  # 406400
    k = _K  # 181951

    path.append(_moveTo(r, 0))
    path.append(_cubicBezTo((k, 0), (0, k), (0, r)))
    path.append(_cubicBezTo((0, r + (r - k)), (k, _CIRCLE_SIZE), (r, _CIRCLE_SIZE)))
    path.append(
        _cubicBezTo(
            (r + (r - k), _CIRCLE_SIZE),
            (_CIRCLE_SIZE, r + (r - k)),
            (_CIRCLE_SIZE, r),
        )
    )
    path.append(_cubicBezTo((_CIRCLE_SIZE, k), (r + (r - k), 0), (r, 0)))
    etree.SubElement(path, _a("close"))

    # Black fill
    solidFill = etree.SubElement(spPr, _a("solidFill"))
    srgbClr = etree.SubElement(solidFill, _a("srgbClr"))
    srgbClr.set("val", _BG_COLOR)

    # Blue border
    ln = etree.SubElement(spPr, _a("ln"))
    ln.set("w", str(_BORDER_WIDTH))
    ln.set("cap", "sq")
    borderFill = etree.SubElement(ln, _a("solidFill"))
    borderClr = etree.SubElement(borderFill, _a("srgbClr"))
    borderClr.set("val", _BORDER_COLOR)
    prstDash = etree.SubElement(ln, _a("prstDash"))
    prstDash.set("val", "solid")
    etree.SubElement(ln, _a("miter"))

    return sp


def _make_text_box(title: Optional[str], lines: List[str]) -> etree._Element:
    """Build the text box containing the slide content."""
    sp = etree.Element(_p("sp"))

    nvSpPr = etree.SubElement(sp, _p("nvSpPr"))
    cNvPr = etree.SubElement(nvSpPr, _p("cNvPr"))
    cNvPr.set("name", "TextBox 4")
    cNvPr.set("id", "4")
    cNvSpPr = etree.SubElement(nvSpPr, _p("cNvSpPr"))
    cNvSpPr.set("txBox", "true")
    etree.SubElement(nvSpPr, _p("nvPr"))

    spPr = etree.SubElement(sp, _p("spPr"))
    xfrm = etree.SubElement(spPr, _a("xfrm"))
    off = etree.SubElement(xfrm, _a("off"))
    off.set("x", str(_TB_X))
    off.set("y", str(_TB_Y))
    ext = etree.SubElement(xfrm, _a("ext"))
    ext.set("cx", str(_TB_W))
    ext.set("cy", str(_TB_H))
    prstGeom = etree.SubElement(spPr, _a("prstGeom"))
    prstGeom.set("prst", "rect")
    etree.SubElement(prstGeom, _a("avLst"))

    txBody = etree.SubElement(sp, _p("txBody"))
    bodyPr = etree.SubElement(txBody, _a("bodyPr"))
    bodyPr.set("anchor", "ctr")
    bodyPr.set("rtlCol", "false")
    bodyPr.set("tIns", str(_TB_MARGIN))
    bodyPr.set("lIns", str(_TB_MARGIN))
    bodyPr.set("bIns", str(_TB_MARGIN))
    bodyPr.set("rIns", str(_TB_MARGIN))
    etree.SubElement(txBody, _a("lstStyle"))

    if title is not None:
        txBody.append(_make_paragraph(text=title, bold=True))
        txBody.append(_make_paragraph(text="  "))

    for line in lines:
        txBody.append(_make_paragraph(text=line, spc_bef_zero=True))

    # Ensure txBody has at least one paragraph (required by the spec)
    if txBody.find(_a("p")) is None:
        txBody.append(_make_paragraph(text="", spc_bef_zero=True))

    return sp


def _make_paragraph(
    text: str = "",
    bold: bool = False,
    spc_bef_zero: bool = False,
) -> etree._Element:
    """Build a ``<a:p>`` element with the given text and formatting."""
    font = _FONT_BOLD if bold else _FONT_REGULAR

    p = etree.Element(_a("p"))

    pPr = etree.SubElement(p, _a("pPr"))
    pPr.set("algn", "ctr")

    lnSpc = etree.SubElement(pPr, _a("lnSpc"))
    spcPts = etree.SubElement(lnSpc, _a("spcPts"))
    spcPts.set("val", _LINE_SPACING)

    if spc_bef_zero:
        spcBef = etree.SubElement(pPr, _a("spcBef"))
        spcPct = etree.SubElement(spcBef, _a("spcPct"))
        spcPct.set("val", "0")

    if text:
        r = etree.SubElement(p, _a("r"))

        rPr = etree.SubElement(r, _a("rPr"))
        rPr.set("lang", "en-US")
        rPr.set("sz", _FONT_SIZE)
        if bold:
            rPr.set("b", "true")

        solidFill = etree.SubElement(rPr, _a("solidFill"))
        srgbClr = etree.SubElement(solidFill, _a("srgbClr"))
        srgbClr.set("val", _TEXT_COLOR)

        for tag in ("latin", "ea", "cs", "sym"):
            elem = etree.SubElement(rPr, _a(tag))
            elem.set("typeface", font)

        t = etree.SubElement(r, _a("t"))
        t.set(f"{{{_XML_NS}}}space", "preserve")
        t.text = text

    return p
