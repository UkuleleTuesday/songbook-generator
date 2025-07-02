import click
import fitz  # PyMuPDF

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


# Load configuration for TOC
def load_toc_config():
    config = load_config()
    return (
        resolve_font(
            config.get("toc", {}).get("text-font", DEFAULT_FONT), DEFAULT_FONT
        ),
        config.get("toc", {}).get("text-fontsize", 9),
        resolve_font(
            config.get("toc", {}).get("title-font", DEFAULT_FONT), DEFAULT_FONT
        ),
        config.get("toc", {}).get("title-fontsize", 16),
    )


def build_table_of_contents(files, page_offset=0):
    toc_pdf = fitz.open()
    toc_entries = []

    # Layout configuration
    columns_per_page = 2
    column_width = 250
    column_spacing = 20
    page_margin = 50
    title_height = 50
    line_spacing = 10

    toc_font, toc_fontsize, title_font, title_fontsize = load_toc_config()

    # Calculate layout parameters
    page_width = toc_pdf.new_page().rect.width
    page_height = toc_pdf.new_page().rect.height
    toc_pdf.close()  # Close the temporary PDF

    # Reopen and start fresh
    toc_pdf = fitz.open()

    available_height = page_height - title_height - (2 * page_margin)
    lines_per_column = int(available_height // line_spacing)

    # Calculate column positions
    column_x_positions = []
    for col in range(columns_per_page):
        x_pos = page_margin + col * (column_width + column_spacing)
        column_x_positions.append(x_pos)

    # Track current position
    current_page = None
    current_column = 0
    current_line_in_column = 0

    def create_new_page():
        page = toc_pdf.new_page()
        # Add title to page
        page.insert_text(
            (page_margin, page_margin + title_height - 10),
            "Table of Contents",
            fontsize=title_fontsize,
            fontfile=title_font,
            color=(0, 0, 0),
        )
        return page

    def get_current_y_position():
        return title_height + page_margin + (current_line_in_column * line_spacing)

    def advance_position():
        nonlocal current_page, current_column, current_line_in_column

        current_line_in_column += 1

        # Check if we need to move to next column
        if current_line_in_column >= lines_per_column:
            current_column += 1
            current_line_in_column = 0

            # Check if we need to create a new page
            if current_column >= columns_per_page:
                current_page = create_new_page()
                current_column = 0

    # Start with first page
    current_page = create_new_page()

    # Process each file
    for page_number, file in enumerate(files, start=(1 + page_offset)):
        file_name = file["name"]
        toc_text_line = f"{page_number}. {file_name}"
        toc_entries.append([1, file_name, page_number])

        # Insert text at current position
        current_x = column_x_positions[current_column]
        current_y = get_current_y_position()

        current_page.insert_text(
            (current_x, current_y),
            toc_text_line,
            fontsize=toc_fontsize,
            fontfile=toc_font,
            color=(0, 0, 0),
        )

        # Advance to next position
        advance_position()

    return toc_pdf
