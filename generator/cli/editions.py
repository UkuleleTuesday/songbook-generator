from pathlib import Path
from typing import List, Optional

import click
import google.auth.exceptions
import yaml
from googleapiclient.errors import HttpError

from ..common import config
from ..common.config import get_settings
from ..common.editions import scan_drive_editions
from ..common.filters import FilterGroup
from ..common.gdrive import GoogleDriveClient, SHORTCUT_MIME_TYPE
from ..worker.pdf import (
    FOLDER_COMPONENT_NAMES,
    collect_and_sort_files,
    init_services,
)
from .utils import SubcmdGroup


@click.group(cls=SubcmdGroup)
def editions():
    """List and manage configured songbook editions."""


@editions.command(name="list")
def list_editions():
    """List all configured and drive-detected songbook editions."""
    settings = get_settings()

    # --- Config editions ---
    config_editions = settings.editions
    if config_editions:
        click.echo("Config editions:")
        for edition in config_editions:
            click.echo(f"  [{edition.id}] {edition.title}")
    else:
        click.echo("No config editions found.")

    # --- Drive editions ---
    credential_config = settings.google_cloud.credentials.get("songbook-generator")
    if not credential_config:
        click.echo(
            "\nWarning: credential config 'songbook-generator' not found; "
            "skipping Drive scan.",
            err=True,
        )
        return

    # init_services can raise on auth/network errors; keep Drive scan best-effort.
    try:
        drive, cache = init_services(
            scopes=credential_config.scopes,
            target_principal=credential_config.principal,
        )
    except HttpError as exc:
        click.echo(f"\nWarning: Drive scan failed: {exc}", err=True)
        return
    except google.auth.exceptions.TransportError as exc:
        click.echo(f"\nWarning: Drive scan failed (network error): {exc}", err=True)
        return
    except google.auth.exceptions.DefaultCredentialsError as exc:
        click.echo(f"\nWarning: Drive scan failed (credentials error): {exc}", err=True)
        return

    gdrive_client = GoogleDriveClient(cache=cache, drive=drive)
    # scan_drive_editions handles Drive API errors internally and never raises.
    drive_results = scan_drive_editions(gdrive_client)

    if drive_results:
        click.echo("\nDrive editions:")
        for folder_id, edition in drive_results:
            click.echo(f"  [{folder_id}] {edition.title}")
    else:
        click.echo("\nNo drive editions found.")


