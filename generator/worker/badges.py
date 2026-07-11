"""Decoration badges: the small flag/identity marks stamped after a song title.

A songbook edition can attach badges to songs via ``TocDecoration`` filters (see
``generator/common/config.py``). The same badges appear both in the table of
contents and on each song's first-page "tab", so the matching logic
(:func:`collect_decoration_badges`) and the vector drawing (:func:`draw_flag`)
live here and are shared by ``toc.py`` (TOC rows) and ``pdf.py`` (song tabs).
"""

from typing import List, Optional, Tuple

import fitz  # PyMuPDF

from ..common.config import TocBadge, TocDecoration, TocSymbol
from .models import File

# Pride/identity flags drawn as small vector marks next to entries carrying the
# matching ``TocSymbol`` badge. RGB on a 0–1 scale; top stripe first. Vivid (not
# the muted text shades) because the mark is a small solid graphic, where
# saturated colours read as a recognisable flag.
PRIDE_FLAG_COLORS: Tuple[Tuple[float, float, float], ...] = (
    (0.894, 0.012, 0.012),  # red
    (1.000, 0.549, 0.000),  # orange
    (1.000, 0.929, 0.000),  # yellow
    (0.000, 0.502, 0.149),  # green
    (0.000, 0.302, 1.000),  # blue
    (0.459, 0.027, 0.529),  # violet
)

# Transgender flag: light blue / pink / white / pink / light blue.
TRANS_FLAG_COLORS: Tuple[Tuple[float, float, float], ...] = (
    (0.357, 0.808, 0.980),
    (0.961, 0.663, 0.722),
    (1.000, 1.000, 1.000),
    (0.961, 0.663, 0.722),
    (0.357, 0.808, 0.980),
)

# Bisexual flag: magenta / lavender / royal blue, in a 2:1:2 stripe ratio.
BI_FLAG_COLORS: Tuple[Tuple[float, float, float], ...] = (
    (0.839, 0.008, 0.439),
    (0.608, 0.310, 0.588),
    (0.000, 0.220, 0.659),
)
BI_FLAG_WEIGHTS: Tuple[float, ...] = (2.0, 1.0, 2.0)

# Lesbian flag (five-stripe): dark orange / orange / white / pink / dark rose.
LESBIAN_FLAG_COLORS: Tuple[Tuple[float, float, float], ...] = (
    (0.835, 0.176, 0.000),
    (1.000, 0.604, 0.337),
    (1.000, 1.000, 1.000),
    (0.827, 0.384, 0.643),
    (0.639, 0.008, 0.384),
)

# Pansexual flag: pink / yellow / cyan-blue.
PAN_FLAG_COLORS: Tuple[Tuple[float, float, float], ...] = (
    (1.000, 0.129, 0.549),
    (1.000, 0.847, 0.000),
    (0.129, 0.694, 1.000),
)

# Non-binary flag: yellow / white / purple / black.
NONBINARY_FLAG_COLORS: Tuple[Tuple[float, float, float], ...] = (
    (0.988, 0.957, 0.204),
    (1.000, 1.000, 1.000),
    (0.612, 0.349, 0.820),
    (0.173, 0.173, 0.173),
)

# French flag: blue / white / red, drawn as *vertical* stripes (see
# VERTICAL_FLAG_SYMBOLS) rather than the horizontal stripes of the pride flags.
FRANCE_FLAG_COLORS: Tuple[Tuple[float, float, float], ...] = (
    (0.000, 0.129, 0.522),  # blue
    (1.000, 1.000, 1.000),  # white
    (0.929, 0.161, 0.220),  # red
)

# Map each flag symbol to its (stripe colours, optional per-stripe weights).
# Weights of ``None`` mean equal-height stripes.
FLAG_PALETTES: dict = {
    TocSymbol.PRIDE_FLAG: (PRIDE_FLAG_COLORS, None),
    TocSymbol.TRANS_FLAG: (TRANS_FLAG_COLORS, None),
    TocSymbol.BI_FLAG: (BI_FLAG_COLORS, BI_FLAG_WEIGHTS),
    TocSymbol.LESBIAN_FLAG: (LESBIAN_FLAG_COLORS, None),
    TocSymbol.PAN_FLAG: (PAN_FLAG_COLORS, None),
    TocSymbol.NONBINARY_FLAG: (NONBINARY_FLAG_COLORS, None),
    TocSymbol.FRANCE_FLAG: (FRANCE_FLAG_COLORS, None),
}

# Symbols whose stripes run vertically (left-to-right) instead of horizontally
# (top-to-bottom). ``draw_flag`` reads this to pick the stripe direction.
VERTICAL_FLAG_SYMBOLS = frozenset({TocSymbol.FRANCE_FLAG})


def collect_decoration_badges(
    file: File, decorations: Optional[List[TocDecoration]]
) -> Tuple[List[TocBadge], Optional[Tuple[float, float, float]]]:
    """Collect the badges (and first matched colour) that apply to *file*.

    Shared by the TOC rows and the per-song "tab" stamps so both pick up the
    exact same decorations: every decoration whose filters match contributes
    its badges, in order, and the first matched ``color`` wins.
    """
    badges: List[TocBadge] = []
    color: Optional[Tuple[float, float, float]] = None
    if not decorations:
        return badges, color
    for decoration in decorations:
        for p_filter in decoration.filters:
            if p_filter.matches({**file.properties, "name": file.name}):
                badges.extend(decoration.badges)
                if color is None and decoration.color is not None:
                    color = decoration.color
                break  # Stop checking filters for this decoration
    return badges, color


def draw_flag(
    page: fitz.Page,
    x: float,
    baseline_y: float,
    width: float,
    height: float,
    stripes: Tuple[Tuple[float, float, float], ...],
    weights: Optional[Tuple[float, ...]] = None,
    vertical: bool = False,
) -> None:
    """Draw a small striped flag with its baseline near the text.

    The flag bottom sits on the text baseline; stripes overlap by a hair to
    avoid anti-aliasing seams, and a faint outline crisps it against white.
    ``weights`` gives relative stripe sizes (e.g. the bi flag's 2:1:2); when
    ``None`` the stripes are equal size. ``vertical`` draws the stripes
    left-to-right (e.g. the French tricolor) instead of top-to-bottom.
    """
    n = len(stripes)
    if weights is None:
        weights = (1.0,) * n
    total = sum(weights)
    top = baseline_y - height
    if vertical:
        v = x
        for i, (color, weight) in enumerate(zip(stripes, weights)):
            stripe_w = width * (weight / total)
            x0 = v
            # Extend the last stripe to the flag edge; overlap others.
            x1 = x + width if i == n - 1 else x0 + stripe_w + 0.15
            page.draw_rect(
                fitz.Rect(x0, top, x1, baseline_y), color=None, fill=color, width=0
            )
            v += stripe_w
    else:
        y = top
        for i, (color, weight) in enumerate(zip(stripes, weights)):
            stripe_h = height * (weight / total)
            y0 = y
            # Extend the last stripe to the flag bottom; overlap others.
            y1 = baseline_y if i == n - 1 else y0 + stripe_h + 0.15
            page.draw_rect(
                fitz.Rect(x, y0, x + width, y1), color=None, fill=color, width=0
            )
            y += stripe_h
    page.draw_rect(
        fitz.Rect(x, top, x + width, baseline_y),
        color=(0.6, 0.6, 0.6),
        width=0.3,
    )
