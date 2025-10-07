import traceback
import os
import functools
import logging
import sys
from typing import Optional
import click
import fitz
from pathlib import Path


from .common.config import get_settings
from .cache_updater.main import fetch_and_merge_pdfs
import json
from .common.gdrive import (
    GoogleDriveClient,
)
from .common.caching import init_cache
from .cache_updater.sync import download_gcs_cache_to_local, sync_cache
from .common.filters import FilterParser, parse_filters
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from .tagupdater.tags import Tagger
from .worker.gcp import get_credentials
from .worker.pdf import (
    generate_songbook,
    generate_songbook_from_edition,
    init_services,
    collect_and_sort_files,
)


def make_cli_progress_callback():
    """Return a callback that displays progress updates to the console."""

    def _callback(percent: float, message: str = None):
        percentage = int(percent * 100)
        click.echo(f"[{percentage:3d}%] {message or ''}")

    return _callback


def global_options(f):
    """Decorator to apply global options to a command."""
    options = [
        click.option(
            "--log-level",
            default="INFO",
            type=click.Choice(
                ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], case_sensitive=False
            ),
            help="Set the logging level.",
        )
    ]
    return functools.reduce(lambda x, opt: opt(x), options, f)


@click.group(context_settings=dict(allow_interspersed_args=False))
@global_options
@click.pass_context
def cli(ctx, log_level: str):
    """Songbook Generator CLI tool."""
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    ctx.ensure_object(dict)


@cli.command()
@global_options
@click.pass_context
@click.option(
    "--edition",
    "-e",
    help="The ID of the songbook edition to generate (from songbooks.yaml).",
)
@click.option(
    "--source-folder",
    "-s",
    multiple=True,
    default=lambda: get_settings().song_sheets.folder_ids,
    help="Drive folder IDs to read files from (can be passed multiple times)",
)
@click.option(
    "--destination-path",
    "-d",
    type=click.Path(path_type=Path),
    default="out/songbook.pdf",
    help="Where to save the generated pdf",
)
@click.option(
    "--open-generated-pdf",
    is_flag=True,
    help="Open the generated pdf",
)
@click.option(
    "--cover-file-id",
    "-c",
    default=lambda: get_settings().cover.file_id,
    help="File ID of the cover",
)
@click.option(
    "--limit",
    "-l",
    type=int,
    default=None,
    help="Limit the number of files to process (no limit by default)",
)
@click.option(
    "--filter",
    "-f",
    help="Filter files using property syntax. Examples: 'specialbooks:contains:regular', 'year:gte:2000', 'artist:equals:Beatles', 'difficulty:in:easy,medium'",
)
@click.option(
    "--preface-file-id",
    multiple=True,
    help="Google Drive file IDs for preface pages (after cover, before TOC). Can be specified multiple times.",
)
@click.option(
    "--postface-file-id",
    multiple=True,
    help="Google Drive file IDs for postface pages (at the very end). Can be specified multiple times.",
)
def generate(
    ctx,
    edition: str,
    source_folder: str,
    destination_path: Path,
    open_generated_pdf,
    cover_file_id: str,
    limit: int,
    filter,
    preface_file_id,
    postface_file_id,
    **kwargs,
):
    """Generates a songbook PDF from Google Drive files."""

    settings = get_settings()
    credential_config = settings.google_cloud.credentials.get("songbook-generator")
    if not credential_config:
        click.echo("Error: credential config 'songbook-generator' not found.", err=True)
        raise click.Abort()

    drive, cache = init_services(
        scopes=credential_config.scopes,
        target_principal=credential_config.principal,
    )

    # Convert tuples to lists early
    source_folders = list(source_folder) if source_folder else []
    preface_file_ids = list(preface_file_id) if preface_file_id else None
    postface_file_ids = list(postface_file_id) if postface_file_id else None

    progress_callback = make_cli_progress_callback()

    if edition:
        # When using an edition, certain CLI flags are disallowed.
        conflicting_flags = {
            "--filter": filter,
            "--cover-file-id": cover_file_id != get_settings().cover.file_id,
            "--preface-file-id": preface_file_ids,
            "--postface-file-id": postface_file_ids,
        }
        used_conflicting = [
            flag for flag, present in conflicting_flags.items() if present
        ]
        if used_conflicting:
            click.echo(
                f"Error: Cannot use {', '.join(used_conflicting)} with --edition.",
                err=True,
            )
            raise click.Abort()

        selected_edition = next((e for e in settings.editions if e.id == edition), None)
        if not selected_edition:
            available = ", ".join([e.id for e in settings.editions])
            click.echo(f"Error: Edition '{edition}' not found.", err=True)
            click.echo(f"Available editions: {available}", err=True)
            raise click.Abort()

        click.echo(
            f"Generating songbook for edition: {selected_edition.id} - {selected_edition.description}"
        )
        generate_songbook_from_edition(
            drive=drive,
            cache=cache,
            source_folders=source_folders,
            destination_path=destination_path,
            edition=selected_edition,
            limit=limit,
            on_progress=progress_callback,
        )
    else:
        # Legacy mode without edition
        client_filter = None
        if filter:
            try:
                client_filter = FilterParser.parse_simple_filter(filter)
                click.echo(f"Applying client-side filter: {filter}")
            except ValueError as e:
                click.echo(f"Error parsing filter: {e}")
                return

        if preface_file_ids:
            click.echo(f"Using {len(preface_file_ids)} preface file(s)")
        if postface_file_ids:
            click.echo(f"Using {len(postface_file_ids)} postface file(s)")

        generate_songbook(
            drive,
            cache,
            source_folders,
            destination_path,
            limit,
            cover_file_id,
            client_filter,
            preface_file_ids,
            postface_file_ids,
            on_progress=progress_callback,
        )

    if open_generated_pdf:
        click.echo(f"Opening generated songbook: {destination_path}")
        click.launch(str(destination_path))


