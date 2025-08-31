"""PDF validation utilities for songbook generation."""

from pathlib import Path
from typing import Optional

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
