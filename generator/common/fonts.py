import importlib.resources
import click
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional

import fitz
import fontra
from opentelemetry import trace

from .tracing import get_tracer

# Local fallback fonts directory
FONTS_DIR = Path(__file__).parent.parent.parent / "fonts"
tracer = get_tracer(__name__)

# Initialize fontra's font database on module load
fontra.init_fontdb()


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
        print(f"XXX FONT NAME = {font_name}")
        parts = font_name.split("-")
        family = parts[0]
        style = parts[1] if len(parts) > 1 else "Regular"

        try:
            font_ref = fontra.get_font(family, style)
        except KeyError as e:
            raise KeyError(
                f"Font lookup failed for font '{font_name}' (parsed as family='{family}', style='{style}'). "
                f"This may be due to a missing font on the system or a font naming issue. "
                f"Original error: {e}"
            ) from e

        if font_ref and font_ref.path:
            font_path = str(font_ref.path)
            click.echo(f"Found font '{font_name}' via fontra at: {font_path}")
            return font_path
    except (RuntimeError, OSError) as e:
        click.echo(
            f"fontra failed to find font '{font_name}'. Will try local fallback. Error: {e}"
        )

    # Fallback to checking local `fonts/` directory
    # First, check for exact filename match for names like "RobotoCondensed-Regular.ttf"
    for ext in ("ttf", "otf"):
        if font_name.endswith(f".{ext}"):
            local_path = FONTS_DIR / font_name
            if local_path.exists():
                click.echo(
                    f"Found font '{font_name}' via local fallback at: {local_path}"
                )
                return str(local_path)

    # Then, check for font names like "Verdana-Bold" -> "Verdana-Bold.ttf"
    # fontra names are usually PostScript names, but let's be flexible
    for ext in ("ttf", "otf"):
        # e.g. Verdana-Bold -> Verdana-Bold.ttf
        local_path = FONTS_DIR / f"{font_name}.{ext}"
        if local_path.exists():
            click.echo(f"Found font '{font_name}' via local fallback at: {local_path}")
            return str(local_path)
        # e.g. Verdana-Bold -> Verdana.ttf (if bold is a style)
        base_family = font_name.split("-")[0]
        local_path = FONTS_DIR / f"{base_family}.{ext}"
        if local_path.exists():
            click.echo(
                f"Found font '{font_name}' as base family via local fallback at: {local_path}"
            )
            return str(local_path)

    click.echo(f"Could not find a font file for '{font_name}'")
    return None


# Regex to find the base name of a subset font, e.g., "ABCDEF+Verdana-Bold" -> "Verdana-Bold"
SUBSET_FONT_RE = re.compile(r"^[A-Z]{6}\+(.*)")


def resolve_font(font_name: str) -> fitz.Font:
    """
    Finds and loads a font by its name, returning a fitz.Font object.
    It tries to load from package resources first, then system fonts.
    """
    # 1. Try to load from package resources (for bundled fonts like Roboto)
    try:
        font_buffer = (
            importlib.resources.files("generator.fonts")
            .joinpath(font_name)
            .read_bytes()
        )
        return fitz.Font(fontbuffer=font_buffer)
    except (ModuleNotFoundError, FileNotFoundError):
        click.echo(f"Font '{font_name}' not found in package resources.")

    # 2. Try to find font on the system using fontra or local path
    font_path = find_font_path(font_name)
    if font_path:
        try:
            return fitz.Font(fontfile=font_path)
        except RuntimeError as e:
            click.echo(
                f"Failed to load font from path '{font_path}': {e}. Using built-in."
            )
            return fitz.Font("helv")

    # 3. Fallback for system fonts if fontra fails but font might exist
    click.echo(f"Font '{font_name}' not found. Falling back to search system.")
    try:
        return fitz.Font(font_name)
    except RuntimeError:
        click.echo(f"Fallback for font '{font_name}' failed. Using built-in helv.")
        return fitz.Font("helv")