@cli.command("list-songs")
@global_options
@click.pass_context
@click.option(
    "--source-folder",
    "-s",
    multiple=True,
    default=lambda: get_settings().song_sheets.folder_ids,
    help="Drive folder IDs to read files from (can be passed multiple times)",
)
@click.option("--edition", "-e", help="List songs from a predefined edition.")
@click.option(
    "--filter",
    "-f",
    "filter_str",
    help="Filter files using property syntax.",
)
def list_songs(ctx, source_folder: str, edition: str, filter_str: str, **kwargs):
    """List songs matching a given filter expression or edition."""
    if not edition and not filter_str:
        raise click.UsageError("Either --edition or --filter must be provided.")
    if edition and filter_str:
        raise click.UsageError("Cannot use --edition and --filter simultaneously.")

    settings = get_settings()
    credential_config = settings.google_cloud.credentials.get("songbook-generator")
    if not credential_config:
        click.echo("Error: credential config 'songbook-generator' not found.", err=True)
        raise click.Abort()

    drive, _ = init_services(
        scopes=credential_config.scopes,
        target_principal=credential_config.principal,
    )

    source_folders = list(source_folder) if source_folder else []

    client_filter = None
    if filter_str:
        click.echo(f"Fetching files matching filter: {filter_str}")
        client_filter = parse_filters(filter_str)
    elif edition:
        click.echo(f"Fetching files for edition: '{edition}'")
        edition_config = next((e for e in settings.editions if e.id == edition), None)
        if not edition_config:
            raise click.BadParameter(f"Edition '{edition}' not found in configuration.")
        client_filter = parse_filters(edition_config.filters)

    files = collect_and_sort_files(
        gdrive_client=drive,
        source_folders=source_folders,
        client_filter=client_filter,
    )

    if not files:
        click.echo("No songs found matching the specified criteria.")
        return

    click.echo(f"\nFound {len(files)} song(s):")
    for file in files:
        click.echo(f"  - {file.name} (ID: {file.id})")


