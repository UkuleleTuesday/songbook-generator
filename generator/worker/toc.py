import fitz  # PyMuPDF
from dataclasses import dataclass
from typing import List, Tuple, Optional
import logging

from ..common.fonts import resolve_font
from ..common.tracing import get_tracer
from ..common.titles import generate_short_title
from .difficulty import assign_difficulty_bins
from .models import File
from ..common.config import get_settings, Toc, TocSymbol

logger = logging.getLogger(__name__)
tracer = get_tracer(__name__)

DEFAULT_FONT_NAME = "RobotoCondensed-Regular.ttf"
DEFAULT_TITLE_FONT_NAME = "RobotoCondensed-Bold.ttf"
DEFAULT_TEXT_SEMIBOLD_FONT_NAME = "RobotoCondensed-SemiBold.ttf"

# Pride/identity flags drawn as small vector marks next to TOC entries carrying
# the matching ``TocSymbol`` badge. RGB on a 0–1 scale; top stripe first. Vivid
# (not the muted text shades) because the mark is a small solid graphic, where
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

# Map each flag symbol to its (stripe colours, optional per-stripe weights).
# Weights of ``None`` mean equal-height stripes.
FLAG_PALETTES: dict = {
    TocSymbol.PRIDE_FLAG: (PRIDE_FLAG_COLORS, None),
    TocSymbol.TRANS_FLAG: (TRANS_FLAG_COLORS, None),
    TocSymbol.BI_FLAG: (BI_FLAG_COLORS, BI_FLAG_WEIGHTS),
    TocSymbol.LESBIAN_FLAG: (LESBIAN_FLAG_COLORS, None),
    TocSymbol.PAN_FLAG: (PAN_FLAG_COLORS, None),
    TocSymbol.NONBINARY_FLAG: (NONBINARY_FLAG_COLORS, None),
}


def difficulty_symbol(difficulty_bin: int) -> str:
    """Return a symbol representing the difficulty level from a bin."""
    symbols = ["", "○", "◔", "◑", "◕", "●"]
    if 0 <= difficulty_bin < len(symbols):
        return symbols[difficulty_bin]
    return ""  # Default to no symbol if bin is out of range


@dataclass
class TocEntry:
    """Information about a TOC entry for later link creation."""

    page_number: int
    target_page: int
    text: str
    rect: fitz.Rect
    toc_page_index: int
    title: str = ""
    """Full, untruncated song title, used for the native PDF outline/bookmarks."""


