import fitz
import click
import os
import yaml
from datetime import datetime, timezone
from opentelemetry import trace
from pathlib import Path
from typing import List, Optional, Union, Dict, Any
from pydantic import ValidationError
from . import progress
from . import toc
from . import cover
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from ..common import caching, config
from .gcp import get_credentials
from .exceptions import PdfCopyException, PdfCacheNotFound, PdfCacheMissException
from ..common.filters import PropertyFilter, FilterGroup
from ..common.gdrive import (
    GoogleDriveClient,
    client,
)
from .models import File
from ..common.tracing import get_tracer
from ..common.editions import _make_default_edition
from natsort import natsorted
from unidecode import unidecode
import re

tracer = get_tracer(__name__)


def init_services(
    scopes: Optional[List[str]] = None, target_principal: Optional[str] = None
):
    """Initializes and authenticates services, logging auth details."""
    main_span = trace.get_current_span()

    with tracer.start_as_current_span("init_services"):
        if scopes is None:
            scopes = ["https://www.googleapis.com/auth/drive.readonly"]

        creds = get_credentials(scopes=scopes, target_principal=target_principal)
        drive = client(credentials=creds)
        cache = caching.init_cache()

        # Check for service account first by looking for the 'account' attribute
        if hasattr(creds, "account") and creds.account:
            auth_type = "Service Account"
            email = creds.account
            main_span.set_attribute("auth.type", auth_type)
            main_span.set_attribute("auth.email", email)
        # Then check for user credentials
        elif hasattr(creds, "token"):
            auth_type = "User Credentials"
            try:
                about = drive.about().get(fields="user").execute()
                user_info = about.get("user")
                if user_info:
                    user_name = user_info.get("displayName")
                    email = user_info.get("emailAddress")
                    main_span.set_attribute("auth.type", auth_type)
                    main_span.set_attribute("auth.email", email)
                    main_span.set_attribute("auth.user", user_name)
            except HttpError:
                pass  # Ignore errors fetching user info
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
    gdrive_client: GoogleDriveClient,
    source_folders: List[str],
    client_filter: Optional[Union[PropertyFilter, FilterGroup]] = None,
    progress_step=None,
) -> List[File]:
    """
    Collect files from multiple Google Drive folders and sort them alphabetically by name.

    Args:
        gdrive_client: Authenticated Google Drive client
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

        files = gdrive_client.query_drive_files_with_client_filter(
            source_folders, client_filter
        )

        if progress_step:
            progress_step.increment(
                1.0, f"Found {len(files)} files in {len(source_folders)} folder(s)"
            )

        # Sort files alphabetically by name after aggregating from all folders
        sorted_files = _sort_titles(files)
        span.set_attribute("total_files_found", len(files))
        return sorted_files


_COVER_PREFIX = "_cover"
_PREFACE_PREFIX = "_preface"
_POSTFACE_PREFIX = "_postface"


def categorize_folder_files(files: List[File]) -> Dict[str, Any]:
    """
    Categorize files in a Drive folder into cover, preface, songs, and postface.

    Naming convention (case-insensitive):
    - ``_cover…``   → cover page (the first one alphabetically is used)
    - ``_preface…`` → preface pages (sorted alphabetically)
    - ``_postface…``→ postface pages (sorted alphabetically)
    - everything else → song files (sorted using the standard song sort key)

    Args:
        files: Files as returned by
            :meth:`~generator.common.gdrive.GoogleDriveClient.list_folder_contents`.

    Returns:
        Dict with keys ``cover`` (a single :class:`~generator.worker.models.File`
        or ``None``), ``preface`` (list), ``songs`` (list), ``postface`` (list).
    """
    cover_files: List[File] = []
    preface_files: List[File] = []
    postface_files: List[File] = []
    song_files: List[File] = []

    for f in files:
        name_lower = f.name.lower()
        if name_lower.startswith(_COVER_PREFIX):
            cover_files.append(f)
        elif name_lower.startswith(_PREFACE_PREFIX):
            preface_files.append(f)
        elif name_lower.startswith(_POSTFACE_PREFIX):
            postface_files.append(f)
        else:
            song_files.append(f)

    cover_files.sort(key=lambda f: f.name.lower())
    preface_files.sort(key=lambda f: f.name.lower())
    postface_files.sort(key=lambda f: f.name.lower())
    song_files = _sort_titles(song_files)

    return {
        "cover": cover_files[0] if cover_files else None,
        "preface": preface_files,
        "songs": song_files,
        "postface": postface_files,
    }


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


_FOLDER_COMPONENT_NAMES = {
    "cover": "Cover",
    "preface": "Preface",
    "postface": "Postface",
    "songs": "Songs",
}


def resolve_folder_components(
    gdrive_client: GoogleDriveClient,
    folder_id: str,
    edition: config.Edition,
) -> config.Edition:
    """
    Resolve cover/preface/postface components from dedicated subfolders when
    ``use_folder_components`` is enabled on the edition.

    For each component type the function looks for a subfolder whose name
    matches the component name case-insensitively (``Cover``, ``Preface``,
    ``Postface``).  If a matching subfolder is found **and** the corresponding
    field on the edition is not already set in the YAML config, the
    subfolder's contents are used:

    - **Cover**: only the first file in the subfolder is used.
    - **Preface**, **Postface**: all files in the subfolder are used, in the
      order returned by the Drive API.

    Shortcuts inside any subfolder are resolved transparently by
    :meth:`~generator.common.gdrive.GoogleDriveClient.list_folder_contents`.

    Explicit YAML config entries (``cover_file_id``, ``preface_file_ids``,
    ``postface_file_ids``) always take precedence over subfolder-detected
    files so that existing configurations remain fully backward-compatible.

    Args:
        gdrive_client: An authenticated GoogleDriveClient instance.
        folder_id: The Drive folder ID that contains the edition subfolders.
        edition: The Edition loaded from ``.songbook.yaml``.

    Returns:
        A (possibly updated) copy of the Edition with file IDs resolved from
        the subfolders.  The original object is not mutated.
    """
    if not edition.use_folder_components:
        return edition

    with tracer.start_as_current_span("resolve_folder_components") as span:
        span.set_attribute("folder_id", folder_id)

        updates: dict = {}

        # --- Cover ---
        if edition.cover_file_id is None:
            cover_folder_id = gdrive_client.find_subfolder_by_name(
                folder_id, _FOLDER_COMPONENT_NAMES["cover"]
            )
            if cover_folder_id:
                cover_files = gdrive_client.list_folder_contents(cover_folder_id)
                if cover_files:
                    updates["cover_file_id"] = cover_files[0].id
                    click.echo(f"Found cover from subfolder: {cover_files[0].name}")
                    span.set_attribute("cover_resolved_from_folder", True)
                else:
                    click.echo(
                        "Cover subfolder found but contains no files; skipping.",
                        err=True,
                    )
            else:
                span.set_attribute("cover_subfolder_found", False)
        else:
            span.set_attribute("cover_from_yaml", True)

        # --- Preface ---
        if edition.preface_file_ids is None:
            preface_folder_id = gdrive_client.find_subfolder_by_name(
                folder_id, _FOLDER_COMPONENT_NAMES["preface"]
            )
            if preface_folder_id:
                preface_files = gdrive_client.list_folder_contents(preface_folder_id)
                if preface_files:
                    updates["preface_file_ids"] = [f.id for f in preface_files]
                    click.echo(
                        f"Found {len(preface_files)} preface file(s) from subfolder."
                    )
                    span.set_attribute("preface_resolved_from_folder", True)
                    span.set_attribute("preface_files_count", len(preface_files))
                else:
                    click.echo(
                        "Preface subfolder found but contains no files; skipping.",
                        err=True,
                    )
            else:
                span.set_attribute("preface_subfolder_found", False)
        else:
            span.set_attribute("preface_from_yaml", True)

        # --- Postface ---
        if edition.postface_file_ids is None:
            postface_folder_id = gdrive_client.find_subfolder_by_name(
                folder_id, _FOLDER_COMPONENT_NAMES["postface"]
            )
            if postface_folder_id:
                postface_files = gdrive_client.list_folder_contents(postface_folder_id)
                if postface_files:
                    updates["postface_file_ids"] = [f.id for f in postface_files]
                    click.echo(
                        f"Found {len(postface_files)} postface file(s) from subfolder."
                    )
                    span.set_attribute("postface_resolved_from_folder", True)
                    span.set_attribute("postface_files_count", len(postface_files))
                else:
                    click.echo(
                        "Postface subfolder found but contains no files; skipping.",
                        err=True,
                    )
            else:
                span.set_attribute("postface_subfolder_found", False)
        else:
            span.set_attribute("postface_from_yaml", True)

        if updates:
            return edition.model_copy(update=updates)
        return edition


def _resolve_songs_from_folder(
    gdrive_client: GoogleDriveClient,
    folder_id: str,
) -> Optional[List[File]]:
    """
    Scan the ``Songs`` subfolder inside *folder_id* and return its contents
    as a sorted list of :class:`~generator.worker.models.File` objects, or
    ``None`` if no ``Songs`` subfolder exists.

    Shortcuts are resolved transparently by
    :meth:`~generator.common.gdrive.GoogleDriveClient.list_folder_contents`.

    Args:
        gdrive_client: An authenticated GoogleDriveClient instance.
        folder_id: The Drive folder that may contain a ``Songs`` subfolder.

    Returns:
        Sorted list of song files, or ``None`` if no ``Songs`` subfolder was
        found.
    """
    with tracer.start_as_current_span("resolve_songs_from_folder") as span:
        span.set_attribute("folder_id", folder_id)
        songs_folder_id = gdrive_client.find_subfolder_by_name(
            folder_id, _FOLDER_COMPONENT_NAMES["songs"]
        )
        if not songs_folder_id:
            span.set_attribute("songs_subfolder_found", False)
            return None

        songs_files = gdrive_client.list_folder_contents(songs_folder_id)
        if not songs_files:
            click.echo(
                "Songs subfolder found but contains no files; skipping.",
                err=True,
            )
            return None

        songs_files = _sort_titles(songs_files)
        click.echo(f"Found {len(songs_files)} song(s) from Songs subfolder.")
        span.set_attribute("songs_resolved_from_folder", True)
        span.set_attribute("songs_files_count", len(songs_files))
        return songs_files


def load_edition_from_drive_folder(
    gdrive_client: GoogleDriveClient,
    folder_id: str,
) -> tuple[config.Edition, Optional[List[File]]]:
    """
    Load an Edition configuration from a Google Drive folder.

    If the folder contains a ``.songbook.yaml`` file it is downloaded,
    validated against the :class:`~generator.common.config.Edition` schema,
    and used as the edition configuration.

    If **no** ``.songbook.yaml`` is present the folder's display name is
    fetched from the Drive API and a default edition is created via
    :func:`~generator.common.editions._make_default_edition` with
    ``use_folder_components=True``, so that ``Cover``, ``Preface``,
    ``Postface``, and ``Songs`` sub-folders are automatically discovered.

    If the loaded edition has ``use_folder_components: true``, dedicated
    subfolders named ``Cover``, ``Preface``, ``Postface``, and ``Songs``
    inside *folder_id* are scanned for component files.  Subfolder-detected
    files for cover/preface/postface are only used when the corresponding
    field is **not** already specified in the YAML config, preserving full
    backward compatibility.

    Args:
        gdrive_client: An authenticated GoogleDriveClient instance.
        folder_id: The Drive folder ID to load the edition from.

    Returns:
        A tuple of ``(edition, songs_files)`` where *edition* is a validated
        Edition object (parsed from YAML or built from sane defaults) with
        folder-based components resolved, and *songs_files* is a sorted list
        of :class:`~generator.worker.models.File` objects loaded from the
        ``Songs`` subfolder (or ``None`` if no such subfolder was found or
        ``use_folder_components`` is disabled).

    Raises:
        ValueError: If a ``.songbook.yaml`` file exists but is unreadable or
            invalid.
    """
    songbook_file = gdrive_client.find_file_in_folder(folder_id, ".songbook.yaml")
    if not songbook_file:
        folder_meta = gdrive_client.get_file_metadata(folder_id)
        folder_name = folder_meta.name if folder_meta else folder_id
        edition = _make_default_edition(folder_id, folder_name)
    else:
        raw = gdrive_client.download_raw_bytes(songbook_file.id)
        try:
            data = yaml.safe_load(raw.decode("utf-8"))
        except (yaml.YAMLError, UnicodeDecodeError) as e:
            raise ValueError(f"Failed to parse .songbook.yaml: {e}") from e

        try:
            edition = config.Edition.model_validate(data)
        except ValidationError as e:
            raise ValueError(
                f".songbook.yaml does not match the Edition schema: {e}"
            ) from e

    edition = resolve_folder_components(gdrive_client, folder_id, edition)

    songs_files = None
    if edition.use_folder_components:
        songs_files = _resolve_songs_from_folder(gdrive_client, folder_id)

    return edition, songs_files


def generate_songbook_from_edition(
    drive,
    cache,
    source_folders: List[str],
    destination_path: Path,
    edition: config.Edition,
    limit: int,
    on_progress=None,
    files: Optional[List[File]] = None,
):
    """
    Generate a songbook based on a predefined Edition configuration.

    This function acts as a wrapper around `generate_songbook`, using the
    settings defined in the provided `edition` object.

    Args:
        drive: Authenticated Google Drive service object.
        cache: Cache instance (local or GCS).
        source_folders: Google Drive folder IDs used as the song source when
            *files* is not provided.
        destination_path: Where to save the generated PDF.
        edition: The Edition configuration to use.
        limit: Maximum number of song files to include (``None`` = no limit).
        on_progress: Optional progress callback.
        files: Pre-resolved list of song :class:`~generator.worker.models.File`
            objects.  When provided the filter-based query against
            *source_folders* is skipped entirely.  Pass the second element of
            the tuple returned by :func:`load_edition_from_drive_folder` here
            when the edition was loaded from a Drive folder with a ``Songs``
            subfolder.
    """
    with tracer.start_as_current_span("generate_songbook_from_edition") as span:
        span.set_attribute("edition.id", edition.id)
        span.set_attribute("edition.description", edition.description)

        # Combine filters from the edition into a single FilterGroup if necessary
        client_filter = None
        if edition.filters:
            if len(edition.filters) == 1:
                client_filter = edition.filters[0]
            else:
                client_filter = FilterGroup(operator="AND", filters=edition.filters)

        if client_filter:
            span.set_attribute("client_filter", str(client_filter.model_dump()))

        if files is not None:
            span.set_attribute("songs_pre_supplied", True)
            span.set_attribute("songs_files_count", len(files))

        return generate_songbook(
            drive=drive,
            cache=cache,
            source_folders=source_folders,
            destination_path=destination_path,
            limit=limit,
            cover_file_id=edition.cover_file_id,
            client_filter=client_filter,
            preface_file_ids=edition.preface_file_ids,
            postface_file_ids=edition.postface_file_ids,
            on_progress=on_progress,
            title=edition.title,
            subject=edition.description,
            edition_toc_config=edition.table_of_contents,
            files=files,
        )


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
    title: Optional[str] = None,
    subject: Optional[str] = None,
    edition_toc_config: Optional[config.Toc] = None,
    files: Optional[List[File]] = None,
):
    with tracer.start_as_current_span("generate_songbook") as span:
        span.set_attribute("source_folders_count", len(source_folders))
        span.set_attribute("destination_path", str(destination_path))
        if title:
            span.set_attribute("pdf.title", title)
        if subject:
            span.set_attribute("pdf.subject", subject)
        if limit:
            span.set_attribute("limit", limit)
        if cover_file_id:
            span.set_attribute("cover_file_id", cover_file_id)
        if preface_file_ids:
            span.set_attribute("preface_files_count", len(preface_file_ids))
        if postface_file_ids:
            span.set_attribute("postface_files_count", len(postface_file_ids))

        reporter = progress.ProgressReporter(on_progress)

        gdrive_client = GoogleDriveClient(cache=cache, drive=drive)

        if files is None:
            with reporter.step(1, "Querying files...") as step:
                files = collect_and_sort_files(
                    gdrive_client, source_folders, client_filter, step
                )

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
        else:
            span.set_attribute("files_pre_supplied", True)
            click.echo(
                f"Using {len(files)} pre-supplied song files. Starting generation..."
            )

        span.set_attribute("final_files_count", len(files))

        # Get preface and postface files
        preface_files = []
        postface_files = []

        if preface_file_ids:
            with reporter.step(1, "Retrieving preface files...") as step:
                with tracer.start_as_current_span("get_preface_files") as preface_span:
                    preface_files = gdrive_client.get_files_metadata_by_ids(
                        preface_file_ids, step
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
                    postface_files = gdrive_client.get_files_metadata_by_ids(
                        postface_file_ids, step
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

        # Initialize page index tracking
        page_indices = {
            "cover": None,
            "preface": None,
            "table_of_contents": None,
            "body": None,
            "postface": None,
        }

        with tracer.start_as_current_span("create_songbook_pdf") as pdf_span:
            with fitz.open() as songbook_pdf:
                current_page = 0

                # Generate cover first to know if we need to adjust page offset
                with reporter.step(1, "Generating cover..."):
                    with tracer.start_as_current_span("generate_cover"):
                        settings = config.get_settings()
                        credential_config = settings.google_cloud.credentials.get(
                            "songbook-generator"
                        )
                        cover_creds = get_credentials(
                            scopes=credential_config.scopes,
                            target_principal=credential_config.principal,
                        )
                        docs_write_service = build(
                            "docs", "v1", credentials=cover_creds
                        )
                        drive_write_service = build(
                            "drive", "v3", credentials=cover_creds
                        )
                        gdrive_client_write = GoogleDriveClient(
                            cache=cache, drive=drive_write_service
                        )
                        cover_generator = cover.CoverGenerator(
                            gdrive_client_write,
                            docs_write_service,
                            cover_config=config.get_settings().cover,
                        )
                        cover_pdf = cover_generator.generate_cover(cover_file_id)

                # We need to calculate TOC size first to properly set page offsets
                with reporter.step(1, "Pre-calculating table of contents..."):
                    with tracer.start_as_current_span("precalculate_toc"):
                        toc_pdf, toc_entries = toc.build_table_of_contents(
                            files, 0, edition_toc_config
                        )  # Temporary offset
                        toc_page_count = len(toc_pdf)
                        toc_pdf.close()  # Close temporary TOC

                # Calculate page offset based on cover + preface pages + TOC pages
                cover_page_count = 1 if cover_pdf else 0
                page_offset = cover_page_count + len(preface_files) + toc_page_count
                pdf_span.set_attribute("page_offset", page_offset)

                # Add cover and track page indices
                if cover_pdf:
                    cover_start = current_page
                    songbook_pdf.insert_pdf(cover_pdf, start_at=0)
                    current_page = len(songbook_pdf)
                    page_indices["cover"] = {
                        "first_page": cover_start + 1,  # 1-based page numbers
                        "last_page": current_page,
                    }

                # Add preface files after cover and track page indices
                if preface_files:
                    preface_start = current_page
                    with reporter.step(
                        len(preface_files), "Adding preface files..."
                    ) as step:
                        with tracer.start_as_current_span(
                            "add_preface_files"
                        ) as preface_span:
                            for file in preface_files:
                                with (
                                    gdrive_client.download_file_stream(
                                        file
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
                    current_page = len(songbook_pdf)
                    page_indices["preface"] = {
                        "first_page": preface_start + 1,  # 1-based page numbers
                        "last_page": current_page,
                    }

                # Generate TOC with correct page offset and track page indices
                toc_start = current_page
                with reporter.step(1, "Generating table of contents..."):
                    with tracer.start_as_current_span("generate_toc"):
                        toc_pdf, toc_entries = toc.build_table_of_contents(
                            files, page_offset, edition_toc_config
                        )
                        toc_start_page = len(songbook_pdf)  # Remember where TOC starts
                        songbook_pdf.insert_pdf(toc_pdf)
                current_page = len(songbook_pdf)
                if toc_page_count > 0:  # Only set if TOC actually exists
                    page_indices["table_of_contents"] = {
                        "first_page": toc_start + 1,  # 1-based page numbers
                        "last_page": current_page,
                    }

                # Add main content - try cached approach first, fall back to individual downloads
                body_start = current_page
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
                current_page = len(songbook_pdf)
                if files:  # Only set if there are actual song files
                    page_indices["body"] = {
                        "first_page": body_start + 1,  # 1-based page numbers
                        "last_page": current_page,
                    }

                # Add postface files at the end and track page indices
                if postface_files:
                    postface_start = current_page
                    with reporter.step(
                        len(postface_files), "Adding postface files..."
                    ) as step:
                        with tracer.start_as_current_span(
                            "add_postface_files"
                        ) as postface_span:
                            for i, file in enumerate(postface_files):
                                with (
                                    gdrive_client.download_file_stream(
                                        file
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
                    current_page = len(songbook_pdf)
                    page_indices["postface"] = {
                        "first_page": postface_start + 1,  # 1-based page numbers
                        "last_page": current_page,
                    }

                # Add TOC links after all content is in place
                with reporter.step(1, "Adding table of contents links..."):
                    with tracer.start_as_current_span("add_toc_links"):
                        toc.add_toc_links_to_merged_pdf(
                            songbook_pdf, toc_entries, toc_start_page
                        )

                with reporter.step(1, "Setting PDF metadata..."):
                    with tracer.start_as_current_span("set_metadata"):
                        metadata = {
                            "author": "Ukulele Tuesday",
                            "producer": "PyMuPDF",
                            "creator": "Ukulele Tuesday Songbook Generator",
                        }
                        if title:
                            metadata["title"] = title
                        if subject:
                            metadata["subject"] = subject
                        songbook_pdf.set_metadata(metadata)

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

        # Return generation information for manifest creation
        return {
            "files": files,
            "title": title,
            "subject": subject,
            "page_indices": page_indices,
        }


def generate_songbook_from_drive_folder(
    drive,
    cache,
    folder_id: str,
    destination_path: Path,
    limit: Optional[int] = None,
    on_progress=None,
    title: Optional[str] = None,
    subject: Optional[str] = None,
    edition_toc_config: Optional[config.Toc] = None,
):
    """
    Generate a songbook from the contents of a single Google Drive folder.

    The folder may contain song PDFs, Google Docs, or **shortcuts** to files
    in other folders (shortcuts let you reuse a tab in multiple editions
    without duplicating the file).

    Special files are identified by their name prefix (case-insensitive):

    ==================  =======================================================
    Prefix              Role
    ==================  =======================================================
    ``_cover…``         Cover page – the first matching file is used.
    ``_preface…``       Preface page(s) – inserted after cover, before TOC,
                        sorted alphabetically.
    ``_postface…``      Postface page(s) – appended at the end, sorted
                        alphabetically.
    *(anything else)*   Song file – included as songbook body content, sorted
                        with the standard song sort key.
    ==================  =======================================================

    Args:
        drive: Authenticated Google Drive service object.
        cache: Cache instance (local or GCS).
        folder_id: The Google Drive folder ID to build the songbook from.
        destination_path: Where to save the generated PDF.
        limit: Maximum number of song files to include (``None`` = no limit).
        on_progress: Optional progress callback.
        title: PDF title metadata.
        subject: PDF subject metadata.
        edition_toc_config: Optional TOC configuration overrides.

    Returns:
        Generation information dict (same as :func:`generate_songbook`), or
        ``None`` if no song files are found in the folder (i.e. every file
        matched a special ``_cover``, ``_preface``, or ``_postface`` prefix,
        or the folder contained no files at all).
    """
    with tracer.start_as_current_span("generate_songbook_from_drive_folder") as span:
        span.set_attribute("folder_id", folder_id)

        gdrive_client = GoogleDriveClient(cache=cache, drive=drive)

        click.echo(f"Listing contents of Drive folder: {folder_id}")
        all_files = gdrive_client.list_folder_contents(folder_id)
        click.echo(f"Found {len(all_files)} item(s) in folder")
        span.set_attribute("folder_total_items", len(all_files))

        categorized = categorize_folder_files(all_files)

        cover_file = categorized["cover"]
        preface_files: List[File] = categorized["preface"]
        song_files: List[File] = categorized["songs"]
        postface_files: List[File] = categorized["postface"]

        span.set_attribute("cover_found", cover_file is not None)
        span.set_attribute("preface_count", len(preface_files))
        span.set_attribute("songs_count", len(song_files))
        span.set_attribute("postface_count", len(postface_files))

        cover_msg = (
            "found"
            if cover_file
            else "not found – global default cover will be used if configured"
        )
        click.echo(f"  Cover:    {cover_msg}")
        click.echo(f"  Preface:  {len(preface_files)} file(s)")
        click.echo(f"  Songs:    {len(song_files)} file(s)")
        click.echo(f"  Postface: {len(postface_files)} file(s)")

        if not song_files:
            click.echo(
                "No song files found in folder.  "
                "Make sure song files do not start with '_cover', "
                "'_preface', or '_postface'."
            )
            return None

        if limit and len(song_files) > limit:
            click.echo(f"Limiting to {limit} songs out of {len(song_files)} total")
            song_files = song_files[:limit]

        return generate_songbook(
            drive=drive,
            cache=cache,
            source_folders=[folder_id],
            destination_path=destination_path,
            limit=None,  # limit already applied above
            cover_file_id=cover_file.id if cover_file else None,
            client_filter=None,
            preface_file_ids=[f.id for f in preface_files] or None,
            postface_file_ids=[f.id for f in postface_files] or None,
            on_progress=on_progress,
            title=title,
            subject=subject,
            edition_toc_config=edition_toc_config,
            files=song_files,
        )


def generate_manifest(
    job_id: str,
    params: Dict[str, Any],
    destination_path: Path,
    files: List[File],
    edition: Optional[config.Edition] = None,
    title: Optional[str] = None,
    subject: Optional[str] = None,
    source_folders: Optional[List[str]] = None,
    generation_start_time: Optional[datetime] = None,
    generation_end_time: Optional[datetime] = None,
    page_indices: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Generate manifest data for a PDF generation job.

    Args:
        job_id: Unique identifier for the generation job
        params: Original job parameters
        destination_path: Path where the PDF was generated
        files: List of files included in the songbook
        edition: Edition configuration if used
        title: PDF title
        subject: PDF subject
        source_folders: Source Google Drive folder IDs
        generation_start_time: When generation started
        generation_end_time: When generation completed
        page_indices: Dictionary with page indices for each section (cover, preface, table_of_contents, body, postface)

    Returns:
        Dictionary containing manifest data
    """
    manifest = {
        "job_id": job_id,
        "generated_at": (generation_end_time or datetime.now(timezone.utc)).isoformat(),
        "generation_info": {
            "start_time": (
                generation_start_time or datetime.now(timezone.utc)
            ).isoformat(),
            "end_time": (generation_end_time or datetime.now(timezone.utc)).isoformat(),
            "duration_seconds": (
                (generation_end_time - generation_start_time).total_seconds()
                if generation_start_time and generation_end_time
                else None
            ),
        },
        "input_parameters": params.copy() if params else {},
        "pdf_info": {
            "title": title,
            "subject": subject,
            "author": "Ukulele Tuesday",
            "creator": "Ukulele Tuesday Songbook Generator",
            "producer": "PyMuPDF",
            "file_size_bytes": os.path.getsize(destination_path)
            if destination_path.exists()
            else None,
        },
        "content_info": {
            "total_files": len(files),
            "file_names": [f.name for f in files],
            "source_folders": source_folders or [],
        },
    }

    # Add edition information if available
    if edition:
        manifest["edition"] = {
            "id": edition.id,
            "title": edition.title,
            "description": edition.description,
            "cover_file_id": edition.cover_file_id,
            "preface_file_ids": edition.preface_file_ids,
            "postface_file_ids": edition.postface_file_ids,
            "table_of_contents_config": (
                edition.table_of_contents.model_dump(mode="json")
                if edition.table_of_contents
                else None
            ),
            "filters": [{**f.model_dump(mode="json")} for f in edition.filters]
            if edition.filters
            else [],
        }

    # Add page information if PDF exists
    if destination_path.exists():
        try:
            with fitz.open(destination_path) as pdf_doc:
                manifest["pdf_info"]["page_count"] = pdf_doc.page_count
                manifest["pdf_info"]["has_toc"] = bool(pdf_doc.get_toc())
                manifest["pdf_info"]["toc_entries"] = len(pdf_doc.get_toc())
        except (OSError, ValueError) as e:
            # Don't fail manifest generation if PDF reading fails
            click.echo(f"Warning: Could not read PDF metadata: {e}", err=True)

    # Add page indices information if available
    if page_indices:
        manifest["page_indices"] = page_indices

    return manifest


def add_page_number(page, page_index):
    text = str(page_index)
    x = page.rect.width - 35
    y = 30
    page.insert_text((x, y), text, fontsize=11, color=(0, 0, 0))
