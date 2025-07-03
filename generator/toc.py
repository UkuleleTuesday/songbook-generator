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
        return title
    
    # Remove featuring information and version details in parentheses
    # Patterns like (feat. ...), (Radio Edit), (Single Version), etc.
    title = re.sub(r'\s*\([^)]*(?:feat\.|Radio|Single|Edit|Version|Mix|Remix)[^)]*\)', '', title, flags=re.IGNORECASE)
    
    # Remove other parenthetical information that might be version/format related
    title = re.sub(r'\s*\([^)]*\)\s*$', '', title)
    
    # Remove bracketed information
    title = re.sub(r'\s*\[[^\]]*\]', '', title, flags=re.IGNORECASE)
    
    # Clean up any extra whitespace
    title = re.sub(r'\s+', ' ', title).strip()
    
    # If still too long, truncate with ellipsis
    if len(title) > max_length:
        # Try to cut at a word boundary if possible
        if max_length > 3:
            truncate_length = max_length - 3  # Reserve space for "..."
            if ' ' in title[:truncate_length]:
                # Find the last space before the truncation point
                last_space = title[:truncate_length].rfind(' ')
                if last_space > max_length // 2:  # Only use word boundary if it's not too short
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

            # Advance to next position
            self._advance_position()

        return self.pdf


def build_table_of_contents(
    files: List[Dict[str, Any]], page_offset: int = 0
) -> fitz.Document:
    """Build a table of contents PDF from a list of files."""
    layout = load_toc_config()
    generator = TocGenerator(layout)
    return generator.generate(files, page_offset)
