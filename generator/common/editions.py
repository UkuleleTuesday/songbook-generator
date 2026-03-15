"""Utilities for scanning and managing songbook editions from Google Drive."""

import click
import yaml
from googleapiclient.errors import HttpError
from loguru import logger
from pydantic import ValidationError
from typing import List, Tuple

from . import config
from .gdrive import GoogleDriveClient
from .tracing import get_tracer

tracer = get_tracer(__name__)


def _make_default_edition(folder_id: str, folder_name: str) -> config.Edition:
    """
    Build a default :class:`~generator.common.config.Edition` for a Drive
    folder that has no ``.songbook.yaml`` file.

    The returned edition has:

    - ``id`` set to *folder_id* (stable, unique Drive identifier)
    - ``title`` set to *folder_name* (human-readable display name)
    - ``description`` set to an empty string
    - ``filters`` set to an empty list (no server-side filter; song files are
      expected to come from a ``Songs`` subfolder resolved via
      ``use_folder_components``)
    - ``use_folder_components`` set to ``True`` so that ``Cover``, ``Preface``,
      ``Postface``, and ``Songs`` sub-folders are automatically discovered

    Args:
        folder_id: The Google Drive folder ID.
        folder_name: The human-readable folder name as shown in Drive.

    Returns:
        A fully-constructed :class:`~generator.common.config.Edition` instance.
    """
    return config.Edition(
        id=folder_id,
        title=folder_name,
        description="",
        filters=[],
        use_folder_components=True,
    )


def scan_drive_editions(
    gdrive_client: GoogleDriveClient,
) -> List[Tuple[str, config.Edition]]:
    """
    Scan Google Drive for songbook edition folders.

    Edition folders are direct children of the configured source folders.
    Each folder must contain a valid ``.songbook.yaml`` file to be recognized
    as an edition.

    Folders without a ``.songbook.yaml`` file or with invalid YAML/schema are
    skipped with a warning; they do not cause the entire scan to fail.

    The search is restricted to specific Drive folders via
    ``GDRIVE_SONGBOOK_EDITIONS_FOLDER_IDS`` (comma-separated).

    Args:
        gdrive_client: An authenticated :class:`~generator.common.gdrive.GoogleDriveClient`.

    Returns:
        A list of ``(folder_id, Edition)`` tuples – one entry per valid
        edition folder found.  The *folder_id* is the Drive folder that
        contains the ``.songbook.yaml`` and can be used directly as an
        edition identifier when submitting a generation job.
    """
    with tracer.start_as_current_span("scan_drive_editions") as span:
        settings = config.get_settings()
        source_folders = settings.songbook_editions.folder_ids

        if not source_folders:
            logger.info(
                "scan_drive_editions: no source folders configured; skipping scan"
            )
            span.set_attribute("scan.source_folders_count", 0)
            span.set_attribute("scan.editions_valid", 0)
            return []

        span.set_attribute("scan.source_folders_count", len(source_folders))

        logger.info(
            f"scan_drive_editions: scanning {len(source_folders)} source folder(s) "
            f"for edition folders; source_folders={source_folders!r}"
        )

        editions: List[Tuple[str, config.Edition]] = []
        skipped_errors = 0

        # For each source folder, find direct child folders
        for source_folder_id in source_folders:
            try:
                # Query for folders that are direct children of source_folder
                resp = (
                    gdrive_client.drive.files()
                    .list(
                        q=f"'{source_folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
                        pageSize=100,
                        fields="files(id, name)",
                    )
                    .execute(num_retries=gdrive_client.config.api_retries)
                )

                child_folders = resp.get("files", [])

                # For each child folder, look for .songbook.yaml
                for folder in child_folders:
                    folder_id = folder["id"]
                    folder_name = folder["name"]

                    try:
                        # Find .songbook.yaml in this folder
                        yaml_resp = (
                            gdrive_client.drive.files()
                            .list(
                                q=f"'{folder_id}' in parents and name = '.songbook.yaml' and trashed = false",
                                pageSize=1,
                                fields="files(id)",
                            )
                            .execute(num_retries=gdrive_client.config.api_retries)
                        )

                        yaml_files = yaml_resp.get("files", [])
                        if not yaml_files:
                            logger.info(
                                f"scan_drive_editions: no .songbook.yaml in folder "
                                f"{folder_name!r} (id={folder_id!r}); using sane defaults"
                            )
                            editions.append(
                                (
                                    folder_id,
                                    _make_default_edition(folder_id, folder_name),
                                )
                            )
                            continue

                        yaml_file_id = yaml_files[0]["id"]

                        raw = gdrive_client.download_raw_bytes(yaml_file_id)
                        data = yaml.safe_load(raw.decode("utf-8"))

                        edition = config.Edition.model_validate(data)
                        logger.info(
                            f"scan_drive_editions: validated edition title={edition.title!r} "
                            f"from folder {folder_name!r} (id={folder_id!r})"
                        )
                        editions.append((folder_id, edition))

                    except HttpError as e:
                        skipped_errors += 1
                        logger.warning(
                            f"scan_drive_editions: could not download .songbook.yaml from "
                            f"folder {folder_name!r} (id={folder_id!r}): {e}"
                        )
                        click.echo(
                            f"Warning: could not read .songbook.yaml from folder "
                            f"'{folder_name}': {e}",
                            err=True,
                        )
                    except (yaml.YAMLError, UnicodeDecodeError) as e:
                        skipped_errors += 1
                        logger.warning(
                            f"scan_drive_editions: could not parse .songbook.yaml in "
                            f"folder {folder_name!r} (id={folder_id!r}): {e}"
                        )
                        click.echo(
                            f"Warning: could not parse .songbook.yaml in folder '{folder_name}': {e}",
                            err=True,
                        )
                    except ValidationError as e:
                        skipped_errors += 1
                        logger.warning(
                            f"scan_drive_editions: .songbook.yaml in folder {folder_name!r} "
                            f"(id={folder_id!r}) failed Edition schema validation: {e}"
                        )
                        click.echo(
                            f"Warning: .songbook.yaml in folder '{folder_name}' does not "
                            f"match the Edition schema: {e}",
                            err=True,
                        )

            except HttpError as e:
                logger.error(
                    f"scan_drive_editions: could not list folders in "
                    f"source_folder={source_folder_id!r}: {e}"
                )
                click.echo(
                    f"Error: could not scan source folder '{source_folder_id}': {e}",
                    err=True,
                )

        span.set_attribute("scan.editions_valid", len(editions))
        span.set_attribute("scan.skipped_errors", skipped_errors)
        logger.info(
            f"scan_drive_editions: completed; "
            f"editions_valid={len(editions)} skipped_errors={skipped_errors}"
        )
        return editions