@editions.command(name="copy")
@click.argument("source_folder_id")
@click.option(
    "--target-folder",
    "-t",
    default=None,
    help=(
        "Google Drive folder ID where the new edition folder will be created. "
        "Defaults to the single configured edition source folder "
        "(GDRIVE_SONGBOOK_EDITIONS_FOLDER_IDS)."
    ),
)
@click.option(
    "--folder-name",
    "-n",
    default=None,
    help="Name for the new Drive folder (defaults to 'Copy of <original name>').",
)
def copy_edition(
    source_folder_id: str,
    target_folder: Optional[str],
    folder_name: Optional[str],
):
    """Copy an existing songbook edition on Google Drive.

    Duplicates an edition folder including its .songbook.yaml config and all
    subfolders (Cover, Preface, Postface, Songs). Shortcuts within component
    folders are recreated pointing to the same target files.

    SOURCE_FOLDER_ID is the Drive folder ID of the edition to copy.
    """
    settings = get_settings()

    # Determine target folder
    if target_folder is None:
        edition_folders = settings.songbook_editions.folder_ids
        if len(edition_folders) == 1:
            target_folder = edition_folders[0]
        elif len(edition_folders) > 1:
            click.echo(
                "Error: Multiple edition source folders are configured. "
                "Please specify --target-folder.",
                err=True,
            )
            raise click.Abort()
        else:
            click.echo(
                "Error: No --target-folder specified and no edition source "
                "folders are configured (GDRIVE_SONGBOOK_EDITIONS_FOLDER_IDS). "
                "Please provide --target-folder.",
                err=True,
            )
            raise click.Abort()

    # Initialize Drive services
    try:
        drive, cache = init_services(
            scopes=["https://www.googleapis.com/auth/drive"],
        )
    except (
        HttpError,
        google.auth.exceptions.TransportError,
        google.auth.exceptions.DefaultCredentialsError,
    ) as exc:
        click.echo(f"Error: Failed to initialize Drive services: {exc}", err=True)
        raise click.Abort()

    gdrive_client = GoogleDriveClient(cache=cache, drive=drive)

    # Get source folder metadata
    click.echo(f"Fetching source folder '{source_folder_id}'...")
    try:
        source_files = gdrive_client.query_drive_files([source_folder_id])
        # Also get the folder itself to find its name
        resp = (
            drive.files()
            .get(fileId=source_folder_id, fields="name")
            .execute(num_retries=gdrive_client.config.api_retries)
        )
        source_folder_name = resp.get("name", "Untitled")
    except HttpError as exc:
        click.echo(f"Error: Failed to access source folder: {exc}", err=True)
        raise click.Abort()

    # Determine new folder name
    if folder_name is None:
        folder_name = f"Copy of {source_folder_name}"

    # Create the new edition folder
    click.echo(f"Creating new edition folder '{folder_name}'...")
    try:
        new_folder_id = gdrive_client.create_folder(folder_name, target_folder)
    except HttpError as exc:
        click.echo(f"Error: Failed to create new folder: {exc}", err=True)
        raise click.Abort()
    click.echo(f"  Created folder (id={new_folder_id})")

    # Copy .songbook.yaml if it exists
    click.echo("Copying .songbook.yaml...")
    yaml_files = [f for f in source_files if f.name == ".songbook.yaml"]
    if yaml_files:
        try:
            yaml_file = yaml_files[0]
            yaml_stream = gdrive_client.download_file_stream(yaml_file, use_cache=False)
            yaml_content = yaml_stream.read()
            yaml_file_id = gdrive_client.upload_file_bytes(
                ".songbook.yaml",
                yaml_content,
                new_folder_id,
                mime_type="application/x-yaml",
            )
            click.echo(f"  Copied .songbook.yaml (id={yaml_file_id})")
        except HttpError as exc:
            click.echo(f"Warning: Failed to copy .songbook.yaml: {exc}", err=True)
    else:
        click.echo("  No .songbook.yaml found in source folder")

    # Copy component subfolders and their shortcuts
    click.echo("Copying component subfolders...")
    component_folders = {
        "Cover": [],
        "Preface": [],
        "Postface": [],
        "Songs": [],
    }

    for file in source_files:
        if file.mimeType == "application/vnd.google-apps.folder":
            if file.name in component_folders:
                component_folders[file.name].append(file)

    for component_name, folders in component_folders.items():
        try:
            new_component_folder_id = gdrive_client.create_folder(
                component_name, new_folder_id
            )
            click.echo(f"  Created '{component_name}' subfolder")

            # If source has this component folder, copy its shortcuts
            if folders:
                source_component_folder = folders[0]
                # Get files in the component folder
                component_files = gdrive_client.query_drive_files(
                    [source_component_folder.id]
                )
                for file in component_files:
                    if file.mimeType == SHORTCUT_MIME_TYPE:
                        try:
                            # Get shortcut target
                            shortcut_resp = (
                                drive.files()
                                .get(
                                    fileId=file.id,
                                    fields="shortcutDetails",
                                )
                                .execute(
                                    num_retries=gdrive_client.config.api_retries
                                )
                            )
                            target_id = shortcut_resp.get("shortcutDetails", {}).get(
                                "targetId"
                            )
                            if target_id:
                                gdrive_client.create_shortcut(
                                    file.name, target_id, new_component_folder_id
                                )
                                click.echo(
                                    f"    Copied shortcut '{file.name}' in {component_name}/"
                                )
                        except HttpError as exc:
                            click.echo(
                                f"    Warning: Failed to copy shortcut '{file.name}': {exc}",
                                err=True,
                            )
        except HttpError as exc:
            click.echo(
                f"Warning: Failed to create '{component_name}' subfolder: {exc}",
                err=True,
            )

    click.echo("\nEdition copy complete.")
    click.echo(f"New edition folder ID: {new_folder_id}")
    click.echo("Run 'editions list' to verify the new edition is discovered.")


