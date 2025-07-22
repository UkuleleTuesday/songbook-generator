import fitz  # PyMuPDF
import re
from dataclasses import dataclass
from typing import List, Tuple
import importlib.resources
import os

from ..common.config import load_config
from ..common.tracing import get_tracer
from .difficulty import assign_difficulty_bins
from .exceptions import TocGenerationException
from .models import File

tracer = get_tracer(__name__)

DEFAULT_FONT_NAME = "RobotoCondensed-Regular.ttf"
DEFAULT_TITLE_FONT_NAME = "RobotoCondensed-Bold.ttf"


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


def generate_toc_title(original_title: str, max_length: int) -> str:
    """
    Generate a shortened title for TOC entries using simple heuristics.

    Args:
        original_title: The original song title
        max_length: Maximum allowed length for the title

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

    return title


@dataclass
class TocLayout:
    """Configuration for TOC layout and styling."""

    columns_per_page: int = 2
    column_width: int = 250
    column_spacing: int = 20
    margin_top: int = 20
    margin_bottom: int = 20
    margin_left: int = 25
    margin_right: int = 25
    title_height: int = 50
    line_spacing: int = 12
    text_font: fitz.Font = None
    text_fontsize: float = 10
    title_font: fitz.Font = None
    title_fontsize: int = 16
    # With current font, fontsize and margins, this is the max length that fits and
    # doesn't result in overlap between columns.
    # Obviously highly dependent on the font and fontsize used.
    max_toc_entry_length = 58


@dataclass
class TocEntry:
    """Information about a TOC entry for later link creation."""

    page_number: int
    target_page: int
    text: str
    rect: fitz.Rect
    toc_page_index: int


def load_toc_config() -> TocLayout:
    """Load TOC configuration from config file."""
    config = load_config()
    toc_config = config.get("toc", {})
    layout = TocLayout()

    layout.text_font = resolve_font(toc_config.get("text-font", DEFAULT_FONT_NAME))
    layout.text_fontsize = toc_config.get("text-fontsize", layout.text_fontsize)
    layout.title_font = resolve_font(
        toc_config.get("title-font", DEFAULT_TITLE_FONT_NAME)
    )
    layout.title_fontsize = toc_config.get("title-fontsize", layout.title_fontsize)

    return layout


class TocGenerator:
    """Generates table of contents PDF with multi-column, multi-page layout."""

    def __init__(self, layout: TocLayout):
        self.layout = layout
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

        # Reserve fixed width for page numbers for consistent dot alignment
        max_page_num_width = self.layout.text_font.text_length(
            "9999", fontsize=self.layout.text_fontsize
        )
        symbol_width = self.layout.text_font.text_length(
            symbol, fontsize=self.layout.text_fontsize
        )

        file_name = file.name
        shortened_title = generate_toc_title(
            file_name, max_length=self.layout.max_toc_entry_length
        )
        if file.properties.get("status") == "READY_TO_PLAY":
            shortened_title += "*"

        full_title = f"{symbol}{shortened_title}"
        title_width = self.layout.text_font.text_length(
            full_title, fontsize=self.layout.text_fontsize
        )

        # Append title
        tw.append(
            (x_start, y_pos),
            full_title,
            font=self.layout.text_font,
            fontsize=self.layout.text_fontsize,
        )

        # If title is wider than the column, it will cause an error.
        # This can happen if the title has many wide characters. We avoid drawing dots.
        if title_width < self.layout.column_width:
            # Define rectangle for dots and page number
            dots_rect = fitz.Rect(
                x_start + title_width,
                y_pos - self.layout.text_fontsize,  # Align with title baseline
                x_start + self.layout.column_width,
                y_pos + self.layout.line_spacing,
            )

            # Calculate number of dots to fill the space
            page_num_width = self.layout.text_font.text_length(
                page_number_str, fontsize=self.layout.text_fontsize
            )
            dot_width = self.layout.text_font.text_length(
                ".", fontsize=self.layout.text_fontsize
            )
            dots_space = dots_rect.width - page_num_width
            num_dots = int(dots_space / dot_width) if dot_width > 0 else 0
            dots = "." * max(num_dots - 3, 0)

            # Fill textbox with dots and right-aligned page number
            print(full_title)
            print(f"{dots} {page_number_str}")
            tw.fill_textbox(
                dots_rect,
                f"{dots} {page_number_str}",
                font=self.layout.text_font,
                fontsize=self.layout.text_fontsize,
                align=fitz.TEXT_ALIGN_RIGHT,
            )

        # Store entry for link creation
        link_rect = fitz.Rect(
            x_start,
            y_pos - self.layout.text_fontsize,
            x_start + self.layout.column_width,
            y_pos + self.layout.text_fontsize * 0.2,
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
            - self.layout.title_height
            - self.layout.margin_top
            - self.layout.margin_bottom
        )
        lines_per_column = int(available_height // self.layout.line_spacing)
        column_positions = [
            self.layout.margin_left
            + col * (self.layout.column_width + self.layout.column_spacing)
            for col in range(self.layout.columns_per_page)
        ]
        title_pos = fitz.Point(
            self.layout.margin_left,
            self.layout.margin_top + self.layout.title_height - 20,
        )
        tw.append(
            title_pos,
            "Table of Contents",
            font=self.layout.title_font,
            fontsize=self.layout.title_fontsize,
        )

        current_column = 0
        current_line_in_column = 0
        current_page_index = 0

        for file_index, file in enumerate(files):
            if current_line_in_column >= lines_per_column:
                current_column = (current_column + 1) % self.layout.columns_per_page
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
                        font=self.layout.title_font,
                        fontsize=self.layout.title_fontsize,
                    )

            y_pos = (
                self.layout.title_height
                + self.layout.margin_top
                + (current_line_in_column * self.layout.line_spacing)
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

        layout = load_toc_config()
        span.set_attributes(
            {
                "toc.layout.columns_per_page": layout.columns_per_page,
                "toc.layout.column_width": layout.column_width,
                "toc.layout.column_spacing": layout.column_spacing,
                "toc.layout.margin_top": layout.margin_top,
                "toc.layout.margin_bottom": layout.margin_bottom,
                "toc.layout.margin_left": layout.margin_left,
                "toc.layout.margin_right": layout.margin_right,
                "toc.layout.title_height": layout.title_height,
                "toc.layout.line_spacing": layout.line_spacing,
                "toc.layout.text_font": layout.text_font.name,
                "toc.layout.text_fontsize": layout.text_fontsize,
                "toc.layout.title_font": layout.title_font.name,
                "toc.layout.title_fontsize": layout.title_fontsize,
                "toc.layout.max_toc_entry_length": layout.max_toc_entry_length,
            }
        )
        generator = TocGenerator(layout)
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
