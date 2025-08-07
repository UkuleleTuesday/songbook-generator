import importlib.resources
import click
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
        parts = font_name.split("-")
        family = parts[0]
        style = parts[1] if len(parts) > 1 else "Regular"

        try:
            font_ref = fontra.get_font(family, style)
        except KeyError as e:
            click.echo(
                f"Warning: Font lookup failed for font '{font_name}' (parsed as family='{family}', style='{style}'). "
                f"The font will be skipped. Original error: {e}"
            )
            return None

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