@editions.command(name="create")
@click.argument("title")
@click.option(
    "--target-folder",
    "-t",
    default=None,
    help=(
        "Google Drive folder ID where the new edition folder will be created. "
        "Defaults to the single configured edition source folder "
        "(GDRIVE_SONGBOOK_EDITIONS_FOLDER_IDS)."
    ),
)
@click.option(
    "--folder-name",
    "-n",
    default=None,
    help="Name for the new Drive folder (defaults to the title).",
)
@click.option(
    "--description",
    "-d",
    default="",
    help="Description for the edition.",
)
@click.option(
    "--filters",
    "-f",
    multiple=True,
    help=(
        "Edition filters in the format 'property:value'. Can be specified multiple times. "
        "Example: --filters 'artist:Beatles' --filters 'bpm:120'"
    ),
)
@click.option(
    "--cover-file-id",
    default=None,
    help="Google Drive file ID for the cover page.",
)
@click.option(
    "--preface-file-ids",
    default=None,
    help="Comma-separated list of Google Drive file IDs for preface pages.",
)
@click.option(
    "--postface-file-ids",
    default=None,
    help="Comma-separated list of Google Drive file IDs for postface pages.",
)
@click.option(
    "--no-shortcuts",
    is_flag=True,
    default=False,
    help="Do not create Drive component subfolders and shortcuts (default: create them).",
)
def create_edition(
    title: str,
    target_folder: Optional[str],
    folder_name: Optional[str],
    description: str,
    filters: tuple,
    cover_file_id: Optional[str],
    preface_file_ids: Optional[str],
    postface_file_ids: Optional[str],
    no_shortcuts: bool,
):
    """Create a new songbook edition on Google Drive.

    Creates a new Drive folder with a .songbook.yaml configuration file.
    The edition can be configured with filters and optional cover/preface/postface files.

    TITLE is the title for the new edition.
    """
    settings = get_settings()

    # Determine target folder
    if target_folder is None:
        edition_folders = settings.songbook_editions.folder_ids
        if len(edition_folders) == 1:
            target_folder = edition_folders[0]
        elif len(edition_folders) > 1:
            click.echo(
                "Error: Multiple edition source folders are configured. "
                "Please specify --target-folder.",
                err=True,
            )
            raise click.Abort()
        else:
            click.echo(
                "Error: No --target-folder specified and no edition source "
                "folders are configured (GDRIVE_SONGBOOK_EDITIONS_FOLDER_IDS). "
                "Please provide --target-folder.",
                err=True,
            )
            raise click.Abort()

    # Determine folder name
    if folder_name is None:
        folder_name = title

    # Initialize Drive services
    try:
        drive, cache = init_services(
            scopes=["https://www.googleapis.com/auth/drive"],
        )
    except (
        HttpError,
        google.auth.exceptions.TransportError,
        google.auth.exceptions.DefaultCredentialsError,
    ) as exc:
        click.echo(f"Error: Failed to initialize Drive services: {exc}", err=True)
        raise click.Abort()

    gdrive_client = GoogleDriveClient(cache=cache, drive=drive)

    # Create the edition folder in Drive
    click.echo(f"Creating Drive folder '{folder_name}'...")
    try:
        folder_id = gdrive_client.create_folder(folder_name, target_folder)
    except HttpError as exc:
        click.echo(f"Error: Failed to create Drive folder: {exc}", err=True)
        raise click.Abort()
    click.echo(f"  Created folder (id={folder_id})")

    # Build the edition configuration
    edition_data = {
        "title": title,
        "description": description,
        "use_folder_components": True,
    }

    # Add filters if provided
    if filters:
        filter_list = []
        for filter_str in filters:
            if ":" not in filter_str:
                click.echo(
                    f"Error: Invalid filter format '{filter_str}'. "
                    f"Expected 'property:value'.",
                    err=True,
                )
                raise click.Abort()
            prop, value = filter_str.split(":", 1)
            filter_list.append({"property": prop.strip(), "value": value.strip()})
        if filter_list:
            edition_data["filters"] = filter_list

    # Add component file IDs if provided
    if cover_file_id:
        edition_data["cover_file_id"] = cover_file_id
    if preface_file_ids:
        edition_data["preface_file_ids"] = [
            fid.strip() for fid in preface_file_ids.split(",")
        ]
    if postface_file_ids:
        edition_data["postface_file_ids"] = [
            fid.strip() for fid in postface_file_ids.split(",")
        ]

    # Serialize and upload .songbook.yaml
    yaml_content = yaml.dump(
        edition_data,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    ).encode("utf-8")

    click.echo("Uploading .songbook.yaml...")
    try:
        yaml_file_id = gdrive_client.upload_file_bytes(
            ".songbook.yaml",
            yaml_content,
            folder_id,
            mime_type="application/x-yaml",
        )
    except HttpError as exc:
        click.echo(f"Error: Failed to upload .songbook.yaml: {exc}", err=True)
        raise click.Abort()
    click.echo(f"  Uploaded .songbook.yaml (id={yaml_file_id})")

    # Always create component subfolders
    click.echo("Creating component subfolders...")
    if not no_shortcuts:
        # Create subfolders with shortcuts if component file IDs are provided
        from ..common.config import Edition as ConfigEdition

        edition_obj = ConfigEdition(
            title=title,
            description=description,
            filters=[],
            cover_file_id=cover_file_id,
            preface_file_ids=preface_file_ids.split(",") if preface_file_ids else None,
            postface_file_ids=postface_file_ids.split(",") if postface_file_ids else None,
        )
        _create_component_shortcuts(gdrive_client, edition_obj, folder_id)

    # Always create empty subfolders (Cover, Preface, Postface, Songs)
    # even if shortcuts weren't created or if no component files were specified
    for component_name in ["Cover", "Preface", "Postface", "Songs"]:
        try:
            # Check if subfolder already exists (created above with shortcuts)
            existing_files = gdrive_client.query_drive_files(
                [folder_id], property_filters=None
            )
            if not any(f.name == component_name for f in existing_files):
                gdrive_client.create_folder(component_name, folder_id)
                click.echo(f"  Created '{component_name}' subfolder")
        except HttpError as exc:
            click.echo(
                f"Warning: failed to create '{component_name}' subfolder: {exc}",
                err=True,
            )

    click.echo("\nEdition creation complete.")
    click.echo(f"Edition folder ID: {folder_id}")
    click.echo("Run 'editions list' to verify the new Drive edition is discovered.")


