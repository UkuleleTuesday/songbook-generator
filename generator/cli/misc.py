import sys
from pathlib import Path
from typing import Optional

import click
import fitz

from ..common.config import get_settings
from .utils import global_options


@click.command(name="print-settings")
def print_settings():
    """Prints the current settings for debugging purposes."""
    click.echo("Current application settings:")
    settings = get_settings()
    click.echo(settings.model_dump_json(indent=2))


@click.command(name="validate-pdf")
@global_options
@click.argument("pdf_path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--manifest",
    "-m",
    type=click.Path(exists=True, path_type=Path),
    help="Path to manifest.json file for enhanced validation",
)
@click.option(
    "--check-structure",
    is_flag=True,
    default=True,
    help="Validate songbook-specific structure",
)
@click.option(
    "--min-pages", type=int, default=3, help="Minimum number of pages expected"
)
@click.option("--max-size-mb", type=int, default=25, help="Maximum file size in MB")
@click.option("--expected-title", type=str, help="Expected PDF title in metadata")
@click.option(
    "--expected-author",
    type=str,
    default="Ukulele Tuesday",
    help="Expected PDF author in metadata",
)
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
def validate_pdf_cli(
    pdf_path: Path,
    manifest: Optional[Path],
    check_structure: bool,
    min_pages: int,
    max_size_mb: int,
    expected_title: str,
    expected_author: str,
    verbose: bool,
    **kwargs,
):
    """
    Validate a PDF file for basic sanity checks.

    This command performs comprehensive validation of a PDF file to ensure
    it's not corrupted and meets basic quality standards for a songbook.

    If a manifest.json file is provided, additional validation will be
    performed using the rich metadata from the generation process.
    """
    from ..validation import (
        PDFValidationError,
        validate_pdf_file,
        validate_pdf_with_manifest,
    )

    try:
        if manifest:
            # Use enhanced validation with manifest
            validate_pdf_with_manifest(
                pdf_path=pdf_path,
                manifest_path=manifest,
                verbose=verbose,
            )
        else:
            # Use standard validation
            validate_pdf_file(
                pdf_path=pdf_path,
                check_structure=check_structure,
                min_pages=min_pages,
                max_size_mb=max_size_mb,
                expected_title=expected_title,
                expected_author=expected_author,
                verbose=verbose,
            )

        if not verbose:
            click.echo("✅ PDF validation passed")

    except PDFValidationError as e:
        click.echo(f"❌ PDF validation failed: {e}", err=True)
        sys.exit(1)
    except (OSError, IOError, fitz.FileDataError) as e:
        click.echo(f"❌ Error accessing PDF file: {e}", err=True)
        sys.exit(1)