@cli.command(name="sync-cache")
@global_options
@click.pass_context
@click.option(
    "--source-folder",
    "-s",
    multiple=True,
    default=lambda: get_settings().song_sheets.folder_ids,
    help="Drive folder IDs to sync from (can be passed multiple times)",
)
@click.option(
    "--no-metadata",
    is_flag=True,
    default=False,
    help="Disable syncing of file metadata from Drive to GCS.",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Force a full sync, ignoring modification times.",
)
@click.option(
    "--update-tags-only",
    is_flag=True,
    default=False,
    help="[DEPRECATED] This option is no longer supported. Tagging is now handled by a dedicated cloud function.",
    hidden=True,
)
@click.option(
    "--update-tags",
    is_flag=True,
    default=False,
    help="[DEPRECATED] This option is no longer supported. Tagging is now handled by a dedicated cloud function.",
    hidden=True,
)
@click.option(
    "--local",
    is_flag=True,
    default=False,
    help="Sync to the local cache instead of GCS.",
)
def sync_cache_command(
    ctx,
    source_folder,
    no_metadata,
    force,
    update_tags_only,
    update_tags,
    local,
    **kwargs,
):
    """Syncs files and metadata from Google Drive to the cache."""
    # Check for deprecated tagging options
    if update_tags_only or update_tags:
        click.echo(
            "WARNING: The --update-tags-only and --update-tags options are deprecated.",
            err=True,
        )
        click.echo(
            "Tagging is now handled automatically by a dedicated cloud function when files change.",
            err=True,
        )
        if update_tags_only:
            click.echo("ERROR: --update-tags-only is no longer supported.", err=True)
            raise click.Abort()

    try:
        click.echo("Starting cache synchronization (CLI mode)")
        from .cache_updater import main as cache_updater_main

        services = cache_updater_main._get_services()
        source_folders = list(source_folder) if source_folder else []

        if not source_folders:
            click.echo("No source folders provided. Nothing to sync.", err=True)
            raise click.Abort()

        last_merge_time = None
        if not force:
            if not local:
                last_merge_time = cache_updater_main._get_last_merge_time(
                    services["cache_bucket"]
                )
        else:
            click.echo("Force flag set. Performing a full sync.")

        if local:
            click.echo("Using local cache.")
            services["cache"] = init_cache(use_gcs=False)

        click.echo(f"Syncing folders: {source_folders}")
        sync_cache(
            source_folders,
            services,
            with_metadata=not no_metadata,
            modified_after=last_merge_time,
        )
        click.echo("Cache synchronization complete.")

    except click.Abort:
        # click.Abort is raised on purpose, so just re-raise.
        raise
    except Exception:  # noqa: BLE001 - Catch all for CLI error reporting
        click.echo("Cache sync operation failed.", err=True)
        click.echo("Error details:", err=True)
        click.echo(traceback.format_exc(), err=True)
        raise click.Abort()


@cli.command(name="download-cache")
@global_options
@click.option(
    "--with-metadata",
    is_flag=True,
    default=False,
    help="Also download GCS object metadata and save it to a .metadata.json file.",
)
def download_cache_command(with_metadata, **kwargs):
    """Downloads the GCS cache to the local cache directory."""
    try:
        click.echo("Starting GCS cache download (CLI mode)")
        from .cache_updater import main as cache_updater_main

        services = cache_updater_main._get_services()
        local_cache_dir = get_settings().caching.local.dir
        click.echo(f"Local cache directory: {local_cache_dir}")

        download_gcs_cache_to_local(
            services, os.path.expanduser(local_cache_dir), with_metadata
        )

        click.echo("GCS cache download complete.")

    except click.Abort:
        # click.Abort is raised on purpose, so just re-raise.
        raise
    except Exception:  # noqa: BLE001 - Catch all for CLI error reporting
        click.echo("Cache download operation failed.", err=True)
        click.echo("Error details:", err=True)
        click.echo(traceback.format_exc(), err=True)
        raise click.Abort()


