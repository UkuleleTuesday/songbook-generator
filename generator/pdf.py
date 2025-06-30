import fitz
import click
import os

import pdf
import toc
import cover
from gdrive import authenticate_drive, query_drive_files, download_files


def generate_songbook(source_folder: str, limit: int, cover_file_id: str):
    drive = authenticate_drive()
    click.echo("Authenticating with Google Drive...")
    files = []
    for folder in source_folder:
        files.extend(query_drive_files(drive, folder, limit))
    if not files:
        click.echo(f"No files found in folder {source_folder}.")
        return
    cache_dir = os.path.join(
        os.path.expanduser("~/.cache"), "songbook-generator", "cache"
    )
    os.makedirs(cache_dir, exist_ok=True)
    click.echo(f"Found {len(files)} files in the source folder. Starting download...")
    song_sheets_dir = os.path.join(cache_dir, "song-sheets")
    os.makedirs(song_sheets_dir, exist_ok=True)
    pdf_paths = download_files(drive, files, song_sheets_dir)
    click.echo("Merging downloaded PDFs into a single master PDF...")
    merged_pdf = pdf.merge_pdfs(pdf_paths, files, cache_dir, drive)
    toc_pdf = toc.build_table_of_contents(files)
    merged_pdf.insert_pdf(toc_pdf, start_at=0)
    cover_pdf = cover.generate_cover(drive, cache_dir, cover_file_id)
    merged_pdf.insert_pdf(cover_pdf, start_at=0)

    try:
        master_pdf_path = os.path.join(cache_dir, "master.pdf")
        merged_pdf.save(master_pdf_path)  # Save the merged PDF
        if not os.path.exists(master_pdf_path):
            raise FileNotFoundError(f"Failed to save master PDF at {master_pdf_path}")
    except Exception as e:
        click.echo(f"Error saving master PDF: {e}")
        return None
    return master_pdf_path


def merge_pdfs(pdf_paths, files, cache_dir, drive):
    merged_pdf = fitz.open()

    for pdf_path in pdf_paths:
        pdf_document = fitz.open(pdf_path)
        merged_pdf.insert_pdf(pdf_document)
    for page_number in range(len(merged_pdf)):
        page = merged_pdf[page_number]
        text = str(page_number + 1)
        x = page.rect.width - 50
        y = 30
        page.insert_text((x, y), text, fontsize=9, color=(0, 0, 0))

    return merged_pdf
