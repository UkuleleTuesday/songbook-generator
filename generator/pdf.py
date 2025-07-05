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
    get_files_metadata_by_ids,
)
from filters import PropertyFilter, FilterGroup

# Import tracing - only if running in cloud environment
try:
    from common.tracing import get_tracer

    tracer = get_tracer(__name__)
except ImportError:
    # Running locally (CLI), create a no-op tracer
    class NoOpTracer:
        def start_as_current_span(self, name):
            return NoOpSpan()

    class NoOpSpan:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def set_attribute(self, key, value):
            pass

    tracer = NoOpTracer()


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
    with tracer.start_as_current_span("collect_and_sort_files") as span:
        span.set_attribute("source_folders_count", len(source_folders))
        span.set_attribute("filter", client_filter)

        files = []
        for folder_index, folder in enumerate(source_folders):
            with tracer.start_as_current_span("query_gdrive_folder") as folder_span:
                folder_span.set_attribute("folder_id", folder)
                folder_span.set_attribute("filter", client_filter)
                folder_files = query_drive_files_with_client_filter(
                    drive, folder, client_filter
                )
                files.extend(folder_files)
                folder_span.set_attribute("files_found", len(folder_files))

                if progress_step:
                    progress_step.increment(
                        1 / len(source_folders),
                        f"Found {len(folder_files)} files in folder {folder_index + 1}: {folder}",
                    )

        # Sort files alphabetically by name after aggregating from all folders
        files.sort(key=lambda f: f["name"])
        span.set_attribute("total_files_found", len(files))
        return files


