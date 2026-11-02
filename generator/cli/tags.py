import contextlib
import csv
import json
import sys

import click
from google import genai
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from ..common.caching import init_cache
from ..common.config import get_settings
from ..common.gdrive import GoogleDriveClient
from ..common.metadata_store import get_metadata_store
from ..tagupdater.tags import Tagger
from ..worker.gcp import get_credentials
from ..worker.pdf import init_services
from .utils import SubcmdGroup, _resolve_file_id


@click.group(cls=SubcmdGroup)
def tags():
    """Get and set song tags in the Firestore metadata store."""


@tags.command(name="get")
@click.argument("file_identifier")
@click.argument("key", required=False)
def get_tag(file_identifier, key):
    """Get a specific tag or all tags for a song sheet."""
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

    properties = get_metadata_store().get_properties(file_id)
    if properties is None:
        click.echo(f"No metadata document found for file ID '{file_id}'.", err=True)
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
    """Set a tag on a song sheet."""
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

    if settings.metadata_store.firestore_write_enabled:
        store = get_metadata_store()
        props = store.get_properties(file_id) or {}
        props[key] = value
        store.write(file_id, props)
        click.echo(f"Successfully set tag '{key}' to '{value}' in Firestore.")


@tags.command(name="delete")
@click.argument("file_identifier")
@click.argument("key")
def delete_tag(file_identifier, key):
    """Delete a tag from a song sheet."""
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

    if settings.metadata_store.firestore_write_enabled:
        store = get_metadata_store()
        props = store.get_properties(file_id)
        if props is None:
            click.echo("No Firestore doc found. No changes made.")
        elif key not in props:
            click.echo(f"Tag '{key}' not found in Firestore. No changes made.")
        else:
            store.delete_property(file_id, key)
            click.echo(f"Successfully deleted tag '{key}' from Firestore.")


# Date properties that store the literal string "unknown" as a sentinel when the
# real value could not be determined (see #442). The sentinel is kept in
# Firestore to stop the tagger re-stamping a wrong timestamp, but consumers of
# the exported dataset should see an absent field rather than a magic string.
_UNKNOWN_SENTINEL = "unknown"
_UNKNOWN_SENTINEL_FIELDS = ("ready_to_play_date", "approved_date")


def _normalise_unknown_sentinels(doc: dict) -> dict:
    """Drop date properties whose value is the ``"unknown"`` sentinel.

    Returns the same document (mutated) so consumers get an absent field
    instead of a literal ``"unknown"`` string.
    """
    props = doc.get("properties")
    if not props:
        return doc
    for key in _UNKNOWN_SENTINEL_FIELDS:
        if props.get(key) == _UNKNOWN_SENTINEL:
            del props[key]
    return doc


def _load_metadata_documents() -> list[dict]:
    """Return all song metadata documents from Firestore, sorted by Drive file ID.

    Date fields holding the ``"unknown"`` sentinel are normalised to absent so
    the exported dataset never surfaces the magic string (see #442).
    """
    all_docs = get_metadata_store().get_all()
    return [
        _normalise_unknown_sentinels(all_docs[file_id]) for file_id in sorted(all_docs)
    ]


@contextlib.contextmanager
def _open_output(output_path):
    """Yield a writable handle for ``output_path``, or stdout if it is None."""
    if output_path is None:
        yield sys.stdout
    else:
        with open(output_path, "w", encoding="utf-8", newline="") as handle:
            yield handle


def _write_jsonl(documents: list[dict], out) -> None:
    """Write documents as newline-delimited JSON (one object per line)."""
    for doc in documents:
        out.write(json.dumps(doc, default=str, sort_keys=True))
        out.write("\n")


def _write_csv(documents: list[dict], out) -> None:
    """Write documents as CSV, one row per song.

    Columns are the identifying ``gdrive_file_id``/``gdrive_file_name`` fields
    followed by the sorted union of all property keys across documents.
    """
    property_keys: set[str] = set()
    for doc in documents:
        property_keys.update(doc.get("properties", {}) or {})

    columns = ["gdrive_file_id", "gdrive_file_name", *sorted(property_keys)]
    writer = csv.DictWriter(out, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for doc in documents:
        row = {
            "gdrive_file_id": doc.get("gdrive_file_id", ""),
            "gdrive_file_name": doc.get("gdrive_file_name", ""),
        }
        row.update(doc.get("properties", {}) or {})
        writer.writerow(row)


@tags.command(name="export")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["csv", "json"]),
    default="json",
    show_default=True,
    help="Output format.",
)
@click.option(
    "--output",
    "output_path",
    type=click.Path(dir_okay=False, writable=True),
    default=None,
    help="Output file path (default: stdout).",
)
def export_tags(output_format, output_path):
    """Bulk-export all song metadata (tags) to a local file or stdout.

    Reads every song document from Firestore and writes them in the requested
    format:

    \b
    - json: newline-delimited JSON (one object per line, same schema as the
      GCS dataset).
    - csv: one row per song, columns derived from the union of all property
      keys present across documents.
    """
    documents = _load_metadata_documents()

    with _open_output(output_path) as out:
        if output_format == "json":
            _write_jsonl(documents, out)
        else:
            _write_csv(documents, out)

    if output_path:
        click.echo(f"Exported {len(documents)} song(s) to {output_path}.", err=True)


