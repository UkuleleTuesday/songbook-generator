import fitz
import click
import os
from pathlib import Path
import progress

import toc
import cover
import caching
from gdrive import authenticate_drive, query_drive_files, stream_file_bytes

from typing import List


def generate_songbook(
    source_folders: List[str],
    destination_path: Path,
    limit: int,
    cover_file_id: str,
    on_progress=None,
):
    reporter = progress.ProgressReporter(on_progress)

    with reporter.step(1, "Initializing cache..."):
        cache = caching.init_cache()

    with reporter.step(1, "Authenticating with Google Drive..."):
        drive = authenticate_drive()

    with reporter.step(1, "Querying files...") as step:
        files = []
        for i, folder in enumerate(source_folders):
            folder_files = query_drive_files(drive, folder, limit)
            files.extend(folder_files)
            step.increment(
                1 / len(source_folders),
                f"Found {len(folder_files)} files in folder {i + 1}",
            )

        if not files:
            click.echo(f"No files found in folders {source_folders}.")
            return

        click.echo(
            f"Found {len(files)} files in the source folder. Starting download..."
        )

    click.echo("Merging downloaded PDFs into a single master PDF...")

    with fitz.open() as songbook_pdf:
        with reporter.step(len(files), "Downloading and merging PDFs...") as step:
            for file, _ in zip(files, merge_pdfs(songbook_pdf, files, cache, drive)):
                step.increment(1, f"Added {file['name']}")

        with reporter.step(1, "Adding page numbers..."):
            add_page_numbers(songbook_pdf)

        with reporter.step(1, "Generating table of contents..."):
            toc_pdf = toc.build_table_of_contents(files)
            songbook_pdf.insert_pdf(toc_pdf, start_at=0)

        with reporter.step(1, "Generating cover..."):
            cover_pdf = cover.generate_cover(drive, cache, cover_file_id)
            songbook_pdf.insert_pdf(cover_pdf, start_at=0)

        with reporter.step(1, "Exporting generated PDF..."):
            songbook_pdf.save(destination_path)  # Save the merged PDF
            if not os.path.exists(destination_path):
                raise FileNotFoundError(
                    f"Failed to save master PDF at {destination_path}"
                )


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
