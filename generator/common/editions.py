"""Utilities for scanning and managing songbook editions from Google Drive."""

import click
import yaml
from googleapiclient.errors import HttpError
from loguru import logger
from pydantic import ValidationError
from typing import Dict, List, Tuple

from . import config
from .gdrive import GoogleDriveClient
from .tracing import get_tracer

tracer = get_tracer(__name__)

# Maximum number of parent folder IDs to include in a single Drive API
# OR-query.
_YAML_SEARCH_BATCH_SIZE = 50


def _list_child_folders(
    gdrive_client: GoogleDriveClient,
    source_folder_id: str,
) -> List[Dict[str, str]]:
    """
    Return all direct child folders of *source_folder_id*.

    Handles Drive API pagination so that more than 1 000 child folders are
    returned correctly.

    Args:
        gdrive_client: An authenticated Drive client.
        source_folder_id: The parent folder ID to query.

    Returns:
        A list of ``{"id": …, "name": …}`` dicts for every child folder.

    Raises:
        HttpError: If the Drive API returns an error.
    """
    folder_mime = "application/vnd.google-apps.folder"
    query = (
        f"'{source_folder_id}' in parents"
        f" and mimeType = '{folder_mime}'"
        f" and trashed = false"
    )
    folders: List[Dict[str, str]] = []
    page_token = None
    while True:
        resp = (
            gdrive_client.drive.files()
            .list(
                q=query,
                pageSize=1000,
                fields="nextPageToken, files(id, name)",
                pageToken=page_token,
            )
            .execute(num_retries=gdrive_client.config.api_retries)
        )
        folders.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return folders


def _find_yaml_files_in_folders(
    gdrive_client: GoogleDriveClient,
    folder_ids: List[str],
) -> Dict[str, str]:
    """
    Find ``.songbook.yaml`` files that are direct children of any of the
    given *folder_ids* using a single batched OR-query per chunk.

    Instead of issuing one API call per folder (O(n)), this function groups
    up to ``_YAML_SEARCH_BATCH_SIZE`` folder IDs into each Drive query,
    reducing the total number of requests to O(n / batch_size).

    Args:
        gdrive_client: An authenticated Drive client.
        folder_ids: Folder IDs to search within.

    Returns:
        A dict mapping ``folder_id → yaml_file_id`` for every folder that
        contains a ``.songbook.yaml`` file.  Only the *first* match per
        folder is kept (duplicates are silently ignored).

    Raises:
        HttpError: If the Drive API returns an error for any batch.
    """
    yaml_by_parent: Dict[str, str] = {}
    folder_id_set = set(folder_ids)

    for i in range(0, len(folder_ids), _YAML_SEARCH_BATCH_SIZE):
        batch = folder_ids[i : i + _YAML_SEARCH_BATCH_SIZE]
        parents_clause = " or ".join(f"'{fid}' in parents" for fid in batch)
        query = f"name = '.songbook.yaml' and trashed = false and ({parents_clause})"
        page_token = None
        while True:
            resp = (
                gdrive_client.drive.files()
                .list(
                    q=query,
                    pageSize=1000,
                    fields="nextPageToken, files(id, parents)",
                    pageToken=page_token,
                )
                .execute(num_retries=gdrive_client.config.api_retries)
            )
            for f in resp.get("files", []):
                for parent_id in f.get("parents", []):
                    if parent_id in folder_id_set:
                        yaml_by_parent.setdefault(parent_id, f["id"])
                        break
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

    return yaml_by_parent


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
        skipped_no_yaml = 0
        skipped_errors = 0

        for source_folder_id in source_folders:
            try:
                child_folders = _list_child_folders(gdrive_client, source_folder_id)

                if not child_folders:
                    continue

                folder_map = {f["id"]: f["name"] for f in child_folders}
                folder_ids = list(folder_map.keys())

                yaml_by_parent = _find_yaml_files_in_folders(gdrive_client, folder_ids)

                skipped_no_yaml += len(folder_ids) - len(yaml_by_parent)

                for folder_id, yaml_file_id in yaml_by_parent.items():
                    folder_name = folder_map[folder_id]
                    try:
                        raw = gdrive_client.download_raw_bytes(yaml_file_id)
                        data = yaml.safe_load(raw.decode("utf-8"))

                        edition = config.Edition.model_validate(data)
                        logger.info(
                            f"scan_drive_editions: validated edition "
                            f"title={edition.title!r} from folder "
                            f"{folder_name!r} (id={folder_id!r})"
                        )
                        editions.append((folder_id, edition))

                    except HttpError as e:
                        skipped_errors += 1
                        logger.warning(
                            f"scan_drive_editions: could not download "
                            f".songbook.yaml from folder {folder_name!r} "
                            f"(id={folder_id!r}): {e}"
                        )
                        click.echo(
                            f"Warning: could not read .songbook.yaml from "
                            f"folder '{folder_name}': {e}",
                            err=True,
                        )
                    except (yaml.YAMLError, UnicodeDecodeError) as e:
                        skipped_errors += 1
                        logger.warning(
                            f"scan_drive_editions: could not parse "
                            f".songbook.yaml in folder {folder_name!r} "
                            f"(id={folder_id!r}): {e}"
                        )
                        click.echo(
                            f"Warning: could not parse .songbook.yaml in "
                            f"folder '{folder_name}': {e}",
                            err=True,
                        )
                    except ValidationError as e:
                        skipped_errors += 1
                        logger.warning(
                            f"scan_drive_editions: .songbook.yaml in folder "
                            f"{folder_name!r} (id={folder_id!r}) failed "
                            f"Edition schema validation: {e}"
                        )
                        click.echo(
                            f"Warning: .songbook.yaml in folder "
                            f"'{folder_name}' does not match the Edition "
                            f"schema: {e}",
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
        span.set_attribute("scan.skipped_no_yaml", skipped_no_yaml)
        span.set_attribute("scan.skipped_errors", skipped_errors)
        logger.info(
            f"scan_drive_editions: completed; editions_valid={len(editions)} "
            f"skipped_no_yaml={skipped_no_yaml} skipped_errors={skipped_errors}"
        )
        return editions
