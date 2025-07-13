import fitz
import click
import os
from opentelemetry import trace
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


def init_services():
    """Initializes and authenticates services, logging auth details."""
    main_span = trace.get_current_span()

    with tracer.start_as_current_span("init_services"):
        drive, creds = authenticate_drive()
        cache = caching.init_cache()

        click.echo("Authentication Details:")
        if hasattr(creds, "service_account_email"):
            auth_type = "Service Account"
            email = creds.service_account_email
            click.echo(f"  Type: {auth_type}")
            click.echo(f"  Email: {email}")
            main_span.set_attribute("auth.type", auth_type)
            main_span.set_attribute("auth.email", email)
        elif hasattr(creds, "token"):
            auth_type = "User Credentials"
            click.echo(f"  Type: {auth_type}")
            try:
                about = drive.about().get(fields="user").execute()
                user_info = about.get("user")
                if user_info:
                    user_name = user_info.get("displayName")
                    email = user_info.get("emailAddress")
                    click.echo(f"  User: {user_name}")
                    click.echo(f"  Email: {email}")
                    main_span.set_attribute("auth.type", auth_type)
                    main_span.set_attribute("auth.email", email)
                    main_span.set_attribute("auth.user", user_name)
            except Exception as e:
                click.echo(f"  Could not retrieve user info: {e}")
        else:
            click.echo(f"  Type: {type(creds)}")
        click.echo(f"  Scopes: {creds.scopes}")
        main_span.set_attribute("auth.scopes", str(creds.scopes))
        return drive, cache


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
        span.set_attribute(
            "source_folders_count", len(source_folders) if source_folders else 0
        )
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


def copy_pdfs(
    destination_pdf,
    files,
    cache,
    page_offset,
    progress_step,
    add_page_numbers=True,
):
    """
    Copy pages from the merged PDF cache based on TOC entries for the selected files.

    Args:
        destination_pdf: PyMuPDF document to copy pages to
        files: List of file dictionaries with metadata
        cache: Cache instance for accessing the merged PDF
        page_offset: Starting page offset for numbering
        progress_step: Progress reporter
        add_page_numbers: Whether to add page numbers
    """
    with tracer.start_as_current_span("copy_pdfs") as span:
        files_count = len(files)
        span.set_attribute("files_count", files_count)
        span.set_attribute("add_page_numbers", add_page_numbers)

        # Try to get the cached merged PDF
        try:
            cached_pdf_data = cache.get("merged-pdf/latest.pdf")
            if not cached_pdf_data:
                span.set_attribute("cache_miss", True)
                raise ValueError("Cached merged PDF not found")

            span.set_attribute("cache_hit", True)
            span.set_attribute("cached_pdf_size", len(cached_pdf_data))

            # Open the cached merged PDF
            with fitz.open(stream=cached_pdf_data) as cached_pdf:
                cached_toc = cached_pdf.get_toc()
                span.set_attribute("cached_toc_entries", len(cached_toc))

                if not cached_toc:
                    span.set_attribute("no_toc", True)
                    raise ValueError("Cached PDF has no table of contents")

                # Create a mapping from song names to TOC entries
                toc_map = {}
                for level, title, page_num in cached_toc:
                    # Page numbers in TOC are 1-based, convert to 0-based
                    toc_map[title] = page_num - 1

                current_page = page_offset
                copied_pages = 0

                for file_number, file in enumerate(files):
                    file_name = file["name"]

                    # Look for this file in the cached PDF's TOC
                    if file_name in toc_map:
                        source_page = toc_map[file_name]

                        # Determine how many pages this song has
                        # Find the next song's page or use the last page
                        next_page = len(cached_pdf)  # Default to end of document
                        current_toc_index = None

                        # Find current song in TOC to determine page range
                        for i, (level, title, page_num) in enumerate(cached_toc):
                            if title == file_name:
                                current_toc_index = i
                                break

                        if (
                            current_toc_index is not None
                            and current_toc_index + 1 < len(cached_toc)
                        ):
                            # Get the page number of the next song (convert from 1-based to 0-based)
                            next_page = cached_toc[current_toc_index + 1][2] - 1

                        page_count = next_page - source_page

                        # Copy the pages for this song
                        for page_offset_in_song in range(page_count):
                            source_page_num = source_page + page_offset_in_song
                            if source_page_num < len(cached_pdf):
                                page = cached_pdf[source_page_num]

                                # Create new page in destination
                                dest_page = destination_pdf.new_page(
                                    width=page.rect.width, height=page.rect.height
                                )
                                dest_page.show_pdf_page(
                                    dest_page.rect, cached_pdf, source_page_num
                                )

                                # Add page number if requested and it's the first page of the song
                                if add_page_numbers and page_offset_in_song == 0:
                                    add_page_number(dest_page, current_page + 1)

                                copied_pages += 1

                        current_page += page_count
                        progress_step.increment(
                            1, f"Copied song sheet {file_number}/{files_count}..."
                        )
                    else:
                        print(f"Warning: {file_name} not found in cached PDF TOC")
                        progress_step.increment(
                            1, f"Skipped {file_name} (not in cache)"
                        )

                span.set_attribute("copied_pages", copied_pages)
                span.set_attribute("final_page_count", current_page)

        except Exception as e:
            span.set_attribute("copy_error", str(e))
            print(f"Error copying from cached PDF: {e}")
            raise


def generate_songbook(
    drive,
    cache,
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
                f"Found {len(files)} files in the source folder{filter_msg}{limit_msg}. Starting generation..."
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

        click.echo("Generating songbook PDF...")

        # Load environment variable for page numbering
        add_page_numbers = (
            os.getenv("GENERATOR_ADD_PAGE_NUMBERS", "true").lower() == "true"
        )
        span.set_attribute("add_page_numbers", add_page_numbers)

        # Try to use cached merged PDF first, fall back to individual downloads
        use_cache = True
        try:
            # Quick check if cached PDF is available
            cached_pdf_data = cache.get("merged-pdf/latest.pdf")
            if not cached_pdf_data:
                use_cache = False
                click.echo(
                    "Cached merged PDF not found, falling back to individual file downloads"
                )
        except Exception as e:
            use_cache = False
            click.echo(
                f"Error accessing cached PDF: {e}, falling back to individual file downloads"
            )

        span.set_attribute("use_cached_pdf", use_cache)

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

                # Add main content - try cached approach first, fall back to individual downloads
                if use_cache:
                    with reporter.step(
                        len(files), "Copying from cached PDF..."
                    ) as step:
                        try:
                            copy_pdfs(
                                songbook_pdf,
                                files,
                                cache,
                                page_offset,
                                step,
                                add_page_numbers=add_page_numbers,
                            )
                        except Exception as e:
                            click.echo(f"Failed to copy from cached PDF: {e}")
                            click.echo("Falling back to individual file downloads...")
                            # Fall back to merge_pdfs if copy_pdfs fails
                            use_cache = False

                if not use_cache:
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
    """
    Fallback method: Download and merge individual PDF files.

    This is used when the cached merged PDF is not available or copy_pdfs fails.
    """
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
