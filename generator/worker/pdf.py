import fitz
import click
import os
from opentelemetry import trace
from pathlib import Path
from typing import List, Optional, Union
from . import progress
from . import toc
from . import cover
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from ..common import caching, config
from .gcp import get_credentials
from .exceptions import PdfCopyException, PdfCacheNotFound, PdfCacheMissException
from .filters import PropertyFilter, FilterGroup
from ..common.gdrive import (
    download_file_stream,
    get_files_metadata_by_ids,
    query_drive_files_with_client_filter,
)
from .models import File
from ..common.tracing import get_tracer
from natsort import natsorted
from unidecode import unidecode
import re

tracer = get_tracer(__name__)


def authenticate_drive(key_file_path: Optional[str] = None):
    """Authenticate with Google Drive API."""
    scopes = [
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/drive.metadata.readonly",
    ]
    creds = get_credentials(scopes, key_file_path)
    return build("drive", "v3", credentials=creds), creds


def init_services(
    key_file_path: Optional[str] = None,
    gcs_worker_cache_bucket: Optional[str] = None,
    local_cache_dir: Optional[str] = None,
):
    """Initializes and authenticates services, logging auth details."""
    main_span = trace.get_current_span()

    with tracer.start_as_current_span("init_services"):
        drive, creds = authenticate_drive(key_file_path)
        cache = caching.init_cache(
            gcs_worker_cache_bucket=gcs_worker_cache_bucket,
            local_cache_dir=local_cache_dir,
        )

        click.echo("Authentication Details:")
        # Check for service account first by looking for the 'account' attribute
        if hasattr(creds, "account") and creds.account:
            auth_type = "Service Account"
            email = creds.account
            click.echo(f"  Type: {auth_type}")
            click.echo(f"  Email: {email}")
            main_span.set_attribute("auth.type", auth_type)
            main_span.set_attribute("auth.email", email)
        # Then check for user credentials
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
            except HttpError as e:
                click.echo(f"  Could not retrieve user info: {e}")
        else:
            click.echo(f"  Type: {type(creds)}")
        click.echo(f"  Scopes: {creds.scopes}")
        main_span.set_attribute("auth.scopes", str(creds.scopes))
        return drive, cache


def _create_song_sort_key(file_obj: File) -> str:
    name = file_obj.name
    title = name.split(" - ")[0] if " - " in name else name
    title_no_accents = unidecode(title)
    title_no_punctuation = re.sub(r"[\W_]+", "", title_no_accents)
    return title_no_punctuation.lower()


def _sort_titles(files: List[File]) -> List[File]:
    return natsorted(files, key=_create_song_sort_key)


def collect_and_sort_files(
    drive,
    source_folders: List[str],
    client_filter: Optional[Union[PropertyFilter, FilterGroup]] = None,
    progress_step=None,
) -> List[File]:
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
        sorted_files = _sort_titles(files)
        span.set_attribute("total_files_found", len(files))
        return sorted_files


