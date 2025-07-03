import click
import fitz  # PyMuPDF
import re
from dataclasses import dataclass
from typing import List, Dict, Any, Tuple

from config import load_config

DEFAULT_FONT = "helv"


def resolve_font(fontfile, fallback_font):
    """
    Try to build a Font() using the provided fontfile path.
    If it succeeds, return the fontfile path.
    If it fails, log a warning and fall back to the fallback_font.
    """
    try:
        if fontfile is None:
            raise ValueError("No fontfile provided")
        if fontfile != DEFAULT_FONT:
            fitz.Font(fontfile=fontfile)
            return fontfile
        return fallback_font
    except Exception as e:
        click.echo(
            f"Warning: Failed to load fontfile '{fontfile}'. Falling back to default font '{fallback_font}'. Error: {e}"
        )
        return fallback_font


def generate_toc_title(original_title: str, max_length: int = 60) -> str:
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
    page_margin: int = 50
    title_height: int = 50
    line_spacing: int = 10
    text_font: str = DEFAULT_FONT
    text_fontsize: int = 9
    title_font: str = DEFAULT_FONT
    title_fontsize: int = 16


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

    return TocLayout(
        text_font=resolve_font(toc_config.get("text-font", DEFAULT_FONT), DEFAULT_FONT),
        text_fontsize=toc_config.get("text-fontsize", 9),
        title_font=resolve_font(
            toc_config.get("title-font", DEFAULT_FONT), DEFAULT_FONT
        ),
        title_fontsize=toc_config.get("title-fontsize", 16),
    )


class TocGenerator:
    """Generates table of contents PDF with multi-column, multi-page layout."""

    def __init__(self, layout: TocLayout):
        self.layout = layout
        self.pdf = fitz.open()
        self.current_page = None
        self.current_column = 0
        self.current_line_in_column = 0
        self._column_positions = []
        self._lines_per_column = 0
        self.toc_entries = []  # Store entries for later link creation

    def _calculate_layout_parameters(self) -> None:
        """Calculate layout parameters based on page dimensions."""
        # Get page dimensions from a temporary page
        temp_page = self.pdf.new_page()
        page_height = temp_page.rect.height
        self.pdf.delete_page(0)  # Remove the temporary page

        available_height = (
            page_height - self.layout.title_height - (2 * self.layout.page_margin)
        )
        self._lines_per_column = int(available_height // self.layout.line_spacing)

        # Calculate column x positions
        self._column_positions = [
            self.layout.page_margin
            + col * (self.layout.column_width + self.layout.column_spacing)
            for col in range(self.layout.columns_per_page)
        ]

    def _create_new_page(self) -> fitz.Page:
        """Create a new page with title."""
        page = self.pdf.new_page()
        page.insert_text(
            (
                self.layout.page_margin,
                self.layout.page_margin + self.layout.title_height - 20,
            ),
            "Table of Contents",
            fontsize=self.layout.title_fontsize,
            fontfile=self.layout.title_font,
            color=(0, 0, 0),
        )
        return page

    def _get_current_position(self) -> Tuple[float, float]:
        """Get current x, y position for text insertion."""
        x = self._column_positions[self.current_column]
        y = (
            self.layout.title_height
            + self.layout.page_margin
            + (self.current_line_in_column * self.layout.line_spacing)
        )
        return x, y

    def _advance_position(self) -> None:
        """Advance to next line/column/page as needed."""
        self.current_line_in_column += 1

        # Check if we need to move to next column
        if self.current_line_in_column >= self._lines_per_column:
            self.current_column += 1
            self.current_line_in_column = 0

            # Check if we need to create a new page
            if self.current_column >= self.layout.columns_per_page:
                self.current_page = self._create_new_page()
                self.current_column = 0

    def _estimate_text_width(self, text: str) -> float:
        """Estimate the width of text based on font size."""
        # Rough estimation: assume each character is about 0.6 * fontsize width
        return len(text) * self.layout.text_fontsize * 0.6

    def generate(
        self, files: List[Dict[str, Any]], page_offset: int = 0
    ) -> fitz.Document:
        """Generate the table of contents PDF."""
        self._calculate_layout_parameters()
        self.current_page = self._create_new_page()

        for page_number, file in enumerate(files, start=(1 + page_offset)):
            file_name = file["name"]
            # Use the new function to generate a shortened title
            shortened_title = generate_toc_title(file_name)
            toc_text_line = f"{page_number}. {shortened_title}"

            # Insert text at current position
            x, y = self._get_current_position()
            self.current_page.insert_text(
                (x, y),
                toc_text_line,
                fontsize=self.layout.text_fontsize,
                fontfile=self.layout.text_font,
                color=(0, 0, 0),
            )

            # Store entry information for later link creation
            text_width = self._estimate_text_width(toc_text_line)
            text_height = self.layout.text_fontsize

            # Create rectangle for the clickable area
            link_rect = fitz.Rect(
                x,
                y - text_height * 0.8,  # Slightly above baseline
                x + text_width,
                y + text_height * 0.2,  # Slightly below baseline
            )

            # Target page is the file's position in the final PDF
            target_page = page_number - 1  # Convert to 0-based for PDF internal linking

            # Store the entry for later processing
            toc_entry = TocEntry(
                page_number=page_number,
                target_page=target_page,
                text=toc_text_line,
                rect=link_rect,
                toc_page_index=len(self.pdf) - 1,  # Current page index in TOC PDF
            )
            self.toc_entries.append(toc_entry)

            # Advance to next position
            self._advance_position()

        return self.pdf

    def get_toc_entries(self) -> List[TocEntry]:
        """Return the list of TOC entries for link creation."""
        return self.toc_entries


def build_table_of_contents(
    files: List[Dict[str, Any]], page_offset: int = 0
) -> Tuple[fitz.Document, List[TocEntry]]:
    """Build a table of contents PDF from a list of files.

    Returns:
        Tuple of (TOC PDF document, list of TOC entries for link creation)
    """
    layout = load_toc_config()
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
    for entry in toc_entries:
        # Get the TOC page in the merged PDF
        toc_page_index = toc_page_offset + entry.toc_page_index
        if toc_page_index >= len(merged_pdf):
            continue

        toc_page = merged_pdf[toc_page_index]

        # Calculate the target page in the merged PDF
        target_page_index = toc_page_offset + len(toc_entries) + entry.target_page
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
