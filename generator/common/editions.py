"""Utilities for scanning and managing songbook editions from Google Drive."""

import json
import os
import re

import click
import yaml
from dataclasses import dataclass
from googleapiclient.errors import HttpError
from loguru import logger
from pydantic import ValidationError
from typing import Dict, List, Optional, Tuple

from . import config
from .gdrive import GoogleDriveClient
from .tracing import get_tracer

tracer = get_tracer(__name__)

# Maximum number of parent folder IDs to include in a single Drive API
# OR-query.
_YAML_SEARCH_BATCH_SIZE = 50

# Schema version of the editions.json blob published to GCS by CI.
EDITIONS_SCHEMA_VERSION = 1

# config_ref is the only externally-supplied piece of the GCS config lookup:
# the bucket comes from the environment and the object path is constructed
# here, so a caller can at most select an existing main/pr-N blob — never an
# arbitrary URI.
_CONFIG_REF_RE = re.compile(r"^(main|pr-\d{1,6})$")

# Lazily-initialized GCS client, cached for warm starts.
_storage_client = None


def _get_storage_client():
    global _storage_client
    if _storage_client is None:
        from google.cloud import storage

        _storage_client = storage.Client()
    return _storage_client


def validate_config_ref(ref: str) -> str:
    """
    Validate a config_ref against the allowed ``main`` / ``pr-<N>`` pattern.

    Args:
        ref: The config_ref value to validate.

    Returns:
        The validated ref, unchanged.

    Raises:
        ValueError: If the ref does not match ``^(main|pr-\\d{1,6})$``.
    """
    if not ref or not _CONFIG_REF_RE.match(ref):
        raise ValueError(
            f"Invalid config_ref {ref!r}: must match {_CONFIG_REF_RE.pattern}"
        )
    return ref


def editions_blob_path(ref: str) -> str:
    """Return the GCS object path of the editions blob for *ref*."""
    return f"config/{validate_config_ref(ref)}/editions.json"


def load_editions_from_gcs(bucket_name: str, ref: str) -> List[config.Edition]:
    """
    Download and validate the editions blob for *ref* from *bucket_name*.

    Args:
        bucket_name: Name of the GCS bucket holding the config blobs.
        ref: A validated config ref (``main`` or ``pr-<N>``).

    Returns:
        The full list of editions contained in the blob.

    Raises:
        ValueError: If the blob's schema_version is unsupported.
        Exception: On download errors (e.g. missing blob), JSON parse
            errors, or Edition validation failures.
    """
    blob_path = editions_blob_path(ref)
    blob = _get_storage_client().bucket(bucket_name).blob(blob_path)
    data = json.loads(blob.download_as_bytes())
    schema_version = data.get("schema_version")
    if schema_version != EDITIONS_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported schema_version {schema_version!r} in "
            f"gs://{bucket_name}/{blob_path} "
            f"(expected {EDITIONS_SCHEMA_VERSION})"
        )
    return [config.Edition.model_validate(e) for e in data.get("editions", [])]


