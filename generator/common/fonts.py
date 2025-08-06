import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

import fontra

# Local fallback fonts directory
FONTS_DIR = Path(__file__).parent.parent.parent / "fonts"
logger = logging.getLogger(__name__)


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
        # fontra is good at parsing names like "Verdana-Bold"
        font_path = fontra.get_font_path(font_name)
        if font_path:
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
