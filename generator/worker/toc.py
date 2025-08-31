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

    def _add_toc_entry(
        self,
        tw: fitz.TextWriter,
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

        shortened_title = self._generate_toc_title(
            file.name,
            max_length=self.config.max_toc_entry_length,
            is_ready_to_play=file.properties.get("status") == "READY_TO_PLAY",
        )

        full_title = f"{symbol}{shortened_title}"

        # Append title
        tw.append(
            (x_start, y_pos),
            full_title,
            font=self.text_font,
            fontsize=self.config.text_fontsize,
        )

        title_width = self.text_font.text_length(
            full_title, fontsize=self.config.text_fontsize
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
            )
        )

    def generate(self, files: List[File], page_offset: int = 0) -> fitz.Document:
        """Generate the table of contents PDF."""
        if not files:
            return self.pdf

        temp_page = self.pdf.new_page()
        page_rect = temp_page.rect
        self.pdf.delete_page(0)

        tw = fitz.TextWriter(page_rect)
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
            self.config.margin_top + self.config.title_height - 20,
        )
        tw.append(
            title_pos,
            "Table of Contents",
            font=self.title_font,
            fontsize=self.config.title_fontsize,
        )

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
                    tw.write_text(page)
                    tw = fitz.TextWriter(page_rect)
                    tw.append(
                        title_pos,
                        "Table of Contents",
                        font=self.title_font,
                        fontsize=self.config.title_fontsize,
                    )

            y_pos = (
                self.config.title_height
                + self.config.margin_top
                + (current_line_in_column * self.config.line_spacing)
            )
            self._add_toc_entry(
                tw,
                file_index,
                page_offset,
                file,
                column_positions[current_column],
                y_pos,
                current_page_index,
            )
            current_line_in_column += 1

        if tw.text_rect:
            page = self.pdf.new_page(width=page_rect.width, height=page_rect.height)
            tw.write_text(page)

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

            # Calculate the target page in the merged PDF
            # The target page is after all TOC pages plus the file's index
            target_page_index = (
                toc_page_offset
                + len({e.toc_page_index for e in toc_entries})
                + entry.target_page
            )
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
