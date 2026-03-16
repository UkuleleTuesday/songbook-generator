import warnings

# Suppress deprecation warning from google package about pkg_resources
warnings.filterwarnings("ignore", message="pkg_resources is deprecated")

import logging

import click

from .cache import download_cache_command, merge_pdfs, sync_cache_command
from .editions import editions
from .generate import generate, generate_from_folder, list_songs
from .misc import download_doc_json_command, print_settings, validate_pdf_cli
from .specialbooks import specialbooks
from .tags import tags
from .utils import global_options


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


cli.add_command(generate)
cli.add_command(generate_from_folder)
cli.add_command(list_songs)
cli.add_command(sync_cache_command)
cli.add_command(download_cache_command)
cli.add_command(merge_pdfs)
cli.add_command(print_settings)
cli.add_command(validate_pdf_cli)
cli.add_command(download_doc_json_command)
cli.add_command(specialbooks)
cli.add_command(editions)
cli.add_command(tags)

if __name__ == "__main__":
    cli()
