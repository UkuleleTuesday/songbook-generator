import os
import traceback

import click

from ..cache_updater.main import fetch_and_merge_pdfs
from ..cache_updater.sync import download_gcs_cache_to_local, sync_cache
from ..common.caching import init_cache
from ..common.config import get_settings
from .utils import SubcmdGroup, global_options


@click.group(cls=SubcmdGroup)
def cache():
    """Manage the song sheet cache."""


@cache.command("sync")
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
@click.option(
    "--edition-folder",
    default=None,
    help="Drive folder ID of the edition to prime cache for (syncs its Songs/ subfolder).",
)
def sync_cache_command(
    ctx,
    source_folder,
    no_metadata,
    force,
    update_tags_only,
    update_tags,
    local,
    edition_folder,
    **kwargs,
):
    """Sync files and metadata from Google Drive to the cache."""
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
        from ..cache_updater import main as cache_updater_main

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
        else:
            click.echo("Using GCS cache.")
            services["cache"] = init_cache(use_gcs=True)

        click.echo(f"Syncing folders: {source_folders}")
        sync_cache(
            source_folders,
            services,
            with_metadata=not no_metadata,
            modified_after=last_merge_time,
        )
        click.echo("Cache synchronization complete.")

        if edition_folder:
            click.echo(f"Syncing edition cache for folder: {edition_folder}")
            from ..cache_updater.sync import sync_cache_for_edition_folder

            edition_synced = sync_cache_for_edition_folder(edition_folder, services)
            click.echo(f"Edition sync complete. {edition_synced} file(s) synced.")

    except click.Abort:
        # click.Abort is raised on purpose, so just re-raise.
        raise
    except Exception:  # noqa: BLE001 - Catch all for CLI error reporting
        click.echo("Cache sync operation failed.", err=True)
        click.echo("Error details:", err=True)
        click.echo(traceback.format_exc(), err=True)
        raise click.Abort()


@cache.command("download")
@global_options
@click.option(
    "--with-metadata",
    is_flag=True,
    default=False,
    help="Also download GCS object metadata and save it to a .metadata.json file.",
)
def download_cache_command(with_metadata, **kwargs):
    """Download the GCS cache to the local cache directory."""
    try:
        click.echo("Starting GCS cache download (CLI mode)")
        from ..cache_updater import main as cache_updater_main

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


@cache.command("merge-pdfs")
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
        from ..cache_updater import main as cache_updater_main

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