def copy_pdfs(
    destination_pdf,
    files: List[File],
    cache,
    page_offset,
    progress_step,
    add_page_numbers=True,
    toc_page_index: int = 0,
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
        cached_pdf_data = cache.get("merged-pdf/latest.pdf")
        if not cached_pdf_data:
            span.set_attribute("cache_miss", True)
            raise PdfCacheNotFound("Cached merged PDF not found")

        span.set_attribute("cache_hit", True)
        span.set_attribute("cached_pdf_size", len(cached_pdf_data))

        # Open the cached merged PDF
        with fitz.open(stream=cached_pdf_data) as cached_pdf:
            cached_toc = cached_pdf.get_toc()
            span.set_attribute("cached_toc_entries", len(cached_toc))

            if not cached_toc:
                span.set_attribute("no_toc", True)
                raise PdfCopyException("Cached PDF has no table of contents")

            # Create a mapping from song names to TOC entries
            toc_map = {}
            for level, title, page_num in cached_toc:
                # Page numbers in TOC are 1-based, convert to 0-based
                toc_map[title] = page_num - 1

            current_page = page_offset
            copied_pages = 0

            for file_number, file in enumerate(files):
                # Look for this file in the cached PDF's TOC
                if file.name not in toc_map:
                    raise PdfCacheMissException(f"File ${file.name} not found in cache")

                source_page = toc_map[file.name]

                # Determine how many pages this song has
                # Find the next song's page or use the last page
                next_page = len(cached_pdf)  # Default to end of document
                current_toc_index = None

                # Find current song in TOC to determine page range
                for i, (level, title, page_num) in enumerate(cached_toc):
                    if title == file.name:
                        current_toc_index = i
                        break

                if current_toc_index is not None and current_toc_index + 1 < len(
                    cached_toc
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

                        # On the first page of the song, add a link from the title to the TOC
                        if page_offset_in_song == 0:
                            # Use the full filename as the song title for searching
                            song_title = file.name

                            # Search for the title on the page
                            text_instances = dest_page.search_for(song_title)

                            if text_instances:
                                # Add a link over the first occurrence of the title
                                link_rect = text_instances[0]
                                dest_page.insert_link(
                                    {
                                        "kind": fitz.LINK_GOTO,
                                        "from": link_rect,
                                        "page": toc_page_index,
                                    }
                                )

                        copied_pages += 1

                current_page += page_count
                progress_step.increment(
                    1, f"Copied song sheet {file_number}/{files_count}..."
                )

            span.set_attribute("copied_pages", copied_pages)
            span.set_attribute("final_page_count", current_page)


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

        with tracer.start_as_current_span("create_songbook_pdf") as pdf_span:
            with fitz.open() as songbook_pdf:
                # Generate cover first to know if we need to adjust page offset
                with reporter.step(1, "Generating cover..."):
                    with tracer.start_as_current_span("generate_cover"):
                        cover_creds = get_credentials(
                            scopes=[
                                "https://www.googleapis.com/auth/documents",
                                "https://www.googleapis.com/auth/drive",
                            ]
                        )
                        docs_write_service = build(
                            "docs", "v1", credentials=cover_creds
                        )
                        drive_write_service = build(
                            "drive", "v3", credentials=cover_creds
                        )
                        cover_generator = cover.CoverGenerator(
                            cache,
                            drive_write_service,
                            docs_write_service,
                            cover_config=config.get_settings().cover,
                        )
                        cover_pdf = cover_generator.generate_cover(cover_file_id)

                # We need to calculate TOC size first to properly set page offsets
                with reporter.step(1, "Pre-calculating table of contents..."):
                    with tracer.start_as_current_span("precalculate_toc"):
                        toc_pdf, toc_entries = toc.build_table_of_contents(
                            files, 0
                        )  # Temporary offset
                        toc_page_count = len(toc_pdf)
                        toc_pdf.close()  # Close temporary TOC

                # Calculate page offset based on cover + preface pages + TOC pages
                cover_page_count = 1 if cover_pdf else 0
                page_offset = cover_page_count + len(preface_files) + toc_page_count
                pdf_span.set_attribute("page_offset", page_offset)

                if cover_pdf:
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
                                    step.increment(1, f"Added preface: {file.name}")
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
                with reporter.step(len(files), "Copying from cached PDF...") as step:
                    try:
                        copy_pdfs(
                            songbook_pdf,
                            files,
                            cache,
                            page_offset,
                            step,
                            add_page_numbers=add_page_numbers,
                            toc_page_index=toc_start_page,
                        )
                    except PdfCopyException as e:
                        click.echo(f"Error copying from cached PDF: {str(e)}", err=True)
                        raise

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
                                        click.echo(
                                            f"Passing final=1 for last postface file: {file.name}"
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
                                    step.increment(1, f"Added postface: {file.name}")
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
                        destination_path.parent.mkdir(parents=True, exist_ok=True)
                        songbook_pdf.ez_save(destination_path)  # Save the merged PDF
                        save_span.set_attribute(
                            "output_file_size", os.path.getsize(destination_path)
                        )
                        if not os.path.exists(destination_path):
                            raise FileNotFoundError(
                                f"Failed to save master PDF at {destination_path}"
                            )
        click.echo(f"SUCCESS: Completed generated PDF at {destination_path}.")


def add_page_number(page, page_index):
    text = str(page_index)
    x = page.rect.width - 40
    y = 30
    page.insert_text((x, y), text, fontsize=9, color=(0, 0, 0))
