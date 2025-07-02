import click
from pathlib import Path
from typing import Dict, Optional

from config import load_config_folder_ids, load_cover_config
from pdf import generate_songbook


def make_cli_progress_callback():
    """Return a callback that displays progress updates to the console."""

    def _callback(percent: float, message: str = None):
        percentage = int(percent * 100)
        click.echo(f"[{percentage:3d}%] {message or ''}")

    return _callback


def parse_property_filters(filter_strings) -> Optional[Dict[str, str]]:
    """
    Parse property filter strings into a dictionary.
    
    Args:
        filter_strings: Tuple of strings in format "key=value"
        
    Returns:
        Dict of property filters, or None if empty
    """
    if not filter_strings:
        return None
    
    filters = {}
    for filter_str in filter_strings:
        if "=" not in filter_str:
            raise click.BadParameter(f"Invalid filter format: {filter_str}. Use key=value format.")
        
        key, value = filter_str.split("=", 1)
        filters[key.strip()] = value.strip()
    
    return filters


@click.command()
@click.option(
    "--source-folder",
    "-s",
    multiple=True,
    default=load_config_folder_ids(),
    help="Drive folder IDs to read files from (can be passed multiple times)",
)
@click.option(
    "--destination-path",
    "-d",
    required=True,
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
    default=load_cover_config(),
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
    "filters",
    multiple=True,
    help="Filter files by custom properties. Format: key=value (can be used multiple times). Example: --filter artist=Beatles --filter difficulty=easy",
)
def cli(
    source_folder: str,
    destination_path: Path,
    open_generated_pdf,
    cover_file_id: str,
    limit: int,
    filters,
):
    # Parse property filters
    try:
        property_filters = parse_property_filters(filters)
    except click.BadParameter as e:
        click.echo(f"Error: {e}")
        return
    
    if property_filters:
        click.echo(f"Applying filters: {property_filters}")
    
    progress_callback = make_cli_progress_callback()
    generate_songbook(
        source_folder, destination_path, limit, cover_file_id, property_filters, progress_callback
    )
    if open_generated_pdf:
        click.echo(f"Opening generated songbook: {destination_path}")
        click.launch(destination_path)


cli()