def _gather_font_replacements(
    doc: fitz.Document,
) -> tuple[Dict[int, int], Dict[str, int]]:
    """
    Scans a PDF document for subset fonts and prepares replacements.

    This function iterates through each page of the document, identifies subset fonts,
    finds their corresponding full font files, and embeds them into the PDF.
    It returns maps detailing the necessary replacements.

    Args:
        doc: The fitz.Document object to process.

    Returns:
        A tuple containing:
        - font_xref_map: A dictionary mapping old font cross-reference numbers (xrefs)
          to the new xrefs of their embedded full-font counterparts.
        - embedded_fonts: A dictionary mapping base font names to the new xrefs of the
          embedded full fonts, used to avoid re-embedding the same font.
    """
    font_xref_map: Dict[int, int] = {}
    embedded_fonts: Dict[str, int] = {}

    # Check fonts on all pages as they can differ
    for i, page in enumerate(doc):
        fonts_on_page = page.get_fonts(full=True)
        for font_info in fonts_on_page:
            xref = font_info[0]
            if xref in font_xref_map:
                continue

            # A subset font prefix can appear in the base font name (idx 3) or symbolic name (idx 4)
            name_to_check = None
            if SUBSET_FONT_RE.match(font_info[3]):
                name_to_check = font_info[3]
            elif SUBSET_FONT_RE.match(font_info[4]):
                name_to_check = font_info[4]

            if not name_to_check:
                continue

            match = SUBSET_FONT_RE.match(name_to_check)
            base_font_name = match.group(1)
            click.echo(f"Found subset font: {name_to_check} (base: {base_font_name})")

            if base_font_name in embedded_fonts:
                font_xref_map[xref] = embedded_fonts[base_font_name]
                continue

            font_path = find_font_path(base_font_name)
            if not font_path:
                click.echo(f"No full font file found for '{base_font_name}'. Skipping.")
                continue

            try:
                new_xref = page.insert_font(
                    fontfile=font_path, fontname=base_font_name
                )
                font_xref_map[xref] = new_xref
                embedded_fonts[base_font_name] = new_xref
            except RuntimeError as e:
                click.echo(
                    f"Failed to embed font '{base_font_name}' from path '{font_path}': {e}"
                )

    return font_xref_map, embedded_fonts


def normalize_pdf_fonts(pdf_bytes: bytes) -> bytes:
    """
    Replaces subset fonts in a PDF with their full font files.

    Args:
        pdf_bytes: The original PDF content as bytes.

    Returns:
        The processed PDF content as bytes, or the original bytes if no changes were made.
    """
    with tracer.start_as_current_span("normalize_pdf_fonts") as span:
        span.set_attribute("original_pdf_size", len(pdf_bytes))
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        if not doc.is_pdf or doc.page_count == 0:
            return pdf_bytes

        span.set_attribute("page_count", doc.page_count)
        font_xref_map, embedded_fonts = _gather_font_replacements(doc)

        if not font_xref_map:
            span.set_attribute("fonts_normalized_count", 0)
            span.set_attribute("final_pdf_size", len(pdf_bytes))
            doc.close()
            return pdf_bytes

        # Replace the old font objects (xrefs) with references to the new ones.
        for old_xref, new_xref in font_xref_map.items():
            doc.update_object(old_xref, f"{new_xref} 0 R")

        # Save the document with garbage collection to remove the orphaned subset font objects.
        new_pdf_bytes = doc.tobytes(garbage=3, deflate=True)
        doc.close()

        span.set_attribute("final_pdf_size", len(new_pdf_bytes))
        span.set_attribute("fonts_normalized_count", len(font_xref_map))
        span.set_attribute("embedded_fonts_count", len(embedded_fonts))
        span.set_attribute("embedded_fonts", list(embedded_fonts.keys()))

        return new_pdf_bytes