@tags.command(name="update")
@click.argument("file_identifier", required=False)
@click.option(
    "--all",
    is_flag=True,
    default=False,
    help="Run the auto-tagger on all song sheets.",
)
@click.option(
    "--modified-since",
    type=click.DateTime(
        formats=["%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"]
    ),
    default=None,
    help=(
        "Run the auto-tagger on every song sheet modified in Drive since this "
        "UTC timestamp, e.g. --modified-since 2026-09-28 or "
        "--modified-since 2026-09-28T10:51:00. Use instead of --all to recover "
        "from a missed-change window."
    ),
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what tags would be applied without making any changes.",
)
@click.option(
    "--trigger-field",
    default=None,
    help=(
        "Only write metadata if this field's value changes. "
        "Overrides the config/env setting."
    ),
)
@click.option(
    "--with-llm-tags/--without-llm-tags",
    default=None,
    help=(
        "Enable or disable LLM-backed tag enrichment (year, duration, genre). "
        "Overrides the TAGUPDATER_LLM_TAGGING_ENABLED config/env setting (on by default)."
    ),
)
@click.option(
    "--verbose",
    is_flag=True,
    default=False,
    help="Print computed tag values for each file.",
)
@click.option(
    "--tags",
    default=None,
    help=(
        "Comma-separated list of tag keys to run (skips all others). "
        "Respects only_if_unset — won't overwrite existing values. "
        "E.g. --tags genre,country"
    ),
)
@click.option(
    "--retag",
    default=None,
    help=(
        "Comma-separated list of tag keys to re-run and overwrite even if already set. "
        "E.g. --retag genre,country"
    ),
)
def update_tags(
    file_identifier,
    all,
    modified_since,
    dry_run,
    trigger_field,
    with_llm_tags,
    verbose,
    tags,
    retag,
):
    """Run the auto-tagger on a specific song sheet or all of them."""
    if not file_identifier and not all and not modified_since:
        click.echo(
            "Error: Either a file identifier, the --all flag, or --modified-since "
            "must be provided.",
            err=True,
        )
        raise click.Abort()
    if file_identifier and all:
        click.echo(
            "Error: Cannot use both a file identifier and the --all flag.", err=True
        )
        raise click.Abort()
    if file_identifier and modified_since:
        click.echo(
            "Error: Cannot use both a file identifier and --modified-since.", err=True
        )
        raise click.Abort()
    if tags and retag:
        click.echo("Error: Cannot use both --tags and --retag.", err=True)
        raise click.Abort()

    settings = get_settings()
    credential_config = settings.google_cloud.credentials.get("tag-updater")
    if not credential_config:
        click.echo("Error: credential config 'tag-updater' not found.", err=True)
        raise click.Abort()

    creds = get_credentials(
        scopes=credential_config.scopes, target_principal=credential_config.principal
    )
    drive_service = build("drive", "v3", credentials=creds)
    docs_service = build("docs", "v1", credentials=creds)
    activity_service = build("driveactivity", "v2", credentials=creds)
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
    elif modified_since:
        click.echo(f"Fetching song sheets modified since {modified_since}...")
        files_to_process = gdrive_client.query_drive_files(
            settings.song_sheets.folder_ids, modified_after=modified_since
        )
        click.echo(f"Found {len(files_to_process)} file(s) modified since cutoff.")
    else:  # --all flag
        click.echo("Fetching all song sheets from Drive...")
        files_to_process = gdrive_client.query_drive_files(
            settings.song_sheets.folder_ids
        )

    effective_trigger_field = (
        trigger_field
        if trigger_field is not None
        else settings.tag_updater.trigger_field
    )
    effective_llm_tagging = (
        with_llm_tags
        if with_llm_tags is not None
        else settings.tag_updater.llm_tagging_enabled
    )
    if effective_llm_tagging:
        genai_client = genai.Client(
            vertexai=True,
            project=settings.google_cloud.project_id,
            location=settings.caching.gcs.region or "us-central1",
        )
    else:
        genai_client = None
        click.echo("LLM tagging disabled (use --with-llm-tags to enable).")
    metadata_store = (
        get_metadata_store()
        if settings.metadata_store.firestore_write_enabled
        else None
    )
    metadata_reader = metadata_store or get_metadata_store()
    if metadata_store is not None:
        click.echo(
            "Firestore metadata write enabled (collection "
            f"'{settings.metadata_store.firestore_collection}')."
        )
    tags_keys = {k.strip() for k in tags.split(",")} if tags else None
    retag_keys = {k.strip() for k in retag.split(",")} if retag else None
    if tags_keys:
        click.echo(f"Running only: {', '.join(sorted(tags_keys))}")
    if retag_keys:
        click.echo(f"Re-tagging (force overwrite): {', '.join(sorted(retag_keys))}")
    tagger = Tagger(
        drive_service=drive_service,
        docs_service=docs_service,
        activity_service=activity_service,
        trigger_field=effective_trigger_field,
        genai_client=genai_client,
        llm_tagging_enabled=effective_llm_tagging,
        metadata_store=metadata_store,
        metadata_reader=metadata_reader,
        tags=tags_keys,
        retag=retag_keys,
    )
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

            tagger.update_tags(file_obj, dry_run=dry_run, verbose=verbose)
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