@cli.command(name="merge-pdfs")
@global_options
@click.option(
    "--output",
    "-o",
    default="merged-songbook.pdf",
    help="Output file path for merged PDF (default: merged-songbook.pdf)",
)
def merge_pdfs(output: str, **kwargs):
    """CLI interface for merging PDFs from GCS cache."""
    try:
        click.echo("Starting PDF merge operation (CLI mode)")

        # Lazily import to avoid issues if cache_updater dependencies are not available
        from .cache_updater import main as cache_updater_main

        # Manually get the services since we are not in a Cloud Function
        services = cache_updater_main._get_services()
        click.echo("Merging PDFs from all song sheets in cache.")
        result_path = fetch_and_merge_pdfs(output, services)

        if not result_path:
            click.echo("Error: No PDF files found to merge", err=True)
            raise click.Abort()

        click.echo(f"Successfully created merged PDF: {result_path}")

    except click.Abort:
        # click.Abort is raised on purpose, so just re-raise.
        raise
    except Exception:  # noqa: BLE001 - Catch all for CLI error reporting
        click.echo("Merge operation failed.", err=True)
        click.echo("Error details:", err=True)
        click.echo(traceback.format_exc(), err=True)
        raise click.Abort()


@cli.command(name="print-settings")
def print_settings():
    """Prints the current settings for debugging purposes."""
    click.echo("Current application settings:")
    settings = get_settings()
    click.echo(settings.model_dump_json(indent=2))


@cli.command(name="validate-pdf")
@global_options
@click.argument("pdf_path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--manifest",
    "-m",
    type=click.Path(exists=True, path_type=Path),
    help="Path to manifest.json file for enhanced validation",
)
@click.option(
    "--check-structure",
    is_flag=True,
    default=True,
    help="Validate songbook-specific structure",
)
@click.option(
    "--min-pages", type=int, default=3, help="Minimum number of pages expected"
)
@click.option("--max-size-mb", type=int, default=25, help="Maximum file size in MB")
@click.option("--expected-title", type=str, help="Expected PDF title in metadata")
@click.option(
    "--expected-author",
    type=str,
    default="Ukulele Tuesday",
    help="Expected PDF author in metadata",
)
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
def validate_pdf_cli(
    pdf_path: Path,
    manifest: Optional[Path],
    check_structure: bool,
    min_pages: int,
    max_size_mb: int,
    expected_title: str,
    expected_author: str,
    verbose: bool,
    **kwargs,
):
    """
    Validate a PDF file for basic sanity checks.

    This command performs comprehensive validation of a PDF file to ensure
    it's not corrupted and meets basic quality standards for a songbook.

    If a manifest.json file is provided, additional validation will be
    performed using the rich metadata from the generation process.
    """
    from .validation import (
        validate_pdf_file,
        validate_pdf_with_manifest,
        PDFValidationError,
    )

    try:
        if manifest:
            # Use enhanced validation with manifest
            validate_pdf_with_manifest(
                pdf_path=pdf_path,
                manifest_path=manifest,
                verbose=verbose,
            )
        else:
            # Use standard validation
            validate_pdf_file(
                pdf_path=pdf_path,
                check_structure=check_structure,
                min_pages=min_pages,
                max_size_mb=max_size_mb,
                expected_title=expected_title,
                expected_author=expected_author,
                verbose=verbose,
            )

        if not verbose:
            click.echo("✅ PDF validation passed")

    except PDFValidationError as e:
        click.echo(f"❌ PDF validation failed: {e}", err=True)
        sys.exit(1)
    except (OSError, IOError, fitz.FileDataError) as e:
        click.echo(f"❌ Error accessing PDF file: {e}", err=True)
        sys.exit(1)


@cli.group()
def editions():
    """Manage songbook editions for songs."""


def edition_management_command(func):
    """Decorator to handle boilerplate for edition management commands."""

    @functools.wraps(func)
    def wrapper(edition_name, file_identifier, **kwargs):
        settings = get_settings()
        credential_config = settings.google_cloud.credentials.get(
            "songbook-metadata-writer"
        )
        if not credential_config:
            click.echo(
                "Error: credential config 'songbook-metadata-writer' not found.",
                err=True,
            )
            raise click.Abort()

        drive, cache = init_services(
            scopes=credential_config.scopes,
            target_principal=credential_config.principal,
        )
        gdrive_client = GoogleDriveClient(cache=cache, drive=drive)

        file_id = _resolve_file_id(gdrive_client, file_identifier)
        properties = gdrive_client.get_file_properties(file_id)
        if properties is None:
            raise click.Abort()

        special_books_raw = properties.get("specialbooks", "")
        current_editions = {
            s.strip() for s in special_books_raw.split(",") if s.strip()
        }

        # Pass control to the decorated command function
        new_editions = func(current_editions, edition_name, file_id=file_id, **kwargs)

        # If the command returns None, it's a no-op (e.g., already in edition)
        if new_editions is None:
            return

        # Persist the changes
        new_value = ",".join(sorted(list(new_editions)))
        if gdrive_client.set_file_property(file_id, "specialbooks", new_value):
            click.echo(
                f"Successfully updated editions. New 'specialbooks' value: '{new_value}'"
            )
        else:
            click.echo("Failed to update editions.", err=True)
            raise click.Abort()

    return wrapper


