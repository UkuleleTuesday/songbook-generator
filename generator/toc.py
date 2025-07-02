import click
import fitz  # PyMuPDF
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
        title_font=resolve_font(toc_config.get("title-font", DEFAULT_FONT), DEFAULT_FONT),
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
        
        available_height = (page_height - self.layout.title_height - 
                          (2 * self.layout.page_margin))
        self._lines_per_column = int(available_height // self.layout.line_spacing)
        
        # Calculate column x positions
        self._column_positions = [
            self.layout.page_margin + col * (self.layout.column_width + self.layout.column_spacing)
            for col in range(self.layout.columns_per_page)
        ]
    
    def _create_new_page(self) -> fitz.Page:
        """Create a new page with title."""
        page = self.pdf.new_page()
        page.insert_text(
            (self.layout.page_margin, self.layout.page_margin + self.layout.title_height - 10),
            "Table of Contents",
            fontsize=self.layout.title_fontsize,
            fontfile=self.layout.title_font,
            color=(0, 0, 0),
        )
        return page
    
    def _get_current_position(self) -> Tuple[float, float]:
        """Get current x, y position for text insertion."""
        x = self._column_positions[self.current_column]
        y = (self.layout.title_height + self.layout.page_margin + 
             (self.current_line_in_column * self.layout.line_spacing))
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
    
    def generate(self, files: List[Dict[str, Any]], page_offset: int = 0) -> fitz.Document:
        """Generate the table of contents PDF."""
        self._calculate_layout_parameters()
        self.current_page = self._create_new_page()
        
        for page_number, file in enumerate(files, start=(1 + page_offset)):
            file_name = file["name"]
            toc_text_line = f"{page_number}. {file_name}"
            
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


def build_table_of_contents(files: List[Dict[str, Any]], page_offset: int = 0) -> fitz.Document:
    """Build a table of contents PDF from a list of files."""
    layout = load_toc_config()
    generator = TocGenerator(layout)
    return generator.generate(files, page_offset)