def _edition_to_yaml_bytes(
    edition: config.Edition, use_folder_components: bool = False
) -> bytes:
    """
    Serialize an Edition to YAML bytes.

    Only fields that were explicitly set in the original YAML are included,
    keeping the output minimal and readable.

    When *use_folder_components* is ``True``, the serialized YAML will have
    ``use_folder_components: true`` set and the ``cover_file_id``,
    ``preface_file_ids``, and ``postface_file_ids`` fields omitted — these
    will be resolved from the ``Cover``, ``Preface``, and ``Postface``
    subfolders that the caller is responsible for creating.

    Args:
        edition: The Edition object to serialize.
        use_folder_components: When True, emit ``use_folder_components: true``
            and omit explicit file-ID fields.

    Returns:
        UTF-8 encoded YAML representation of the edition.
    """
    data = edition.model_dump(mode="json", exclude_unset=True)
    if use_folder_components:
        data["use_folder_components"] = True
        data.pop("cover_file_id", None)
        data.pop("preface_file_ids", None)
        data.pop("postface_file_ids", None)
    return yaml.dump(
        data,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    ).encode("utf-8")


def _warn_complex_edition_features(edition: config.Edition) -> None:
    """
    Emit warnings for edition features that require editing the
    .songbook.yaml file directly in Google Drive.

    Args:
        edition: The Edition to inspect.
    """
    has_filter_groups = any(isinstance(f, FilterGroup) for f in edition.filters)
    if has_filter_groups:
        click.echo(
            "Warning: This edition uses complex filter groups (AND/OR). "
            "These can only be modified by editing the .songbook.yaml "
            "file directly in Google Drive.",
            err=True,
        )
    if edition.table_of_contents is not None and edition.table_of_contents.postfixes:
        click.echo(
            "Warning: This edition has Table of Contents postfixes. "
            "These can only be modified by editing the .songbook.yaml "
            "file directly in Google Drive.",
            err=True,
        )