@editions.command(name="add-song")
@click.argument("edition_name")
@click.argument("file_identifier")
@edition_management_command
def add_song_to_edition(current_editions, edition_name, **kwargs):
    """Adds a song to a specific songbook edition (specialbooks tag)."""
    if edition_name in current_editions:
        click.echo(f"Song is already in the '{edition_name}' edition.")
        return None  # Signal no-op

    current_editions.add(edition_name)
    return current_editions


@editions.command(name="remove-song")
@click.argument("edition_name")
@click.argument("file_identifier")
@edition_management_command
def remove_song_from_edition(current_editions, edition_name, **kwargs):
    """Removes a song from a specific songbook edition (specialbooks tag)."""
    if edition_name not in current_editions:
        click.echo(f"Song is not in the '{edition_name}' edition. No changes made.")
        return None  # Signal no-op

    current_editions.remove(edition_name)
    return current_editions


@editions.command(name="list")
@click.argument("file_identifier")
def list_song_editions(file_identifier):
    """Lists all editions a song belongs to."""
    settings = get_settings()
    credential_config = settings.google_cloud.credentials.get(
        "songbook-metadata-reader"
    )
    if not credential_config:
        # Fallback to writer if reader isn't defined
        credential_config = settings.google_cloud.credentials.get(
            "songbook-metadata-writer"
        )

    if not credential_config:
        click.echo(
            "Error: No suitable credential config found.",
            err=True,
        )
        raise click.Abort()

    drive, cache = init_services(
        scopes=credential_config.scopes,
        target_principal=credential_config.principal,
    )
    gdrive_client = GoogleDriveClient(cache=cache, drive=drive)
    file_id = _resolve_file_id(gdrive_client, file_identifier)
    properties = gdrive_client.get_file_properties(file_id)
    if properties is None:
        raise click.Abort()

    special_books_raw = properties.get("specialbooks", "")
    current_editions = {s.strip() for s in special_books_raw.split(",") if s.strip()}

    if not current_editions:
        click.echo("Song does not belong to any editions.")
    else:
        click.echo("Song is in the following editions:")
        for edition in sorted(list(current_editions)):
            click.echo(f"- {edition}")


@cli.group()
def tags():
    """Get and set tags (custom properties) on Google Drive files."""


def _resolve_file_id(gdrive_client: GoogleDriveClient, file_identifier: str) -> str:
    """
    Resolve a file identifier to a Google Drive file ID.
    If it's not a valid ID, search by name.
    """
    # Simple check if it looks like a Google Drive file ID
    if len(file_identifier) > 20 and " " not in file_identifier:
        return file_identifier  # Assume it's an ID

    # Otherwise, search by name
    settings = get_settings()
    source_folders = settings.song_sheets.folder_ids
    found_files = gdrive_client.search_files_by_name(file_identifier, source_folders)

    if not found_files:
        click.echo(f"Error: No file found matching '{file_identifier}'.", err=True)
        raise click.Abort()

    if len(found_files) > 1:
        click.echo(
            f"Error: Found multiple files matching '{file_identifier}'. Please be more specific or use a file ID.",
            err=True,
        )
        for f in found_files:
            click.echo(f"  - {f.name} (ID: {f.id})", err=True)
        raise click.Abort()

    file_id = found_files[0].id
    click.echo(f"Found file: {found_files[0].name} (ID: {file_id})")
    return file_id


