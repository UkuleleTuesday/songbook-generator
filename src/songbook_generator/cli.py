import click

from . import load_config_folder_ids, generate_songbook


@click.command()
@click.option(
    "--source-folder",
    "-s",
    multiple=True,
    default=load_config_folder_ids(),
    help="Drive folder IDs to read files from (can be passed multiple times)",
)
@click.option(
    "--limit",
    "-l",
    type=int,
    default=None,
    help="Limit the number of files to process (no limit by default)",
)
def cli(source_folder: str, limit: int):
    generate_songbook(source_folder, limit)