def _find_edition_config_path(edition_id: str) -> Optional[Path]:
    """
    Find the YAML config file path for a given edition ID.

    Scans the ``generator/config/songbooks/`` directory for a YAML file
    whose ``id`` field matches *edition_id*.

    Args:
        edition_id: The edition ID to search for.

    Returns:
        The :class:`~pathlib.Path` to the YAML file, or ``None`` if not found.
    """
    config_dir = Path(__file__).parent.parent / "config" / "songbooks"
    if not config_dir.is_dir():
        return None
    for filepath in sorted(config_dir.iterdir()):
        if filepath.suffix in (".yaml", ".yml"):
            try:
                with open(filepath) as f:
                    data = yaml.safe_load(f)
                if isinstance(data, dict) and data.get("id") == edition_id:
                    return filepath
            except (OSError, yaml.YAMLError):
                continue
    return None


def _create_component_shortcuts(
    gdrive_client: GoogleDriveClient,
    edition: config.Edition,
    folder_id: str,
    song_files: Optional[List] = None,
) -> None:
    """
    Create component subfolders and shortcuts for cover, preface, postface,
    and songs.

    Uses the naming conventions expected by
    :func:`~generator.worker.pdf.resolve_folder_components` when
    ``use_folder_components`` is enabled:

    - ``Cover``   subfolder → shortcut named ``cover``
    - ``Preface`` subfolder → shortcut named ``preface`` (single) or
      ``preface_01``, ``preface_02``, … (multiple, sorted alphabetically)
    - ``Postface`` subfolder → shortcut named ``postface`` (single) or
      ``postface_01``, ``postface_02``, … (multiple, sorted alphabetically)
    - ``Songs``   subfolder → one shortcut per song file, named by the
      song's file name

    Failures for individual subfolders or shortcuts are reported as warnings
    and do not abort the overall conversion.

    Args:
        gdrive_client: An authenticated GoogleDriveClient instance.
        edition: The Edition whose component file IDs to link.
        folder_id: The Drive folder ID of the edition folder.
        song_files: Pre-collected list of song File objects whose shortcuts
            will be placed in the ``Songs`` subfolder.  When ``None`` the
            ``Songs`` subfolder is not created.
    """
    if edition.cover_file_id:
        try:
            cover_subfolder_id = gdrive_client.create_folder(
                FOLDER_COMPONENT_NAMES["cover"], folder_id
            )
            shortcut_id = gdrive_client.create_shortcut(
                "cover", edition.cover_file_id, cover_subfolder_id
            )
            click.echo(
                f"  Created '{FOLDER_COMPONENT_NAMES['cover']}' subfolder "
                f"with cover shortcut (id={shortcut_id})"
            )
        except HttpError as exc:
            click.echo(
                f"Warning: failed to create cover subfolder/shortcut: {exc}",
                err=True,
            )

    preface_ids: List[str] = edition.preface_file_ids or []
    if preface_ids:
        try:
            preface_subfolder_id = gdrive_client.create_folder(
                FOLDER_COMPONENT_NAMES["preface"], folder_id
            )
            for idx, preface_id in enumerate(preface_ids):
                shortcut_name = (
                    "preface" if len(preface_ids) == 1 else f"preface_{idx + 1:02d}"
                )
                try:
                    gdrive_client.create_shortcut(
                        shortcut_name, preface_id, preface_subfolder_id
                    )
                except HttpError as exc:
                    click.echo(
                        f"Warning: failed to create preface shortcut "
                        f"'{shortcut_name}' (target={preface_id}): {exc}",
                        err=True,
                    )
            click.echo(
                f"  Created '{FOLDER_COMPONENT_NAMES['preface']}' subfolder "
                f"with {len(preface_ids)} preface shortcut(s)"
            )
        except HttpError as exc:
            click.echo(
                f"Warning: failed to create preface subfolder: {exc}",
                err=True,
            )

    postface_ids: List[str] = edition.postface_file_ids or []
    if postface_ids:
        try:
            postface_subfolder_id = gdrive_client.create_folder(
                FOLDER_COMPONENT_NAMES["postface"], folder_id
            )
            for idx, postface_id in enumerate(postface_ids):
                shortcut_name = (
                    "postface" if len(postface_ids) == 1 else f"postface_{idx + 1:02d}"
                )
                try:
                    gdrive_client.create_shortcut(
                        shortcut_name, postface_id, postface_subfolder_id
                    )
                except HttpError as exc:
                    click.echo(
                        f"Warning: failed to create postface shortcut "
                        f"'{shortcut_name}' (target={postface_id}): {exc}",
                        err=True,
                    )
            click.echo(
                f"  Created '{FOLDER_COMPONENT_NAMES['postface']}' subfolder "
                f"with {len(postface_ids)} postface shortcut(s)"
            )
        except HttpError as exc:
            click.echo(
                f"Warning: failed to create postface subfolder: {exc}",
                err=True,
            )

    if song_files:
        try:
            songs_subfolder_id = gdrive_client.create_folder(
                FOLDER_COMPONENT_NAMES["songs"], folder_id
            )
            created = 0
            for song in song_files:
                try:
                    gdrive_client.create_shortcut(
                        song.name, song.id, songs_subfolder_id
                    )
                    created += 1
                except HttpError as exc:
                    click.echo(
                        f"Warning: failed to create song shortcut "
                        f"'{song.name}' (id={song.id}): {exc}",
                        err=True,
                    )
            click.echo(
                f"  Created '{FOLDER_COMPONENT_NAMES['songs']}' subfolder "
                f"with {created} song shortcut(s)"
            )
        except HttpError as exc:
            click.echo(
                f"Warning: failed to create songs subfolder: {exc}",
                err=True,
            )