def resolve_editions(
    config_ref: Optional[str] = None,
) -> Tuple[List[config.Edition], str]:
    """
    Resolve the effective set of repo-config editions.

    When ``EDITIONS_CONFIG_BUCKET`` is set, editions are read from the GCS
    blob published by CI, so config-only changes take effect without a
    function redeploy. The blob is a whole-set replacement for the baked-in
    config (never a per-edition merge), so edition deletions propagate.

    Args:
        config_ref: Optional explicit ref (``main`` or ``pr-<N>``) selecting
            which published blob to read, used by PR previews running
            through the production worker. ``None`` selects the default
            (``main`` when the bucket is configured).

    Returns:
        A tuple ``(editions, source)`` where *source* is ``"gcs:<ref>"`` or
        ``"baked"``.

    Raises:
        ValueError: If *config_ref* is malformed, or if it was explicitly
            provided but its blob could not be loaded — an explicitly
            requested config must never silently fall back to another one.
    """
    bucket_name = os.getenv("EDITIONS_CONFIG_BUCKET") or None

    if config_ref:
        validate_config_ref(config_ref)
        if bucket_name is None:
            # PR-deployed functions (mixed code+config PRs) don't set the
            # bucket; their baked config already matches the PR.
            logger.warning(
                f"config_ref {config_ref!r} given but EDITIONS_CONFIG_BUCKET "
                "is not set; using baked-in editions config"
            )
            return config.get_settings().editions, "baked"
        try:
            editions = load_editions_from_gcs(bucket_name, config_ref)
        except Exception as e:
            raise ValueError(
                f"Could not load editions config for config_ref "
                f"{config_ref!r} from gs://{bucket_name}: {e}"
            ) from e
        logger.info(
            f"Loaded {len(editions)} edition(s) from "
            f"gs://{bucket_name}/{editions_blob_path(config_ref)}"
        )
        return editions, f"gcs:{config_ref}"

    if bucket_name is None:
        return config.get_settings().editions, "baked"

    try:
        editions = load_editions_from_gcs(bucket_name, "main")
    except Exception as e:  # noqa: BLE001 - any failure falls back to baked config
        logger.warning(
            f"Could not load editions config from gs://{bucket_name}/"
            f"{editions_blob_path('main')}; falling back to baked-in "
            f"editions config: {e}"
        )
        return config.get_settings().editions, "baked"
    logger.info(
        f"Loaded {len(editions)} edition(s) from "
        f"gs://{bucket_name}/{editions_blob_path('main')}"
    )
    return editions, "gcs:main"


@dataclass
class DriveEditionError:
    """Represents a Drive edition folder whose ``.songbook.yaml`` is invalid.

    Attributes:
        folder_id: The Google Drive folder ID.
        folder_name: Human-readable name of the Drive folder.
        error: A short description of the validation error.
    """

    folder_id: str
    folder_name: str
    error: str


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
) -> Tuple[List[Tuple[str, config.Edition]], List[DriveEditionError]]:
    """
    Scan Google Drive for songbook edition folders, returning both valid
    editions and folders whose ``.songbook.yaml`` could not be loaded.

    Edition folders are direct children of the configured source folders.
    Each folder that contains a ``.songbook.yaml`` file is attempted; those
    that parse and validate successfully are returned as
    ``(folder_id, Edition)`` pairs, while those that fail are returned as
    :class:`DriveEditionError` entries.

    Folders without a ``.songbook.yaml`` file are silently ignored.

    The search is restricted to specific Drive folders via
    ``GDRIVE_SONGBOOK_EDITIONS_FOLDER_IDS`` (comma-separated).

    Args:
        gdrive_client: An authenticated
            :class:`~generator.common.gdrive.GoogleDriveClient`.

    Returns:
        A tuple ``(editions, errors)`` where *editions* is a list of
        ``(folder_id, Edition)`` tuples for every valid edition found and
        *errors* is a list of :class:`DriveEditionError` objects for every
        folder whose ``.songbook.yaml`` could not be loaded or validated.
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
            return [], []

        span.set_attribute("scan.source_folders_count", len(source_folders))

        logger.info(
            f"scan_drive_editions: scanning {len(source_folders)} source folder(s) "
            f"for edition folders; source_folders={source_folders!r}"
        )

        editions: List[Tuple[str, config.Edition]] = []
        errors: List[DriveEditionError] = []
        skipped_no_yaml = 0

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
                        error_msg = f"Could not download .songbook.yaml: {e}"
                        errors.append(
                            DriveEditionError(
                                folder_id=folder_id,
                                folder_name=folder_name,
                                error=error_msg,
                            )
                        )
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
                        error_msg = f"Could not parse .songbook.yaml: {e}"
                        errors.append(
                            DriveEditionError(
                                folder_id=folder_id,
                                folder_name=folder_name,
                                error=error_msg,
                            )
                        )
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
                        error_msg = (
                            f".songbook.yaml does not match the Edition schema: {e}"
                        )
                        errors.append(
                            DriveEditionError(
                                folder_id=folder_id,
                                folder_name=folder_name,
                                error=error_msg,
                            )
                        )
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
        span.set_attribute("scan.editions_errors", len(errors))
        logger.info(
            f"scan_drive_editions: completed; editions_valid={len(editions)} "
            f"skipped_no_yaml={skipped_no_yaml} "
            f"editions_errors={len(errors)}"
        )
        return editions, errors
