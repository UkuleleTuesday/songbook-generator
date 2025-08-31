"""PDF validation utilities for songbook generation."""

import json
from pathlib import Path
from typing import Optional, Dict, Any

import fitz


class PDFValidationError(Exception):
    """Raised when PDF validation fails."""

    pass


def validate_pdf_structure(pdf_path: Path) -> None:
    """Validate basic PDF structure and integrity."""
    if not pdf_path.exists():
        raise PDFValidationError(f"PDF file does not exist: {pdf_path}")

    if pdf_path.stat().st_size == 0:
        raise PDFValidationError(f"PDF file is empty: {pdf_path}")

    try:
        with fitz.open(pdf_path) as doc:
            if doc.page_count == 0:
                raise PDFValidationError("PDF has no pages")

            # Try to access the first page to ensure the PDF isn't corrupted
            page = doc[0]
            _ = page.get_text()  # This will fail if the page is corrupted

    except fitz.FileDataError as e:
        raise PDFValidationError(f"PDF file is corrupted: {e}")
    except (OSError, IOError) as e:
        raise PDFValidationError(f"Failed to read PDF: {e}")


def validate_pdf_metadata(
    pdf_path: Path, expected_metadata: Optional[dict] = None
) -> None:
    """Validate PDF metadata is properly set."""
    try:
        with fitz.open(pdf_path) as doc:
            metadata = doc.metadata

            # Check required metadata fields are present and not empty
            required_fields = ["title", "author", "creator"]
            for field in required_fields:
                if not metadata.get(field):
                    raise PDFValidationError(
                        f"Missing or empty required metadata field: {field}"
                    )

            # Check expected values if provided
            if expected_metadata:
                for field, expected_value in expected_metadata.items():
                    actual_value = metadata.get(field)
                    if actual_value != expected_value:
                        raise PDFValidationError(
                            f"Metadata field '{field}' has value '{actual_value}', "
                            f"expected '{expected_value}'"
                        )
    except fitz.FileDataError as e:
        raise PDFValidationError(f"PDF file is corrupted: {e}")


def validate_pdf_content(
    pdf_path: Path, min_pages: int = 1, max_size_mb: int = 25
) -> None:
    """Validate PDF content and size constraints."""
    # Check file size
    file_size_mb = pdf_path.stat().st_size / (1024 * 1024)
    if file_size_mb > max_size_mb:
        raise PDFValidationError(
            f"PDF file too large: {file_size_mb:.1f}MB (max: {max_size_mb}MB)"
        )

    try:
        with fitz.open(pdf_path) as doc:
            page_count = doc.page_count

            if page_count < min_pages:
                raise PDFValidationError(
                    f"PDF has too few pages: {page_count} (min: {min_pages})"
                )

            # Validate that we can extract text from at least some pages
            text_found = False
            pages_to_check = min(5, page_count)  # Check first 5 pages or all if less

            for page_num in range(pages_to_check):
                page = doc[page_num]
                text = page.get_text().strip()
                if text:
                    text_found = True
                    break

            if not text_found:
                raise PDFValidationError(
                    f"No text found in first {pages_to_check} pages - PDF may be corrupted or contain only images"
                )

    except fitz.FileDataError as e:
        raise PDFValidationError(f"PDF file is corrupted: {e}")


def validate_songbook_structure(pdf_path: Path) -> None:
    """Validate songbook-specific structure."""
    try:
        with fitz.open(pdf_path) as doc:
            page_count = doc.page_count

            # A songbook should have at least a cover and some content
            if page_count < 3:
                raise PDFValidationError(
                    f"Songbook too short: {page_count} pages (expected at least 3)"
                )

            # Check for Table of Contents - look for "Contents" or "Table of Contents" in early pages
            toc_found = False
            for page_num in range(min(5, page_count)):
                page_text = doc[page_num].get_text().lower()
                if "contents" in page_text or "table of contents" in page_text:
                    toc_found = True
                    break

            if not toc_found:
                raise PDFValidationError("No table of contents found in first 5 pages")

    except fitz.FileDataError as e:
        raise PDFValidationError(f"PDF file is corrupted: {e}")