class TocGenerator:
    """Generates table of contents PDF with multi-column, multi-page layout."""

    def __init__(self, config: Toc):
        self.config = config
        self.text_font = resolve_font(self.config.text_font)
        self.page_number_font = resolve_font(self.config.page_number_font)
        self.title_font = resolve_font(self.config.title_font)
        self.pdf = fitz.open()
        self.toc_entries = []  # Store entries for later link creation

    def _generate_toc_title(
        self, original_title: str, max_length: int, is_ready_to_play: bool = False
    ) -> str:
        """
        Generate a shortened title for TOC entries using shared logic.

        Args:
            original_title: The original song title
            max_length: Maximum allowed length for the title
            is_ready_to_play: If True, appends a '*' to the title.

        Returns:
            Shortened title that fits within max_length
        """
        return generate_short_title(
            original_title,
            max_length=max_length,
            include_wip_marker=self.config.include_wip_marker,
            is_ready_to_play=is_ready_to_play,
        )

    @staticmethod
    def _write_page_writers(page: fitz.Page, writers: dict) -> None:
        """Write all per-color TextWriters to the page."""
        for color, tw in writers.items():
            if tw.text_rect:
                if color is None:
                    tw.write_text(page)
                else:
                    tw.write_text(page, color=color)

    def _flag_size(self) -> Tuple[float, float, float]:
        """Return (width, height, leading_gap) of a flag mark, in points."""
        height = self.config.text_fontsize * 0.72
        width = height * 1.6  # ~flag aspect ratio
        gap = self.text_font.text_length(" ", fontsize=self.config.text_fontsize)
        return width, height, gap

    @staticmethod
    def _draw_marks(page: fitz.Page, marks: list) -> None:
        """Draw deferred vector flag marks onto a finalised page.

        Each mark is ``(x, baseline_y, width, height, stripes, weights)`` where
        ``stripes`` is the top-to-bottom palette and ``weights`` is an optional
        per-stripe height ratio (``None`` = equal stripes).
        """
        for x, baseline_y, width, height, stripes, weights in marks:
            TocGenerator._draw_flag(
                page, x, baseline_y, width, height, stripes, weights
            )

    @staticmethod
    def _draw_flag(
        page: fitz.Page,
        x: float,
        baseline_y: float,
        width: float,
        height: float,
        stripes: Tuple[Tuple[float, float, float], ...],
        weights: Optional[Tuple[float, ...]] = None,
    ) -> None:
        """Draw a small horizontal-stripe flag with its baseline near the text.

        The flag bottom sits on the text baseline; stripes overlap by a hair to
        avoid anti-aliasing seams, and a faint outline crisps it against white.
        ``weights`` gives relative stripe heights (e.g. the bi flag's 2:1:2);
        when ``None`` the stripes are equal height.
        """
        n = len(stripes)
        if weights is None:
            weights = (1.0,) * n
        total = sum(weights)
        top = baseline_y - height
        y = top
        for i, (color, weight) in enumerate(zip(stripes, weights)):
            stripe_h = height * (weight / total)
            y0 = y
            # Extend the last stripe to the flag bottom; overlap others slightly.
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

    def _add_toc_entry(
        self,
        writers: dict,
        page_rect: fitz.Rect,
        file_index: int,
        page_offset: int,
        file: File,
        x_start: float,
        y_pos: float,
        current_page_index: int,
        marks: Optional[list] = None,
    ):
        if marks is None:
            marks = []
        page_number_str = str(file_index + 1 + page_offset)

        # Get difficulty symbol
        symbol = ""
        if self.config.include_difficulty:
            difficulty_bin_str = file.properties.get("difficulty_bin")
            if difficulty_bin_str:
                try:
                    difficulty_bin = int(difficulty_bin_str)
                    symbol_char = difficulty_symbol(difficulty_bin)
                    if symbol_char:
                        symbol = symbol_char + " "
                except (ValueError, TypeError):
                    pass  # Ignore if not a valid integer

        # Collect badges from all matching decorations (in order); first matched
        # colour wins for the whole row.
        entry_badges = []
        entry_color: Optional[tuple[float, float, float]] = None
        if self.config.decorations:
            for decoration in self.config.decorations:
                for p_filter in decoration.filters:
                    if p_filter.matches({**file.properties, "name": file.name}):
                        entry_badges.extend(decoration.badges)
                        if entry_color is None and decoration.color is not None:
                            entry_color = decoration.color
                        break  # Stop checking filters for this decoration

        # Text badges share the title's character budget so the row still fits.
        text_badge_len = sum(len(b.text) for b in entry_badges if b.text is not None)
        shortened_title = self._generate_toc_title(
            file.name,
            max_length=self.config.max_toc_entry_length - text_badge_len,
            is_ready_to_play=file.properties.get("status") == "READY_TO_PLAY",
        )

        title_text = f"{symbol}{shortened_title}"

        # The whole row shares one TextWriter keyed by its colour (default black
        # unless a decoration sets one).
        tw = writers.setdefault(entry_color, fitz.TextWriter(page_rect))
        tw.append(
            (x_start, y_pos),
            title_text,
            font=self.text_font,
            fontsize=self.config.text_fontsize,
        )

        # Lay out trailing badges after the title, in order. Text badges are
        # appended in the row colour; symbol badges are deferred vector marks
        # drawn when the page is finalised (see _draw_marks). ``x`` tracks the pen
        # so the dot leaders start after the last badge.
        x = x_start + self.text_font.text_length(
            title_text, fontsize=self.config.text_fontsize
        )
        for badge in entry_badges:
            if badge.text is not None:
                tw.append(
                    (x, y_pos),
                    badge.text,
                    font=self.text_font,
                    fontsize=self.config.text_fontsize,
                )
                x += self.text_font.text_length(
                    badge.text, fontsize=self.config.text_fontsize
                )
            elif badge.symbol is not None:
                stripes, weights = FLAG_PALETTES[badge.symbol]
                flag_w, flag_h, gap = self._flag_size()
                x += gap
                marks.append((x, y_pos, flag_w, flag_h, stripes, weights))
                x += flag_w + gap

        # Manually draw dots and page number to allow for different fonts
        page_num_width = self.page_number_font.text_length(
            page_number_str, fontsize=self.config.text_fontsize
        )

        # Draw page number (right-aligned)
        page_num_pos_x = x_start + self.config.column_width - page_num_width
        tw.append(
            (page_num_pos_x, y_pos),
            page_number_str,
            font=self.page_number_font,
            fontsize=self.config.text_fontsize,
        )

        # Draw dots
        dots_start_x = x
        dots_end_x = page_num_pos_x - self.text_font.text_length(
            " ", fontsize=self.config.text_fontsize
        )
        dots_width = dots_end_x - dots_start_x
        dot_width = self.text_font.text_length(".", fontsize=self.config.text_fontsize)
        if dot_width > 0:
            num_dots = int(dots_width / dot_width)
            dots = "." * max(0, num_dots)
            tw.append(
                (dots_start_x, y_pos),
                f"{dots} ",
                font=self.text_font,
                fontsize=self.config.text_fontsize,
            )

        # Store entry for link creation
        link_rect = fitz.Rect(
            x_start,
            y_pos - self.config.text_fontsize,
            x_start + self.config.column_width,
            y_pos + self.config.text_fontsize * 0.2,
        )
        self.toc_entries.append(
            TocEntry(
                page_number=int(page_number_str),
                target_page=file_index,
                text=shortened_title,
                rect=link_rect,
                toc_page_index=current_page_index,
                title=file.name,
            )
        )

    def generate(self, files: List[File], page_offset: int = 0) -> fitz.Document:
        """Generate the table of contents PDF."""
        if not files:
            return self.pdf

        temp_page = self.pdf.new_page()
        page_rect = temp_page.rect
        self.pdf.delete_page(0)

        available_height = (
            page_rect.height
            - self.config.title_height
            - self.config.margin_top
            - self.config.margin_bottom
        )
        lines_per_column = int(available_height // self.config.line_spacing)
        column_positions = [
            self.config.margin_left
            + col * (self.config.column_width + self.config.column_spacing)
            for col in range(self.config.columns_per_page)
        ]
        title_pos = fitz.Point(
            self.config.margin_left,
            self.config.margin_top
            + self.config.title_height
            - self.config.title_margin_bottom,
        )

        def new_writers() -> dict:
            """Fresh per-color writer dict for a new TOC page."""
            tw_default = fitz.TextWriter(page_rect)
            tw_default.append(
                title_pos,
                "Table of Contents",
                font=self.title_font,
                fontsize=self.config.title_fontsize,
            )
            return {None: tw_default}

        writers = new_writers()
        marks: list = []  # deferred vector marks (pride flags) for the current page
        current_column = 0
        current_line_in_column = 0
        current_page_index = 0

        for file_index, file in enumerate(files):
            if current_line_in_column >= lines_per_column:
                current_column = (current_column + 1) % self.config.columns_per_page
                current_line_in_column = 0
                if current_column == 0:
                    current_page_index += 1
                    page = self.pdf.new_page(
                        width=page_rect.width, height=page_rect.height
                    )
                    self._write_page_writers(page, writers)
                    self._draw_marks(page, marks)
                    writers = new_writers()
                    marks = []

            y_pos = (
                self.config.title_height
                + self.config.margin_top
                + (current_line_in_column * self.config.line_spacing)
            )
            self._add_toc_entry(
                writers,
                page_rect,
                file_index,
                page_offset,
                file,
                column_positions[current_column],
                y_pos,
                current_page_index,
                marks,
            )
            current_line_in_column += 1

        if any(tw.text_rect for tw in writers.values()) or marks:
            page = self.pdf.new_page(width=page_rect.width, height=page_rect.height)
            self._write_page_writers(page, writers)
            self._draw_marks(page, marks)

        return self.pdf

    def get_toc_entries(self) -> List[TocEntry]:
        """Return the list of TOC entries for link creation."""
        return self.toc_entries


def build_table_of_contents(
    files: List[File],
    page_offset: int = 0,
    edition_toc_config: Optional[Toc] = None,
) -> Tuple[fitz.Document, List[TocEntry]]:
    """Build a table of contents PDF from a list of files.

    Returns:
        Tuple of (TOC PDF document, list of TOC entries for link creation)
    """
    with tracer.start_as_current_span("build_table_of_contents") as span:
        assign_difficulty_bins(files)

        # Start with global config
        config = get_settings().toc

        # If edition-specific config is provided, merge it
        if edition_toc_config:
            # Create a new Toc object with updated fields
            config_dict = config.model_dump()
            edition_config_dict = edition_toc_config.model_dump(exclude_unset=True)
            config_dict.update(edition_config_dict)
            config = Toc(**config_dict)

        span.set_attributes(
            {
                f"toc.{key}": value
                for key, value in config.model_dump().items()
                if value is not None
            }
        )
        generator = TocGenerator(config)
        toc_pdf = generator.generate(files, page_offset)
        return toc_pdf, generator.get_toc_entries()


def _target_page_index(
    toc_entries: List[TocEntry], entry: TocEntry, toc_page_offset: int
) -> int:
    """Absolute 0-based index of an entry's song page in the merged PDF.

    Songs sit immediately after the cover/preface (``toc_page_offset``) and the
    TOC pages, hence ``+ number of TOC pages + the file's index``. This is the
    same arithmetic used to place the clickable TOC links, so bookmarks and
    links always resolve to the same page.
    """
    num_toc_pages = len({e.toc_page_index for e in toc_entries})
    return toc_page_offset + num_toc_pages + entry.target_page


def build_pdf_outline(
    toc_entries: List[TocEntry],
    toc_page_offset: int,
    page_count: Optional[int] = None,
) -> List[list]:
    """Build a PyMuPDF outline (``[[level, title, page], ...]``) from TOC entries.

    Pages are 1-based, as required by :meth:`fitz.Document.set_toc`. When
    ``page_count`` is given, entries whose target page falls outside the document
    are skipped (mirrors the bounds check used when inserting TOC links).
    """
    outline: List[list] = []
    for entry in toc_entries:
        target_page_index = _target_page_index(toc_entries, entry, toc_page_offset)
        if page_count is not None and target_page_index >= page_count:
            continue
        title = entry.title or entry.text
        if not title:
            continue
        outline.append([1, title, target_page_index + 1])
    return outline


def set_pdf_outline(
    merged_pdf: fitz.Document, toc_entries: List[TocEntry], toc_page_offset: int
) -> List[list]:
    """Set a native PDF outline (bookmarks) on the merged PDF from TOC entries.

    One top-level bookmark per song pointing at its page, so PDF readers show a
    navigable sidebar. Returns the outline that was applied (empty if there were
    no entries).
    """
    with tracer.start_as_current_span("set_pdf_outline") as span:
        outline = build_pdf_outline(
            toc_entries, toc_page_offset, page_count=len(merged_pdf)
        )
        span.set_attribute("toc.outline.count", len(outline))
        if outline:
            merged_pdf.set_toc(outline)
        return outline


def add_toc_links_to_merged_pdf(
    merged_pdf: fitz.Document, toc_entries: List[TocEntry], toc_page_offset: int
):
    """Add clickable links to TOC entries in the merged PDF.

    Args:
        merged_pdf: The complete merged PDF document
        toc_entries: List of TOC entries with link information
        toc_page_offset: Offset where TOC pages start in the merged PDF
    """
    with tracer.start_as_current_span("add_toc_links_to_merged_pdf") as span:
        span.set_attribute("toc.entries.count", len(toc_entries))
        span.set_attribute("toc.page_offset", toc_page_offset)
        for entry in toc_entries:
            # Get the TOC page in the merged PDF
            toc_page_index = toc_page_offset + entry.toc_page_index
            if toc_page_index >= len(merged_pdf):
                continue

            toc_page = merged_pdf[toc_page_index]

            # Calculate the target page in the merged PDF (shared with the native
            # outline so links and bookmarks always point to the same page).
            target_page_index = _target_page_index(toc_entries, entry, toc_page_offset)
            if target_page_index >= len(merged_pdf):
                continue

            # Create link dictionary for internal navigation
            link_dict = {
                "kind": fitz.LINK_GOTO,
                "from": entry.rect,
                "page": target_page_index,
                "to": fitz.Point(0, 0),  # Jump to top-left of target page
            }

            # Insert the link
            toc_page.insert_link(link_dict)