@editions.command(name="convert")
@click.argument("edition_id")
@click.option(
    "--target-folder",
    "-t",
    default=None,
    help=(
        "Google Drive folder ID where the new edition folder will be "
        "created. Required when multiple edition source folders are "
        "configured. Defaults to the single configured edition source "
        "folder (GDRIVE_SONGBOOK_EDITIONS_FOLDER_IDS)."
    ),
)
@click.option(
    "--folder-name",
    "-n",
    default=None,
    help="Name for the new Drive folder (defaults to the edition title).",
)
@click.option(
    "--create-shortcuts/--no-create-shortcuts",
    default=True,
    help=(
        "Create Drive shortcuts for cover, preface, and postface files "
        "in the new folder (default: enabled)."
    ),
)
@click.option(
    "--delete-config",
    is_flag=True,
    default=False,
    help=(
        "Delete the original YAML config file from the repository after "
        "a successful conversion."
    ),
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help=(
        "Print the actions that would be taken without making any changes "
        "to Google Drive or the local file system."
    ),
)
def convert_edition(
    edition_id: str,
    target_folder: Optional[str],
    folder_name: Optional[str],
    create_shortcuts: bool,
    delete_config: bool,
    dry_run: bool,
):
    """Convert a config-based edition to a Google Drive folder structure.

    Reads the config edition identified by EDITION_ID and creates an
    equivalent Drive folder containing a .songbook.yaml file. Shortcuts
    to cover, preface, and postface files are created by default for
    easy browsing in Google Drive.

    EDITION_ID is the edition's configured ID (e.g. 'current').
    """
    settings = get_settings()

    # Find the edition in config editions
    edition = next((e for e in settings.editions if e.id == edition_id), None)
    if edition is None:
        click.echo(
            f"Error: Edition '{edition_id}' not found in config editions.",
            err=True,
        )
        raise click.Abort()

    # Determine target folder
    if target_folder is None:
        edition_folders = settings.songbook_editions.folder_ids
        if len(edition_folders) == 1:
            target_folder = edition_folders[0]
        elif len(edition_folders) > 1:
            click.echo(
                "Error: Multiple edition source folders are configured. "
                "Please specify --target-folder.",
                err=True,
            )
            raise click.Abort()
        else:
            click.echo(
                "Error: No --target-folder specified and no edition source "
                "folders are configured "
                "(GDRIVE_SONGBOOK_EDITIONS_FOLDER_IDS). "
                "Please provide --target-folder.",
                err=True,
            )
            raise click.Abort()

    # Determine folder name
    if folder_name is None:
        folder_name = edition.title

    # Warn about features that require YAML editing in Drive
    _warn_complex_edition_features(edition)

    if dry_run:
        _dry_run_convert_edition(
            edition=edition,
            edition_id=edition_id,
            folder_name=folder_name,
            target_folder=target_folder,
            create_shortcuts=create_shortcuts,
            delete_config=delete_config,
        )
        return

    # Initialize Drive services as the caller (no impersonation) — write
    # operations require user-level access; the service account only has
    # read permissions.
    try:
        drive, cache = init_services(
            scopes=["https://www.googleapis.com/auth/drive"],
        )
    except (
        HttpError,
        google.auth.exceptions.TransportError,
        google.auth.exceptions.DefaultCredentialsError,
    ) as exc:
        click.echo(f"Error: Failed to initialize Drive services: {exc}", err=True)
        raise click.Abort()

    gdrive_client = GoogleDriveClient(cache=cache, drive=drive)

    # Create the edition folder in Drive
    click.echo(f"Creating Drive folder '{folder_name}'...")
    try:
        folder_id = gdrive_client.create_folder(folder_name, target_folder)
    except HttpError as exc:
        click.echo(f"Error: Failed to create Drive folder: {exc}", err=True)
        raise click.Abort()
    click.echo(f"  Created folder (id={folder_id})")

    # Serialize the edition and upload .songbook.yaml.
    # When creating component subfolders, those subfolders will provide the
    # cover/preface/postface files, so use_folder_components is set in the
    # YAML and the explicit file-ID fields are omitted.
    yaml_content = _edition_to_yaml_bytes(
        edition, use_folder_components=create_shortcuts
    )
    click.echo("Uploading .songbook.yaml...")
    try:
        yaml_file_id = gdrive_client.upload_file_bytes(
            ".songbook.yaml",
            yaml_content,
            folder_id,
            mime_type="application/x-yaml",
        )
    except HttpError as exc:
        click.echo(f"Error: Failed to upload .songbook.yaml: {exc}", err=True)
        raise click.Abort()
    click.echo(f"  Uploaded .songbook.yaml (id={yaml_file_id})")

    # Optionally create component subfolders and shortcuts
    if create_shortcuts:
        click.echo("Collecting song files matching edition filters...")
        client_filter = None
        if edition.filters:
            if len(edition.filters) == 1:
                client_filter = edition.filters[0]
            else:
                client_filter = FilterGroup(operator="AND", filters=edition.filters)
        song_files = collect_and_sort_files(
            gdrive_client, settings.song_sheets.folder_ids, client_filter
        )
        click.echo(f"  Found {len(song_files)} song(s)")
        click.echo("Creating component subfolders and shortcuts...")
        _create_component_shortcuts(gdrive_client, edition, folder_id, song_files)

    # Handle optional deletion of the original config file
    if delete_config:
        config_path = _find_edition_config_path(edition_id)
        if config_path:
            config_path.unlink()
            click.echo(f"Deleted config file: {config_path}")
        else:
            click.echo(
                f"Warning: Could not find the config YAML file for edition "
                f"'{edition_id}'; nothing deleted.",
                err=True,
            )
    else:
        config_path = _find_edition_config_path(edition_id)
        if config_path:
            click.echo(
                f"\nNote: The original config file '{config_path}' is "
                f"still present. You may remove it from the repository "
                f"once the Drive edition is confirmed working."
            )

    click.echo("\nConversion complete.")
    click.echo(f"Edition folder ID: {folder_id}")
    click.echo("Run 'editions list' to verify the new Drive edition is discovered.")


