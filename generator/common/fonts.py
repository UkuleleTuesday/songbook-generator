import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional

import fitz
import fontra

# Local fallback fonts directory
FONTS_DIR = Path(__file__).parent.parent.parent / "fonts"
logger = logging.getLogger(__name__)

# Initialize fontra's font database on module load
try:
    fontra.init_fontdb()
except Exception as e:
    logger.error("Failed to initialize fontra's font database: %s", e)


@lru_cache(maxsize=128)
def find_font_path(font_name: str) -> Optional[str]:
    """
    Finds the path to a font file using fontra, with a local fallback.

    Args:
        font_name: The name of the font (e.g., "Verdana", "Arial-Bold").

    Returns:
        The path to the font file, or None if not found.
    """
    try:
        # Parse font_name into family and style, e.g., "Arial-Bold" -> ("Arial", "Bold")
        parts = font_name.split("-")
        family = parts[0]
        style = parts[1] if len(parts) > 1 else "Regular"

        font_ref = fontra.get_font(family, style)
        if font_ref and font_ref.path:
            font_path = str(font_ref.path)
            logger.debug("Found font '%s' via fontra at: %s", font_name, font_path)
            return font_path
    except Exception as e:
        logger.warning(
            "fontra failed to find font '%s'. Will try local fallback. Error: %s",
            font_name,
            e,
        )

    # Fallback to checking local `fonts/` directory
    # fontra names are usually PostScript names, but let's be flexible
    for ext in ("ttf", "otf"):
        # e.g. Verdana-Bold -> Verdana-Bold.ttf
        local_path = FONTS_DIR / f"{font_name}.{ext}"
        if local_path.exists():
            logger.debug(
                "Found font '%s' via local fallback at: %s", font_name, local_path
            )
            return str(local_path)
        # e.g. Verdana-Bold -> Verdana.ttf (if bold is a style)
        base_family = font_name.split("-")[0]
        local_path = FONTS_DIR / f"{base_family}.{ext}"
        if local_path.exists():
            logger.debug(
                "Found font '%s' as base family via local fallback at: %s",
                font_name,
                local_path,
            )
            return str(local_path)

    logger.warning("Could not find a font file for '%s'", font_name)
    return None


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
    for i, page in enumerate(doc):
        fonts_on_page = page.get_fonts(full=True)
        for font_info in fonts_on_page:
            xref = font_info[0]
            name_str = font_info[4]  # The font name is at index 4, and is a string
            # Already processed this font xref
            if xref in font_xref_map:
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
                # Embed the full font into the current page's resources.
                # This makes it available throughout the document.
                new_xref = page.insert_font(
                    fontfile=font_path, fontname=base_font_name
                )
                font_xref_map[xref] = new_xref
                embedded_fonts[base_font_name] = new_xref
            except Exception as e:
                logger.error(
                    "Failed to embed font '%s' from path '%s': %s",
                    base_font_name,
                    font_path,
                    e,
                )

    if not font_xref_map:
        doc.close()
        return pdf_bytes

    # Replace the old font objects (xrefs) with references to the new ones.
    for old_xref, new_xref in font_xref_map.items():
        doc.update_object(old_xref, f"{new_xref} 0 R")

    # Save the document with garbage collection to remove the orphaned subset font objects.
    new_pdf_bytes = doc.tobytes(garbage=3, deflate=True)
    doc.close()

    return new_pdf_bytes
