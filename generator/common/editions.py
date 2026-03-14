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


def scan_drive_editions(
    gdrive_client: GoogleDriveClient,
) -> List[Tuple[str, config.Edition]]:
    """
    Scan Google Drive for songbook edition folders.

    Edition folders are identified by the presence of a ``.songbook.yaml``
    file anywhere within the configured source folder trees.  Each folder
    containing such a file is treated as an edition; the folder ID is
    derived from the ``parents`` field of the discovered ``.songbook.yaml``.

    A single ``name = '.songbook.yaml' and '…' in ancestors`` query is
    issued per configured source folder, replacing the previous approach
    that made one API call per subfolder (O(n)).  This reduces API calls
    from O(n) to O(1) per source folder, with pagination handled via
    ``nextPageToken``.

    Folders with a missing, unparseable, or schema-invalid ``.songbook.yaml``
    are skipped with a warning; they do not cause the entire scan to fail.

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
            f"for .songbook.yaml files; source_folders={source_folders!r}"
        )

        editions: List[Tuple[str, config.Edition]] = []
        skipped_errors = 0

        for source_folder_id in source_folders:
            try:
                # Single query per source folder: find every .songbook.yaml
                # anywhere in the subtree.  The parent of each result is
                # the edition folder.  This replaces the previous O(n)
                # pattern (list child folders, then probe each one).
                page_token = None
                while True:
                    resp = (
                        gdrive_client.drive.files()
                        .list(
                            q=(
                                f"name = '.songbook.yaml'"
                                f" and '{source_folder_id}' in ancestors"
                                " and trashed = false"
                            ),
                            pageSize=100,
                            fields="nextPageToken, files(id, parents)",
                            pageToken=page_token,
                        )
                        .execute(num_retries=gdrive_client.config.api_retries)
                    )

                    for yaml_file in resp.get("files", []):
                        yaml_file_id = yaml_file["id"]
                        parents = yaml_file.get("parents", [])
                        if not parents:
                            skipped_errors += 1
                            logger.warning(
                                f"scan_drive_editions: .songbook.yaml "
                                f"(id={yaml_file_id!r}) has no parent; skipping"
                            )
                            continue
                        folder_id = parents[0]

                        try:
                            raw = gdrive_client.download_raw_bytes(yaml_file_id)
                            data = yaml.safe_load(raw.decode("utf-8"))

                            edition = config.Edition.model_validate(data)
                            logger.info(
                                f"scan_drive_editions: validated edition "
                                f"title={edition.title!r} "
                                f"from folder id={folder_id!r}"
                            )
                            editions.append((folder_id, edition))

                        except HttpError as e:
                            skipped_errors += 1
                            logger.warning(
                                f"scan_drive_editions: could not download "
                                f".songbook.yaml (id={yaml_file_id!r}) in "
                                f"folder id={folder_id!r}: {e}"
                            )
                            click.echo(
                                f"Warning: could not read .songbook.yaml from "
                                f"folder id='{folder_id}': {e}",
                                err=True,
                            )
                        except (yaml.YAMLError, UnicodeDecodeError) as e:
                            skipped_errors += 1
                            logger.warning(
                                f"scan_drive_editions: could not parse "
                                f".songbook.yaml (id={yaml_file_id!r}) in "
                                f"folder id={folder_id!r}: {e}"
                            )
                            click.echo(
                                f"Warning: could not parse .songbook.yaml in "
                                f"folder id='{folder_id}': {e}",
                                err=True,
                            )
                        except ValidationError as e:
                            skipped_errors += 1
                            logger.warning(
                                f"scan_drive_editions: .songbook.yaml "
                                f"(id={yaml_file_id!r}) in folder "
                                f"id={folder_id!r} failed Edition schema "
                                f"validation: {e}"
                            )
                            click.echo(
                                f"Warning: .songbook.yaml in folder "
                                f"id='{folder_id}' does not match the "
                                f"Edition schema: {e}",
                                err=True,
                            )

                    page_token = resp.get("nextPageToken")
                    if not page_token:
                        break

            except HttpError as e:
                logger.error(
                    f"scan_drive_editions: could not search for .songbook.yaml "
                    f"in source_folder={source_folder_id!r}: {e}"
                )
                click.echo(
                    f"Error: could not scan source folder '{source_folder_id}': {e}",
                    err=True,
                )

        span.set_attribute("scan.editions_valid", len(editions))
        span.set_attribute("scan.skipped_errors", skipped_errors)
        logger.info(
            f"scan_drive_editions: completed; editions_valid={len(editions)} "
            f"skipped_errors={skipped_errors}"
        )
        return editions
