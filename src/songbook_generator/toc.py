import toml
import os
import click
import fitz  # PyMuPDF


# Load configuration for TOC
def load_toc_config():
    config_path = os.path.expanduser("~/.config/songbook-generator/config.toml")
    if os.path.exists(config_path):
        config = toml.load(config_path)
        return (
            config.get("toc", {}).get("font", "/usr/share/fonts/truetype/msttcorefonts/Verdana.ttf"),
            config.get("toc", {}).get("fontsize", 9),
            config.get("toc", {}).get("title-font", "/usr/share/fonts/truetype/msttcorefonts/Verdana.ttf"),
            config.get("toc", {}).get("title-fontsize", 16),
        )
    return "helv", 9


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
        file_name = file['name']
        toc_text_line = f"{page_number}. {file_name}"
        toc_entries.append([1, file_name, page_number])
        try:
            toc_page.insert_text((current_x, current_y), toc_text_line, fontsize=toc_fontsize, fontfile=toc_font, color=(0, 0, 0))
        except Exception as e:
            click.echo(f"Warning: Failed to load font '{toc_font}'. Falling back to default font 'helv'. Error: {e}")
            toc_page.insert_text((current_x, current_y), toc_text_line, fontsize=9, fontname="helv", color=(0, 0, 0))
        if current_y > column_height:  # Move to next column if overspills
            current_y = 50
            current_x += column_width + column_spacing

    try:
        try:
            toc_page.insert_text((50, 50), toc_text, fontsize=title_fontsize, fontfile=title_font, color=(0, 0, 0))
        except Exception as e:
            click.echo(f"Warning: Failed to load title font '{title_font}'. Falling back to default font 'helv'. Error: {e}")
            toc_page.insert_text((50, 50), toc_text, fontsize=title_fontsize, fontname="helv", color=(0, 0, 0))
    except Exception as e:
        click.echo(f"Warning: Failed to load font '{toc_font}'. Falling back to default font 'helv'. Error: {e}")
        toc_page.insert_text((50, 50), toc_text, fontsize=16, fontname="helv", color=(0, 0, 0))
    toc_pdf.set_toc(toc_entries)
    return toc_pdf