def generate_songbook(
    source_folders: List[str],
    destination_path: Path,
    limit: int,
    cover_file_id: str,
    client_filter: Optional[Union[PropertyFilter, FilterGroup]] = None,
    preface_file_ids: Optional[List[str]] = None,
    postface_file_ids: Optional[List[str]] = None,
    on_progress=None,
):
    with tracer.start_as_current_span("generate_songbook") as span:
        span.set_attribute("source_folders_count", len(source_folders))
        span.set_attribute("destination_path", str(destination_path))
        if limit:
            span.set_attribute("limit", limit)
        if cover_file_id:
            span.set_attribute("cover_file_id", cover_file_id)
        if preface_file_ids:
            span.set_attribute("preface_files_count", len(preface_file_ids))
        if postface_file_ids:
            span.set_attribute("postface_files_count", len(postface_file_ids))

        reporter = progress.ProgressReporter(on_progress)

        with reporter.step(1, "Initializing cache..."):
            with tracer.start_as_current_span("init_cache"):
                cache = caching.init_cache()

        with reporter.step(1, "Authenticating with Google Drive..."):
            with tracer.start_as_current_span("authenticate_drive"):
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

        span.set_attribute("final_files_count", len(files))

        # Get preface and postface files
        preface_files = []
        postface_files = []

        if preface_file_ids:
            with reporter.step(1, "Retrieving preface files...") as step:
                with tracer.start_as_current_span("get_preface_files") as preface_span:
                    preface_files = get_files_metadata_by_ids(
                        drive, preface_file_ids, step
                    )
                    preface_span.set_attribute(
                        "preface_files_retrieved", len(preface_files)
                    )
                    click.echo(f"Found {len(preface_files)} preface files.")

        if postface_file_ids:
            with reporter.step(1, "Retrieving postface files...") as step:
                with tracer.start_as_current_span(
                    "get_postface_files"
                ) as postface_span:
                    postface_files = get_files_metadata_by_ids(
                        drive, postface_file_ids, step
                    )
                    postface_span.set_attribute(
                        "postface_files_retrieved", len(postface_files)
                    )
                    click.echo(f"Found {len(postface_files)} postface files.")

        click.echo("Merging downloaded PDFs into a single master PDF...")

        # Load environment variable for page numbering
        add_page_numbers = (
            os.getenv("GENERATOR_ADD_PAGE_NUMBERS", "true").lower() == "true"
        )
        span.set_attribute("add_page_numbers", add_page_numbers)

        with tracer.start_as_current_span("create_songbook_pdf") as pdf_span:
            with fitz.open() as songbook_pdf:
                # We need to calculate TOC size first to properly set page offsets
                with reporter.step(1, "Pre-calculating table of contents..."):
                    with tracer.start_as_current_span("precalculate_toc"):
                        toc_pdf, toc_entries = toc.build_table_of_contents(
                            files, 0
                        )  # Temporary offset
                        toc_page_count = len(toc_pdf)
                        toc_pdf.close()  # Close temporary TOC

                # Calculate page offset based on cover + preface pages + TOC pages
                page_offset = 1 + len(preface_files) + toc_page_count
                pdf_span.set_attribute("page_offset", page_offset)

                with reporter.step(1, "Generating cover..."):
                    with tracer.start_as_current_span("generate_cover"):
                        cover_pdf = cover.generate_cover(drive, cache, cover_file_id)
                        songbook_pdf.insert_pdf(cover_pdf, start_at=0)

                # Add preface files after cover
                if preface_files:
                    with reporter.step(
                        len(preface_files), "Adding preface files..."
                    ) as step:
                        with tracer.start_as_current_span(
                            "add_preface_files"
                        ) as preface_span:
                            for file in preface_files:
                                with (
                                    download_file_stream(
                                        drive, file, cache
                                    ) as pdf_stream,
                                    fitz.open(stream=pdf_stream) as pdf_document,
                                ):
                                    songbook_pdf.insert_pdf(
                                        pdf_document,
                                        from_page=0,
                                        to_page=0,
                                        links=False,
                                        annots=False,
                                        widgets=False,
                                        final=0,
                                    )
                                    step.increment(1, f"Added preface: {file['name']}")
                            preface_span.set_attribute(
                                "preface_files_added", len(preface_files)
                            )

                # Generate TOC with correct page offset
                with reporter.step(1, "Generating table of contents..."):
                    with tracer.start_as_current_span("generate_toc"):
                        toc_pdf, toc_entries = toc.build_table_of_contents(
                            files, page_offset
                        )
                        toc_start_page = len(songbook_pdf)  # Remember where TOC starts
                        songbook_pdf.insert_pdf(toc_pdf)

                with reporter.step(
                    len(files), "Downloading and merging PDFs..."
                ) as step:
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

                # Add postface files at the end
                if postface_files:
                    with reporter.step(
                        len(postface_files), "Adding postface files..."
                    ) as step:
                        with tracer.start_as_current_span(
                            "add_postface_files"
                        ) as postface_span:
                            for i, file in enumerate(postface_files):
                                with (
                                    download_file_stream(
                                        drive, file, cache
                                    ) as pdf_stream,
                                    fitz.open(stream=pdf_stream) as pdf_document,
                                ):
                                    is_last_postface = i == len(postface_files) - 1
                                    final_value = 1 if is_last_postface else 0

                                    if final_value == 1:
                                        print(
                                            f"Passing final=1 for last postface file: {file['name']}"
                                        )

                                    songbook_pdf.insert_pdf(
                                        pdf_document,
                                        from_page=0,
                                        to_page=0,
                                        links=False,
                                        annots=False,
                                        widgets=False,
                                        final=final_value,
                                    )
                                    step.increment(1, f"Added postface: {file['name']}")
                            postface_span.set_attribute(
                                "postface_files_added", len(postface_files)
                            )

                # Add TOC links after all content is in place
                with reporter.step(1, "Adding table of contents links..."):
                    with tracer.start_as_current_span("add_toc_links"):
                        toc.add_toc_links_to_merged_pdf(
                            songbook_pdf, toc_entries, toc_start_page
                        )

                with reporter.step(1, "Exporting generated PDF..."):
                    with tracer.start_as_current_span("save_pdf") as save_span:
                        songbook_pdf.save(destination_path)  # Save the merged PDF
                        save_span.set_attribute(
                            "output_file_size", os.path.getsize(destination_path)
                        )
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
    with tracer.start_as_current_span("merge_pdfs") as span:
        span.set_attribute("files_count", len(files))
        span.set_attribute("batch_size", batch_size)
        span.set_attribute("add_page_numbers", add_page_numbers)

        current_page = 1 + page_offset
        total_files = len(files)

        for batch_index, batch in enumerate(batched(files, batch_size)):
            with tracer.start_as_current_span("process_pdf_merge_batch") as batch_span:
                batch_span.set_attribute("batch_size", len(batch))
                batch_span.set_attribute("batch_index", batch_index)

                for file in batch:
                    with (
                        download_file_stream(drive, file, cache) as pdf_stream,
                        fitz.open(stream=pdf_stream) as pdf_document,
                    ):
                        if add_page_numbers:
                            add_page_number(pdf_document[0], current_page)

                        # Determine if this is the last file overall
                        file_index = current_page - page_offset - 1
                        is_last_file = file_index == total_files - 1

                        final_value = 1 if is_last_file else 0
                        if final_value == 1:
                            print(f"Passing final=1 for last file: {file['name']}")

                        destination_pdf.insert_pdf(
                            pdf_document,
                            from_page=0,
                            to_page=0,
                            links=False,
                            annots=False,
                            widgets=False,
                            final=final_value,
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