def validate_pdf_with_manifest(
    pdf_path: Path,
    manifest_path: Path,
    verbose: bool = False,
) -> dict:
    """
    Enhanced PDF validation using manifest.json data.

    This function performs all standard PDF validations plus additional
    checks using the rich metadata from the manifest file.

    Args:
        pdf_path: Path to the PDF file
        manifest_path: Path to the manifest.json file
        verbose: Enable verbose output

    Returns:
        Dictionary with validation results and file information

    Raises:
        PDFValidationError: If validation fails
    """
    if verbose:
        print(f"Validating PDF with manifest: {pdf_path}")
        print(f"Manifest file: {manifest_path}")

    # Load and validate manifest file
    manifest_data = load_manifest(manifest_path)

    # Run standard PDF validation first
    pdf_info = manifest_data.get("pdf_info", {})
    expected_title = pdf_info.get("title")
    expected_author = pdf_info.get("author", "Ukulele Tuesday")

    # Run basic validation
    validation_result = validate_pdf_file(
        pdf_path=pdf_path,
        check_structure=True,
        min_pages=3,  # Default for songbooks
        max_size_mb=25,  # Default limit
        expected_title=expected_title,
        expected_author=expected_author,
        verbose=verbose,
    )

    # Enhanced validation using manifest data
    validate_pdf_against_manifest(pdf_path, manifest_data, verbose=verbose)

    # Add manifest validation results to summary
    validation_result["manifest_validated"] = True
    validation_result["manifest_path"] = str(manifest_path)

    return validation_result


def load_manifest(manifest_path: Path) -> Dict[str, Any]:
    """Load and validate manifest.json file."""
    if not manifest_path.exists():
        raise PDFValidationError(f"Manifest file does not exist: {manifest_path}")

    try:
        with open(manifest_path, 'r') as f:
            manifest_data = json.load(f)
    except json.JSONDecodeError as e:
        raise PDFValidationError(f"Invalid JSON in manifest file: {e}")
    except (OSError, IOError) as e:
        raise PDFValidationError(f"Error reading manifest file: {e}")

    # Validate required manifest sections
    required_sections = ["job_id", "pdf_info"]
    for section in required_sections:
        if section not in manifest_data:
            raise PDFValidationError(f"Missing required section in manifest: {section}")

    return manifest_data


def validate_pdf_against_manifest(
    pdf_path: Path,
    manifest_data: Dict[str, Any],
    verbose: bool = False
) -> None:
    """Validate PDF properties against manifest expectations."""
    if verbose:
        print("Cross-validating PDF against manifest data...")

    pdf_info = manifest_data.get("pdf_info", {})

    try:
        with fitz.open(pdf_path) as doc:
            # Validate page count
            expected_page_count = pdf_info.get("page_count")
            if expected_page_count is not None:
                actual_page_count = doc.page_count
                if actual_page_count != expected_page_count:
                    raise PDFValidationError(
                        f"Page count mismatch: PDF has {actual_page_count} pages, "
                        f"manifest expects {expected_page_count}"
                    )
                if verbose:
                    print(f"✓ Page count matches: {actual_page_count}")

            # Validate file size
            expected_file_size = pdf_info.get("file_size_bytes")
            if expected_file_size is not None:
                actual_file_size = pdf_path.stat().st_size
                # Allow some tolerance for minor differences (1% or 1KB, whichever is larger)
                tolerance = max(expected_file_size * 0.01, 1024)
                if abs(actual_file_size - expected_file_size) > tolerance:
                    raise PDFValidationError(
                        f"File size mismatch: PDF is {actual_file_size} bytes, "
                        f"manifest expects {expected_file_size} bytes"
                    )
                if verbose:
                    print(f"✓ File size matches: {actual_file_size} bytes")

            # Validate TOC presence
            expected_has_toc = pdf_info.get("has_toc")
            if expected_has_toc is not None:
                actual_has_toc = bool(doc.get_toc())
                if actual_has_toc != expected_has_toc:
                    raise PDFValidationError(
                        f"TOC presence mismatch: PDF {'has' if actual_has_toc else 'does not have'} TOC, "
                        f"manifest expects {'TOC' if expected_has_toc else 'no TOC'}"
                    )
                if verbose:
                    print(f"✓ TOC presence matches: {'yes' if actual_has_toc else 'no'}")

            # Validate TOC entry count
            expected_toc_entries = pdf_info.get("toc_entries")
            if expected_toc_entries is not None:
                actual_toc_entries = len(doc.get_toc())
                if actual_toc_entries != expected_toc_entries:
                    raise PDFValidationError(
                        f"TOC entry count mismatch: PDF has {actual_toc_entries} TOC entries, "
                        f"manifest expects {expected_toc_entries}"
                    )
                if verbose:
                    print(f"✓ TOC entries match: {actual_toc_entries}")

            # Validate metadata fields from manifest
            for field in ["title", "subject", "author", "creator", "producer"]:
                expected_value = pdf_info.get(field)
                if expected_value:
                    actual_value = doc.metadata.get(field)
                    if actual_value != expected_value:
                        raise PDFValidationError(
                            f"Metadata field '{field}' mismatch: PDF has '{actual_value}', "
                            f"manifest expects '{expected_value}'"
                        )
                    if verbose:
                        print(f"✓ {field} matches: {actual_value}")

    except fitz.FileDataError as e:
        raise PDFValidationError(f"PDF file is corrupted: {e}")

    # Validate content information
    validate_content_info(manifest_data, verbose=verbose)


