import fitz
import click
import os
import gc
from pathlib import Path
from typing import List, Optional, Union
from itertools import batched
import progress

import debug
import toc
import cover
import caching
from gdrive import (
    authenticate_drive,
    query_drive_files_with_client_filter,
    download_file_stream,
)
from filters import PropertyFilter, FilterGroup


def collect_and_sort_files(
    drive,
    source_folders: List[str],
    client_filter: Optional[Union[PropertyFilter, FilterGroup]] = None,
    progress_step=None,
):
    """
    Collect files from multiple Google Drive folders and sort them alphabetically by name.

    Args:
        drive: Authenticated Google Drive service
        source_folders: List of Google Drive folder IDs
        client_filter: Optional filter to apply to files
        progress_step: Optional progress step for reporting

    Returns:
        List of file dictionaries sorted alphabetically by name
    """
    files = []
    for i, folder in enumerate(source_folders):
        folder_files = query_drive_files_with_client_filter(
            drive, folder, client_filter
        )
        files.extend(folder_files)
        if progress_step:
            progress_step.increment(
                1 / len(source_folders),
                f"Found {len(folder_files)} files in folder {i + 1}",
            )

    # Sort files alphabetically by name after aggregating from all folders
    files.sort(key=lambda f: f["name"])
    return files


def generate_songbook(
    source_folders: List[str],
    destination_path: Path,
    limit: int,
    cover_file_id: str,
    client_filter: Optional[Union[PropertyFilter, FilterGroup]] = None,
    on_progress=None,
):
    reporter = progress.ProgressReporter(on_progress)

    with reporter.step(1, "Initializing cache..."):
        cache = caching.init_cache()

    with reporter.step(1, "Authenticating with Google Drive..."):
        drive = authenticate_drive()

    with reporter.step(1, "Querying files...") as step:
        files = collect_and_sort_files(drive, source_folders, client_filter, step)

        # Apply limit after collecting files from all folders
        if limit and len(files) > limit:
            click.echo(
                f"Limiting to {limit} files out of {len(files)} total files found"
            )
            files = files[:limit]

        if not files:
            if client_filter:
                click.echo(
                    f"No files found in folders {source_folders} matching client-side filter."
                )
            else:
                click.echo(f"No files found in folders {source_folders}.")
            return

        filter_msg = " (with client-side filter)" if client_filter else ""
        limit_msg = f" (limited to {limit})" if limit else ""
        click.echo(
            f"Found {len(files)} files in the source folder{filter_msg}{limit_msg}. Starting download..."
        )

    click.echo("Merging downloaded PDFs into a single master PDF...")

    # Load environment variable for page numbering
    add_page_numbers = os.getenv("GENERATOR_ADD_PAGE_NUMBERS", "true").lower() == "true"

    with fitz.open() as songbook_pdf:
        with reporter.step(1, "Generating table of contents..."):
            toc_pdf = toc.build_table_of_contents(files, 0)  # Use 0 temporarily for TOC generation
            songbook_pdf.insert_pdf(toc_pdf, start_at=0)

        with reporter.step(1, "Generating cover..."):
            cover_pdf = cover.generate_cover(drive, cache, cover_file_id)
            songbook_pdf.insert_pdf(cover_pdf, start_at=0)

        # Calculate page offset after cover and TOC have been inserted
        page_offset = len(songbook_pdf)

        # Regenerate TOC with correct page offset
        with reporter.step(
            1, "Updating table of contents with correct page numbers..."
        ):
            # Remove the old TOC
            songbook_pdf.delete_page(1)  # TOC was inserted at position 1 (after cover)
            # Generate new TOC with correct page offset
            toc_pdf = toc.build_table_of_contents(files, page_offset)
            songbook_pdf.insert_pdf(toc_pdf, start_at=1)

        with reporter.step(len(files), "Downloading and merging PDFs...") as step:
            merge_pdfs(
                songbook_pdf,
                files,
                cache,
                drive,
                page_offset,
                step,
                batch_size=20,
                add_page_numbers=add_page_numbers,
            )

        with reporter.step(1, "Exporting generated PDF..."):
            songbook_pdf.save(destination_path)  # Save the merged PDF
            if not os.path.exists(destination_path):
                raise FileNotFoundError(
                    f"Failed to save master PDF at {destination_path}"
                )


def merge_pdfs(
    destination_pdf,
    files,
    cache,
    drive,
    page_offset,
    progress_step,
    batch_size=20,
    add_page_numbers=True,
):
    current_page = 1 + page_offset

    for batch in batched(files, batch_size):
        for file in batch:
            with (
                download_file_stream(drive, file, cache) as pdf_stream,
                fitz.open(stream=pdf_stream) as pdf_document,
            ):
                if add_page_numbers:
                    add_page_number(pdf_document[0], current_page)

                destination_pdf.insert_pdf(
                    pdf_document, 
                    links=False, 
                    annots=False, 
                    widgets=False
                )
                progress_step.increment(1, f"Added {file['name']}")
                current_page += 1

        debug.log_resource_usage()
        gc.collect()  # Clean up after each batch


def add_page_number(page, page_index):
    text = str(page_index)
    x = page.rect.width - 50
    y = 30
    page.insert_text((x, y), text, fontsize=9, color=(0, 0, 0))