@tags.command(name="get")
@click.argument("file_identifier")
@click.argument("key", required=False)
def get_tag(file_identifier, key):
    """Get a specific tag or all tags for a Google Drive file."""
    settings = get_settings()
    credential_config = settings.google_cloud.credentials.get(
        "songbook-metadata-writer"
    )
    if not credential_config:
        click.echo(
            "Error: credential config 'songbook-metadata-writer' not found.", err=True
        )
        raise click.Abort()

    drive, cache = init_services(
        scopes=credential_config.scopes,
        target_principal=credential_config.principal,
    )
    gdrive_client = GoogleDriveClient(cache=cache, drive=drive)
    file_id = _resolve_file_id(gdrive_client, file_identifier)
    properties = gdrive_client.get_file_properties(file_id)

    if properties is None:
        raise click.Abort()

    if key:
        if key in properties:
            click.echo(properties[key])
        else:
            click.echo(f"Error: Tag '{key}' not found.", err=True)
            raise click.Abort()
    else:
        click.echo(json.dumps(properties, indent=2))


@tags.command(name="set")
@click.argument("file_identifier")
@click.argument("key")
@click.argument("value")
def set_tag(file_identifier, key, value):
    """Set a tag on a Google Drive file."""
    settings = get_settings()
    credential_config = settings.google_cloud.credentials.get(
        "songbook-metadata-writer"
    )
    if not credential_config:
        click.echo(
            "Error: credential config 'songbook-metadata-writer' not found.", err=True
        )
        raise click.Abort()

    drive, cache = init_services(
        scopes=credential_config.scopes, target_principal=credential_config.principal
    )
    gdrive_client = GoogleDriveClient(cache=cache, drive=drive)
    file_id = _resolve_file_id(gdrive_client, file_identifier)
    if gdrive_client.set_file_property(file_id, key, value):
        click.echo(f"Successfully set tag '{key}' to '{value}'.")
    else:
        click.echo("Failed to set tag.", err=True)
        raise click.Abort()


@tags.command(name="delete")
@click.argument("file_identifier")
@click.argument("key")
def delete_tag(file_identifier, key):
    """Delete a tag from a Google Drive file."""
    settings = get_settings()
    credential_config = settings.google_cloud.credentials.get(
        "songbook-metadata-writer"
    )
    if not credential_config:
        click.echo(
            "Error: credential config 'songbook-metadata-writer' not found.", err=True
        )
        raise click.Abort()

    drive, cache = init_services(
        scopes=credential_config.scopes, target_principal=credential_config.principal
    )
    gdrive_client = GoogleDriveClient(cache=cache, drive=drive)
    file_id = _resolve_file_id(gdrive_client, file_identifier)

    try:
        file_metadata = (
            gdrive_client.drive.files()
            .get(fileId=file_id, fields="properties")
            .execute()
        )
        properties = file_metadata.get("properties", {})

        if key not in properties:
            click.echo(f"Tag '{key}' not found on file. No changes made.")
            return

        # To delete a property, set its value to null.
        properties_to_update = {key: None}

        gdrive_client.drive.files().update(
            fileId=file_id,
            body={"properties": properties_to_update},
            fields="properties",
        ).execute()
        click.echo(f"Successfully deleted tag '{key}'.")
    except HttpError as e:
        click.echo(f"Failed to delete tag '{key}': {e}", err=True)
        raise click.Abort()


