import toml
import os
import click
import fitz  # PyMuPDF

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
        fitz.Font(fontfile=fontfile)
        return fontfile
    except Exception as e:
        click.echo(f"Warning: Failed to load fontfile '{fontfile}'. Falling back to default font '{fallback_font}'. Error: {e}")
        return fallback_font


# Load configuration for TOC
def load_toc_config():
    config_path = os.path.expanduser("~/.config/songbook-generator/config.toml")
    if os.path.exists(config_path):
        config = toml.load(config_path)
    else:
        config = toml.loads("")
    return (
        resolve_font(config.get("toc", {}).get("text-font", DEFAULT_FONT), DEFAULT_FONT),
        config.get("toc", {}).get("text-fontsize", 9),
        resolve_font(config.get("toc", {}).get("title-font", DEFAULT_FONT), DEFAULT_FONT),
        config.get("toc", {}).get("title-fontsize", 16),
    )


def build_table_of_contents(files):
    toc_pdf = fitz.open()
    toc_page = toc_pdf.new_page()
    toc_text = "Table of Contents\n\n"
    toc_entries = []
    column_width = 250  # Width of each column
    column_spacing = 20  # Space between columns
    column_height = toc_page.rect.height - 25  # Adjust for margins
    current_y = 50
    current_x = 50

    toc_font, toc_fontsize, title_font, title_fontsize = load_toc_config()

    current_y += 10
    for page_number, file in enumerate(files, start=1):
        current_y += 10  # Line spacing
        file_name = file["name"]
        toc_text_line = f"{page_number}. {file_name}"
        toc_entries.append([1, file_name, page_number])
        toc_page.insert_text(
            (current_x, current_y),
            toc_text_line,
            fontsize=toc_fontsize,
            fontfile=toc_font,
            color=(0, 0, 0),
        )
        if current_y > column_height:  # Move to next column if overspills
            current_y = 50
            current_x += column_width + column_spacing

    toc_page.insert_text(
        (50, 50),
        toc_text,
        fontsize=title_fontsize,
        fontfile=title_font,
        color=(0, 0, 0),
    )
    return toc_pdf
