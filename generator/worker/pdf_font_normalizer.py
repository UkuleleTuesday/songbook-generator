import logging
import re
from typing import Dict

import fitz

from generator.common.fonts import find_font_path

logger = logging.getLogger(__name__)

# Regex to find the base name of a subset font, e.g., "ABCDEF+Verdana-Bold" -> "Verdana-Bold"
SUBSET_FONT_RE = re.compile(r"^[A-Z]{6}\+(.*)")


def normalize_pdf_fonts(pdf_bytes: bytes) -> bytes:
    """
    Replaces subset fonts in a PDF with their full font files.

    Args:
        pdf_bytes: The original PDF content as bytes.

    Returns:
        The processed PDF content as bytes, or the original bytes if no changes were made.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    if not doc.is_pdf or doc.page_count == 0:
        return pdf_bytes

    # A map of {old_xref: new_xref} for font replacement
    font_xref_map: Dict[int, int] = {}
    # A map of {base_font_name: new_xref} to avoid re-embedding the same font
    embedded_fonts: Dict[str, int] = {}

    # Check fonts on all pages as they can differ
    for page in doc:
        fonts_on_page = page.get_fonts(full=True)
        for font in fonts_on_page:
            xref, _, name, _, _, _ = font
            # Already processed this font xref
            if xref in font_xref_map:
                continue

            try:
                # Use 'ignore' for robustness against malformed font names
                name_str = name.decode("utf-8", "ignore")
            except (UnicodeDecodeError, AttributeError):
                continue

            match = SUBSET_FONT_RE.match(name_str)
            if not match:
                continue

            base_font_name = match.group(1)
            logger.debug("Found subset font: %s (base: %s)", name_str, base_font_name)

            if base_font_name in embedded_fonts:
                # Already embedded this full font, just map the old xref to the new one
                font_xref_map[xref] = embedded_fonts[base_font_name]
                continue

            font_path = find_font_path(base_font_name)
            if not font_path:
                logger.warning(
                    "No full font file found for '%s'. Skipping normalization for this font.",
                    base_font_name,
                )
                continue

            try:
                # Embed the full font. Use `fontname` to ensure it's stored with a clean name.
                new_xref = doc.embed_font(fontfile=font_path, fontname=base_font_name)
                font_xref_map[xref] = new_xref
                embedded_fonts[base_font_name] = new_xref
                logger.info(
                    "Replaced subset font '%s' with full font '%s' (new xref: %d)",
                    name_str,
                    base_font_name,
                    new_xref,
                )
            except Exception as e:
                logger.error(
                    "Failed to embed font '%s' from path '%s': %s",
                    base_font_name,
                    font_path,
                    e,
                )

    if not font_xref_map:
        logger.debug("No subset fonts found to normalize. Returning original PDF.")
        doc.close()
        return pdf_bytes

    # PyMuPDF's 'clean_contents' with 'remap' handles replacing font references
    # across all pages, which is safer than manual replacement.
    doc.clean_contents(remap=font_xref_map)

    # Save with garbage collection to remove old font objects
    new_pdf_bytes = doc.tobytes(garbage=4, deflate=True)
    doc.close()
    logger.info(
        "PDF font normalization complete. Size change: %d -> %d bytes",
        len(pdf_bytes),
        len(new_pdf_bytes),
    )

    return new_pdf_bytes