def _dry_run_convert_edition(
    edition: config.Edition,
    edition_id: str,
    folder_name: str,
    target_folder: str,
    create_shortcuts: bool,
    delete_config: bool,
) -> None:
    """
    Print the actions that ``editions convert`` would take, without making
    any changes to Google Drive or the local file system.

    Args:
        edition: The Edition object loaded from config.
        edition_id: The edition ID string.
        folder_name: The Drive folder name that would be created.
        target_folder: The parent Drive folder ID.
        create_shortcuts: Whether component subfolders/shortcuts would be
            created.
        delete_config: Whether the local config file would be deleted.
    """
    click.echo("[DRY RUN] The following actions would be performed:\n")

    click.echo(
        f"  1. Create Drive folder '{folder_name}' inside "
        f"parent folder '{target_folder}'"
    )

    yaml_content = _edition_to_yaml_bytes(
        edition, use_folder_components=create_shortcuts
    ).decode("utf-8")
    click.echo("  2. Upload .songbook.yaml with the following content:")
    for line in yaml_content.splitlines():
        click.echo(f"       {line}")

    step = 3
    if create_shortcuts:
        subfolder_actions: List[str] = []
        if edition.cover_file_id:
            subfolder_actions.append(
                f"{FOLDER_COMPONENT_NAMES['cover']}/ → "
                f"cover shortcut → {edition.cover_file_id}"
            )
        preface_ids: List[str] = edition.preface_file_ids or []
        if preface_ids:
            names = (
                ["preface"]
                if len(preface_ids) == 1
                else [f"preface_{i + 1:02d}" for i in range(len(preface_ids))]
            )
            for name, fid in zip(names, preface_ids):
                subfolder_actions.append(
                    f"{FOLDER_COMPONENT_NAMES['preface']}/ → {name} shortcut → {fid}"
                )
        postface_ids: List[str] = edition.postface_file_ids or []
        if postface_ids:
            names = (
                ["postface"]
                if len(postface_ids) == 1
                else [f"postface_{i + 1:02d}" for i in range(len(postface_ids))]
            )
            for name, fid in zip(names, postface_ids):
                subfolder_actions.append(
                    f"{FOLDER_COMPONENT_NAMES['postface']}/ → {name} shortcut → {fid}"
                )

        if subfolder_actions:
            click.echo(
                f"  {step}. Create component subfolders "
                f"(Cover, Preface, Postface, Songs) with shortcuts:"
            )
            for action in subfolder_actions:
                click.echo(f"       {action}")
            click.echo(
                f"       {FOLDER_COMPONENT_NAMES['songs']}/ "
                f"\u2192 shortcuts for song files matching edition filters "
                f"(resolved at runtime)"
            )
            step += 1
        else:
            click.echo(f"  {step}. Create component subfolders (Songs) with shortcuts:")
            click.echo(
                f"       {FOLDER_COMPONENT_NAMES['songs']}/ "
                f"\u2192 shortcuts for song files matching edition filters "
                f"(resolved at runtime)"
            )
            step += 1

    if delete_config:
        config_path = _find_edition_config_path(edition_id)
        if config_path:
            click.echo(f"  {step}. Delete local config file: {config_path}")
        else:
            click.echo(
                f"  {step}. Delete local config file: "
                f"(not found for edition '{edition_id}')"
            )
    else:
        config_path = _find_edition_config_path(edition_id)
        if config_path:
            click.echo(
                f"  {step}. Keep local config file: {config_path} "
                "(pass --delete-config to remove it)"
            )

    click.echo("\n[DRY RUN] No changes were made.")