def validate_content_info(manifest_data: Dict[str, Any], verbose: bool = False) -> None:
    """Validate content information in manifest for consistency."""
    content_info = manifest_data.get("content_info", {})

    # Check content info consistency
    total_files = content_info.get("total_files")
    file_names = content_info.get("file_names", [])

    if total_files is not None and len(file_names) != total_files:
        raise PDFValidationError(
            f"Content info mismatch: manifest reports {total_files} total files "
            f"but lists {len(file_names)} file names"
        )

    if verbose and total_files is not None:
        print(f"✓ Content consistency: {total_files} files processed")

    # Validate generation info if present
    gen_info = manifest_data.get("generation_info", {})
    if gen_info:
        duration = gen_info.get("duration_seconds")
        if duration is not None and (duration < 0 or duration > 3600):  # Max 1 hour
            raise PDFValidationError(
                f"Suspicious generation duration: {duration} seconds"
            )
        if verbose and duration is not None:
            print(f"✓ Generation duration reasonable: {duration:.1f} seconds")


def validate_pdf_file(
    pdf_path: Path,
    check_structure: bool = True,
    min_pages: int = 3,
    max_size_mb: int = 25,
    expected_title: Optional[str] = None,
    expected_author: str = "Ukulele Tuesday",
    verbose: bool = False,
) -> dict:
    """
    Comprehensive PDF validation function.

    Returns a dictionary with validation results and file information.
    Raises PDFValidationError if validation fails.
    """
    if verbose:
        print(f"Validating PDF: {pdf_path}")

    try:
        # Basic structure validation
        if verbose:
            print("Checking PDF structure and integrity...")
        validate_pdf_structure(pdf_path)

        # Content validation
        if verbose:
            print(f"Checking content (min {min_pages} pages, max {max_size_mb}MB)...")
        validate_pdf_content(pdf_path, min_pages=min_pages, max_size_mb=max_size_mb)

        # Metadata validation
        expected_metadata = {}
        if expected_title:
            expected_metadata["title"] = expected_title
        if expected_author:
            expected_metadata["author"] = expected_author

        if verbose:
            print("Checking PDF metadata...")
        validate_pdf_metadata(pdf_path, expected_metadata)

        # Songbook structure validation
        if check_structure:
            if verbose:
                print("Checking songbook structure...")
            validate_songbook_structure(pdf_path)

        # Collect summary info
        with fitz.open(pdf_path) as doc:
            file_size_mb = pdf_path.stat().st_size / (1024 * 1024)
            summary = {
                "pages": doc.page_count,
                "size_mb": round(file_size_mb, 1),
                "title": doc.metadata.get("title", "Not set"),
                "author": doc.metadata.get("author", "Not set"),
                "valid": True,
            }

        if verbose:
            print("✅ PDF validation passed:")
            print(f"   Pages: {summary['pages']}")
            print(f"   Size: {summary['size_mb']}MB")
            print(f"   Title: {summary['title']}")
            print(f"   Author: {summary['author']}")

        return summary

    except PDFValidationError:
        raise
    except (OSError, IOError, fitz.FileDataError) as e:
        raise PDFValidationError(f"Error accessing PDF file: {e}")
