import fitz
import click
import os
from pathlib import Path
import progress

import toc
import cover
from caching.localstorage import LocalStorageCache
from fsspec.implementations.local import LocalFileSystem
import gcsfs
from gdrive import authenticate_drive, query_drive_files, stream_file_bytes

from typing import List

LOCAL_CACHE_DIR = os.path.join(os.path.expanduser("~/.cache"), "songbook-generator")


def init_cache():
    if os.getenv("GCS_CACHE_BUCKET") and os.getenv("GCS_CACHE_REGION"):
        bucket = os.getenv("GCS_CACHE_BUCKET")
        region = os.getenv("GCS_CACHE_REGION")
        click.echo(f"Using GCS as cache: {bucket} {region}")
        return LocalStorageCache(gcsfs.GCSFileSystem(default_location=region), bucket)
    else:
        click.echo(f"Using cache dir: {LOCAL_CACHE_DIR}")
        return LocalStorageCache(LocalFileSystem(), LOCAL_CACHE_DIR)


def generate_songbook(
    source_folders: List[str], destination_path: Path, limit: int, cover_file_id: str, on_progress=None
):
    cache = init_cache()
    drive = authenticate_drive()
    click.echo("Authenticating with Google Drive...")
    files = []
    for folder in source_folders:
        files.extend(query_drive_files(drive, folder, limit))
    if not files:
        click.echo(f"No files found in folders {source_folders}.")
        return
    click.echo(f"Found {len(files)} files in the source folder. Starting download...")
    click.echo("Merging downloaded PDFs into a single master PDF...")
    total_progress = 10 + len(files) + 5 + 10 + 10
    reporter = progress.ProgressReporter(total_progress, on_progress)
    with fitz.open() as songbook_pdf:
        for file, _ in zip(files, merge_pdfs(songbook_pdf, files, cache, drive)):
            reporter.increment_progress(
                1, f"Adding {file['name']}"
            )
        reporter.increment_progress(
            5, "Adding page numbers..."
        )
        add_page_numbers(songbook_pdf)
        reporter.increment_progress(
            5, "Generating TOC..."
        )
        toc_pdf = toc.build_table_of_contents(files)
        songbook_pdf.insert_pdf(toc_pdf, start_at=0)
        reporter.increment_progress(
            5, "Generating cover..."
        )
        cover_pdf = cover.generate_cover(drive, cache, cover_file_id)
        songbook_pdf.insert_pdf(cover_pdf, start_at=0)
        reporter.increment_progress(
            5, "Exporting generated PDF..."
        )

        songbook_pdf.save(destination_path)  # Save the merged PDF
        if not os.path.exists(destination_path):
            raise FileNotFoundError(f"Failed to save master PDF at {destination_path}")


def merge_pdfs(destination_pdf, files, cache, drive, on_progress=None):
    for i, pdf_bytes in enumerate(stream_file_bytes(drive, files, cache), start=1):
        with fitz.open(stream=pdf_bytes) as pdf_document:
            destination_pdf.insert_pdf(pdf_document)
        yield i


def add_page_numbers(destination_pdf):
    for page_number in range(len(destination_pdf)):
        page = destination_pdf[page_number]
        text = str(page_number + 1)
        x = page.rect.width - 50
        y = 30
        page.insert_text((x, y), text, fontsize=9, color=(0, 0, 0))