@tags.command(name="update")
@click.argument("file_identifier", required=False)
@click.option(
    "--all",
    is_flag=True,
    default=False,
    help="Run the auto-tagger on all song sheets.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what tags would be applied without making any changes.",
)
def update_tags(file_identifier, all, dry_run):
    """Run the auto-tagger on a specific Google Drive file or all files."""
    if not file_identifier and not all:
        click.echo(
            "Error: Either a file identifier or the --all flag must be provided.",
            err=True,
        )
        raise click.Abort()
    if file_identifier and all:
        click.echo(
            "Error: Cannot use both a file identifier and the --all flag.", err=True
        )
        raise click.Abort()

    settings = get_settings()
    credential_config = settings.google_cloud.credentials.get(
        "songbook-metadata-writer"
    )
    if not credential_config:
        click.echo(
            "Error: credential config 'songbook-metadata-writer' not found.", err=True
        )
        raise click.Abort()

    # The Tagger needs to read Google Docs content.
    scopes = list(
        set(
            credential_config.scopes
            + ["https://www.googleapis.com/auth/documents.readonly"]
        )
    )

    creds = get_credentials(scopes=scopes, target_principal=credential_config.principal)
    drive_service = build("drive", "v3", credentials=creds)
    docs_service = build("docs", "v1", credentials=creds)
    cache = init_cache()
    gdrive_client = GoogleDriveClient(cache=cache, drive=drive_service)

    if file_identifier:
        file_id = _resolve_file_id(gdrive_client, file_identifier)
        files_to_process = gdrive_client.get_files_metadata_by_ids([file_id])
        if not files_to_process:
            click.echo(
                f"Error: Could not retrieve metadata for file ID {file_id}", err=True
            )
            raise click.Abort()
    else:  # --all flag
        click.echo("Fetching all song sheets from Drive...")
        files_to_process = gdrive_client.query_drive_files(
            settings.song_sheets.folder_ids
        )

    tagger = Tagger(drive_service=drive_service, docs_service=docs_service)
    failed_updates = {}

    for file_obj in files_to_process:
        try:
            if file_obj.mimeType != "application/vnd.google-apps.document":
                click.echo(
                    f"Skipping '{file_obj.name}' (not a Google Doc).",
                )
                continue

            click.echo(f"Running auto-tagger for '{file_obj.name}'...")
            if dry_run:
                click.echo("  (Dry run mode)")

            tagger.update_tags(file_obj, dry_run=dry_run)
        except HttpError as e:
            error_message = f"Failed to update tags for '{file_obj.name}': {e}"
            click.echo(f"ERROR: {error_message}", err=True)
            failed_updates[file_obj.name] = str(e)
        except Exception as e:  # noqa: BLE001 - Catch all for CLI error reporting
            error_message = f"An unexpected error occurred for '{file_obj.name}': {e}"
            click.echo(f"ERROR: {error_message}", err=True)
            failed_updates[file_obj.name] = str(e)

    if failed_updates:
        click.echo("\n--- Auto-tagger summary ---", err=True)
        click.echo("Auto-tagger run completed with some failures.", err=True)
        click.echo("Failed files:", err=True)
        for file_name, error in failed_updates.items():
            click.echo(f"  - {file_name}: {error}", err=True)
        sys.exit(1)

    click.echo("Auto-tagger run complete.")


@cli.command(name="download-doc-json")
@click.argument("file_identifier")
@click.argument(
    "output_path",
    type=click.Path(path_type=Path, dir_okay=False, writable=True),
    required=False,
)
def download_doc_json_command(file_identifier, output_path):
    """
    Downloads the raw JSON of a Google Doc.

    FILE_IDENTIFIER can be a Google Drive file ID or a partial file name.
    If OUTPUT_PATH is provided, saves to that file. Otherwise, prints to stdout.
    """
    settings = get_settings()
    credential_config = settings.google_cloud.credentials.get("songbook-generator")
    if not credential_config:
        click.echo("Error: credential config 'songbook-generator' not found.", err=True)
        raise click.Abort()

    # Add Docs API scope
    scopes = credential_config.scopes + [
        "https://www.googleapis.com/auth/documents.readonly"
    ]

    creds = get_credentials(
        scopes=scopes,
        target_principal=credential_config.principal,
    )
    drive_service = build("drive", "v3", credentials=creds)
    docs_service = build("docs", "v1", credentials=creds)
    cache = init_cache()
    gdrive_client = GoogleDriveClient(cache=cache, drive=drive_service)

    file_id = _resolve_file_id(gdrive_client, file_identifier)

    if not output_path:
        click.echo(f"Fetching document content for ID: {file_id}...", err=True)

    document = docs_service.documents().get(documentId=file_id).execute()

    if output_path:
        # Ensure the output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(document, f, indent=2)
        click.echo(f"Successfully saved document JSON to {output_path}")
    else:
        click.echo(json.dumps(document, indent=2))


if __name__ == "__main__":
    cli()
