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
        # Calculate page offset after cover and TOC
        page_offset = 2
        with reporter.step(1, "Generating table of contents..."):
            toc_pdf = toc.build_table_of_contents(files, page_offset)
            songbook_pdf.insert_pdf(toc_pdf, start_at=0)

        with reporter.step(1, "Generating cover..."):
            cover_pdf = cover.generate_cover(drive, cache, cover_file_id)
            songbook_pdf.insert_pdf(cover_pdf, start_at=0)

        with reporter.step(len(files), "Downloading and merging PDFs...") as step:
            for file, _ in zip(
                files, merge_pdfs(songbook_pdf, files, cache, drive, page_offset)
            ):
                step.increment(1, f"Added {file['name']}")

        with reporter.step(1, "Exporting generated PDF..."):
            songbook_pdf.save(destination_path)  # Save the merged PDF
            if not os.path.exists(destination_path):
                raise FileNotFoundError(
                    f"Failed to save master PDF at {destination_path}"
                )


def merge_pdfs(destination_pdf, files, cache, drive, page_offset=0):
    for page_index, pdf_bytes in enumerate(
        stream_file_bytes(drive, files, cache), start=(1 + page_offset)
    ):
        with fitz.open(stream=pdf_bytes) as pdf_document:
            page = pdf_document[0]
            add_page_number(page, page_index)
            destination_pdf.insert_pdf(pdf_document)
            yield page_index


def add_page_number(page, page_index):
    text = str(page_index)
    x = page.rect.width - 50
    y = 30
    page.insert_text((x, y), text, fontsize=9, color=(0, 0, 0))
