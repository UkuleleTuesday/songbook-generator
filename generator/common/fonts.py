import importlib.resources
import os
from pathlib import Path

import fitz

from .tracing import get_tracer

# Local fallback fonts directory
FONTS_DIR = Path(__file__).parent.parent.parent / "fonts"
tracer = get_tracer(__name__)


def resolve_font(font_name: str) -> fitz.Font:
    """
    Load a font from package resources.
    If it fails, log a warning and fall back to a built-in font.
    """
    try:
        # Standard way to load package resources, works when installed
        font_buffer = (
            importlib.resources.files("generator.fonts")
            .joinpath(font_name)
            .read_bytes()
        )
        return fitz.Font(fontbuffer=font_buffer)
    except (ModuleNotFoundError, FileNotFoundError):
        # Fallback for environments where the package is not installed (e.g., GCF Gen2)
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            font_path = os.path.join(current_dir, "..", "fonts", font_name)
            with open(font_path, "rb") as f:
                font_buffer = f.read()
            return fitz.Font(fontbuffer=font_buffer)
        except FileNotFoundError as e:
            raise FileNotFoundError(f"Font file not found for: {font_name}") from e
