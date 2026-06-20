import fitz  # PyMuPDF
from dataclasses import dataclass
from typing import List, Tuple, Optional
import logging

from ..common.fonts import resolve_font
from ..common.tracing import get_tracer
from ..common.titles import generate_short_title
from .difficulty import assign_difficulty_bins
from .models import File
from ..common.config import get_settings, Toc

logger = logging.getLogger(__name__)
tracer = get_tracer(__name__)

DEFAULT_FONT_NAME = "RobotoCondensed-Regular.ttf"
DEFAULT_TITLE_FONT_NAME = "RobotoCondensed-Bold.ttf"
DEFAULT_TEXT_SEMIBOLD_FONT_NAME = "RobotoCondensed-SemiBold.ttf"

# Pride-flag rainbow, cycled one colour per (non-space) character for entries a
# postfix flags as ``rainbow``. RGB on a 0–1 scale; the yellow is darkened from
# the literal flag colour so it stays legible on white paper.
RAINBOW_PALETTE: Tuple[Tuple[float, float, float], ...] = (
    (0.84, 0.00, 0.00),  # red
    (0.95, 0.49, 0.00),  # orange
    (0.86, 0.67, 0.00),  # yellow (darkened for contrast)
    (0.00, 0.50, 0.15),  # green
    (0.00, 0.30, 0.80),  # blue
    (0.46, 0.00, 0.54),  # violet
)


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

    def _append_rainbow_title(
        self,
        writers: dict,
        page_rect: fitz.Rect,
        text: str,
        x_start: float,
        y_pos: float,
    ) -> None:
        """Append ``text`` one character at a time, cycling the rainbow palette.

        Each visible character is routed to the per-colour TextWriter for its
        rainbow colour (created on demand), so ``write_text`` paints it that
        colour. Whitespace advances the pen without consuming a colour, keeping
        the cycle aligned to letters across words.
        """
        x = x_start
        color_index = 0
        for char in text:
            char_width = self.text_font.text_length(
                char, fontsize=self.config.text_fontsize
            )
            if not char.isspace():
                color = RAINBOW_PALETTE[color_index % len(RAINBOW_PALETTE)]
                tw = writers.setdefault(color, fitz.TextWriter(page_rect))
                tw.append(
                    (x, y_pos),
                    char,
                    font=self.text_font,
                    fontsize=self.config.text_fontsize,
                )
                color_index += 1
            x += char_width

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
    ):
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

        # Add any custom postfixes; first matched color wins for the whole row
        postfix_str = ""
        entry_color: Optional[tuple[float, float, float]] = None
        entry_rainbow = False
        if self.config.postfixes:
            for postfix_config in self.config.postfixes:
                for p_filter in postfix_config.filters:
                    if p_filter.matches({**file.properties, "name": file.name}):
                        postfix_str += postfix_config.postfix
                        if entry_color is None and postfix_config.color is not None:
                            entry_color = postfix_config.color
                        if postfix_config.rainbow:
                            entry_rainbow = True
                        break  # Stop checking filters for this postfix config

        shortened_title = self._generate_toc_title(
            file.name,
            max_length=self.config.max_toc_entry_length - len(postfix_str),
            is_ready_to_play=file.properties.get("status") == "READY_TO_PLAY",
        )

        full_title = f"{symbol}{shortened_title}{postfix_str}"

        title_width = self.text_font.text_length(
            full_title, fontsize=self.config.text_fontsize
        )

        # Draw the title. Rainbow entries paint each character in the next pride
        # colour (across per-colour writers); otherwise the whole row shares one
        # writer keyed by its colour. Dot leaders and the page number always use
        # ``tw`` below: the matched colour for a plain row, or the default
        # (None) writer for a rainbow row so they stay legible.
        if entry_rainbow:
            self._append_rainbow_title(writers, page_rect, full_title, x_start, y_pos)
            tw = writers.setdefault(None, fitz.TextWriter(page_rect))
        else:
            # Each distinct color gets its own TextWriter so write_text() can apply it
            tw = writers.setdefault(entry_color, fitz.TextWriter(page_rect))
            tw.append(
                (x_start, y_pos),
                full_title,
                font=self.text_font,
                fontsize=self.config.text_fontsize,
            )

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
        dots_start_x = x_start + title_width
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
                    writers = new_writers()

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
            )
            current_line_in_column += 1

        if any(tw.text_rect for tw in writers.values()):
            page = self.pdf.new_page(width=page_rect.width, height=page_rect.height)
            self._write_page_writers(page, writers)

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
