import fitz  # PyMuPDF
import re
from dataclasses import dataclass
from typing import List, Tuple
import importlib.resources
import os

from ..common.tracing import get_tracer
from .difficulty import assign_difficulty_bins
from .exceptions import TocGenerationException
from .models import File
from ..common.config import get_settings, Toc

tracer = get_tracer(__name__)

DEFAULT_FONT_NAME = "RobotoCondensed-Regular.ttf"
DEFAULT_TITLE_FONT_NAME = "RobotoCondensed-Bold.ttf"
DEFAULT_TEXT_SEMIBOLD_FONT_NAME = "RobotoCondensed-SemiBold.ttf"


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
            raise TocGenerationException(f"TOC font file not found: {font_name}") from e


def difficulty_symbol(difficulty_bin: int) -> str:
    """Return a symbol representing the difficulty level from a bin."""
    symbols = ["", "○", "◔", "◑", "◕", "●"]
    if 0 <= difficulty_bin < len(symbols):
        return symbols[difficulty_bin]
    return ""  # Default to no symbol if bin is out of range


def generate_toc_title(
    original_title: str, max_length: int, is_ready_to_play: bool = False
) -> str:
    """
    Generate a shortened title for TOC entries using simple heuristics.

    Args:
        original_title: The original song title
        max_length: Maximum allowed length for the title
        is_ready_to_play: If True, appends a '*' to the title.

    Returns:
        Shortened title that fits within max_length
    """
    title = original_title.strip()

    # If already short enough, return as-is
    if len(title) <= max_length:
        # Still apply cleaning for consistency
        pass

    # Remove featuring information in both parentheses and brackets
    # This regex matches parentheses or brackets containing feat./featuring
    title = re.sub(
        r"\s*[\(\[][^\)\]]*(?:feat\.|featuring)[^\)\]]*[\)\]]",
        "",
        title,
        flags=re.IGNORECASE,
    )

    # Remove bracketed information (after featuring removal to avoid conflicts)
    title = re.sub(r"\s*\[[^\]]*\]", "", title)

    # Remove version/edit information in parentheses
    # This regex matches specific keywords that indicate versions/edits
    title = re.sub(
        r"\s*\([^)]*(?:Radio|Single|Edit|Version|Mix|Remix|Mono)\b[^)]*\)",
        "",
        title,
        flags=re.IGNORECASE,
    )

    # Clean up any extra whitespace
    title = re.sub(r"\s+", " ", title).strip()

    # If still too long, truncate with ellipsis
    if len(title) > max_length:
        # Try to cut at a word boundary if possible
        if max_length > 3:
            truncate_length = max_length - 3  # Reserve space for "..."
            if " " in title[:truncate_length]:
                # Find the last space before the truncation point
                last_space = title[:truncate_length].rfind(" ")
                if (
                    last_space > max_length // 2
                ):  # Only use word boundary if it's not too short
                    title = title[:last_space] + "..."
                else:
                    title = title[:truncate_length] + "..."
            else:
                title = title[:truncate_length] + "..."
        else:
            title = title[:max_length]

    if is_ready_to_play:
        title += "*"

    return title


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
        difficulty_bin_str = file.properties.get("difficulty_bin")
        if difficulty_bin_str:
            try:
                difficulty_bin = int(difficulty_bin_str)
                symbol_char = difficulty_symbol(difficulty_bin)
                if symbol_char:
                    symbol = symbol_char + " "
            except (ValueError, TypeError):
                pass  # Ignore if not a valid integer

        shortened_title = generate_toc_title(
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
    files: List[File], page_offset: int = 0
) -> Tuple[fitz.Document, List[TocEntry]]:
    """Build a table of contents PDF from a list of files.

    Returns:
        Tuple of (TOC PDF document, list of TOC entries for link creation)
    """
    with tracer.start_as_current_span("build_table_of_contents") as span:
        assign_difficulty_bins(files)

        config = get_settings().toc
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
