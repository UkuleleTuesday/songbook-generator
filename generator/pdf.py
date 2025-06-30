import fitz
import click
import os
from pathlib import Path

import toc
import cover
from caching.localstorage import LocalStorageCache
from gdrive import authenticate_drive, query_drive_files, stream_file_bytes

from typing import List

LOCAL_CACHE_DIR = os.path.join(os.path.expanduser("~/.cache"), "songbook-generator")


def generate_songbook(
    source_folders: List[str], destination_path: Path, limit: int, cover_file_id: str
):
    click.echo(f"Using cache dir: {LOCAL_CACHE_DIR}")
    drive = authenticate_drive()
    cache = LocalStorageCache(LOCAL_CACHE_DIR)
    click.echo("Authenticating with Google Drive...")
    files = []
    for folder in source_folders:
        files.extend(query_drive_files(drive, folder, limit))
    if not files:
        click.echo(f"No files found in folders {source_folders}.")
        return
    click.echo(f"Found {len(files)} files in the source folder. Starting download...")
    click.echo("Merging downloaded PDFs into a single master PDF...")
    with fitz.open() as songbook_pdf:
        merge_pdfs(songbook_pdf, files, cache, drive)
        toc_pdf = toc.build_table_of_contents(files)
        songbook_pdf.insert_pdf(toc_pdf, start_at=0)
        cover_pdf = cover.generate_cover(drive, cache, cover_file_id)
        songbook_pdf.insert_pdf(cover_pdf, start_at=0)

        songbook_pdf.save(destination_path)  # Save the merged PDF
        if not os.path.exists(destination_path):
            raise FileNotFoundError(f"Failed to save master PDF at {destination_path}")


def merge_pdfs(destination_pdf, files, cache, drive):
    for pdf_bytes in stream_file_bytes(drive, files, cache):
        with fitz.open(stream=pdf_bytes) as pdf_document:
            destination_pdf.insert_pdf(pdf_document)
    for page_number in range(len(destination_pdf)):
        page = destination_pdf[page_number]
        text = str(page_number + 1)
        x = page.rect.width - 50
        y = 30
        page.insert_text((x, y), text, fontsize=9, color=(0, 0, 0))

    return destination_pdf
