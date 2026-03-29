import warnings

# Suppress deprecation warning from google package about pkg_resources
warnings.filterwarnings("ignore", message="pkg_resources is deprecated")

import logging

import click

from .cache import cache
from .editions import editions
from .generate import generate
from .misc import print_settings, validate_pdf_cli
from .songs import songs
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
cli.add_command(songs)
cli.add_command(cache)
cli.add_command(print_settings)
cli.add_command(validate_pdf_cli)
cli.add_command(specialbooks)
cli.add_command(editions)
cli.add_command(tags)

if __name__ == "__main__":
    cli()
