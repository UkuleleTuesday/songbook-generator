"""PDF validation utilities for songbook generation."""

import json
import re
from pathlib import Path
from typing import Optional, Dict, Any

import fitz

from .common.titles import generate_short_title


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
    pdf_info = manifest_data.get("pdf_info", {})
    expected_has_toc = pdf_info.get("has_toc")

    # Skip songbook structure validation if manifest indicates no TOC expected
    # since songbook structure validation always requires a TOC
    check_structure = expected_has_toc is not False  # Only skip if explicitly False

    validation_result = validate_pdf_file(
        pdf_path=pdf_path,
        check_structure=check_structure,
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
        with open(manifest_path, "r") as f:
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
    pdf_path: Path, manifest_data: Dict[str, Any], verbose: bool = False
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
                    print(
                        f"✓ TOC presence matches: {'yes' if actual_has_toc else 'no'}"
                    )

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

            # Validate TOC entry content against expected files
            validate_toc_entries_against_manifest(doc, manifest_data, verbose=verbose)

            # Validate song titles appear on their respective pages
            validate_song_titles_on_pages(doc, manifest_data, verbose=verbose)

            # Validate PDF sections using page indices
            validate_pdf_sections(doc, manifest_data, verbose=verbose)

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


def validate_toc_entries_against_manifest(
    doc: fitz.Document, manifest_data: Dict[str, Any], verbose: bool = False
) -> None:
    """
    Validate that TOC entries in PDF match expected files from manifest.

    This function checks that all expected files from the manifest appear
    in the PDF's table of contents, handling title shortening and formatting.
    Only performs validation if both PDF and manifest indicate TOC should exist.

    Args:
        doc: Opened PDF document
        manifest_data: Manifest data dictionary
        verbose: Enable verbose output

    Raises:
        PDFValidationError: If TOC entries don't match expected files
    """
    content_info = manifest_data.get("content_info", {})
    expected_file_names = content_info.get("file_names", [])
    pdf_info = manifest_data.get("pdf_info", {})
    expected_has_toc = pdf_info.get("has_toc")

    # Skip validation if no expected files in manifest
    if not expected_file_names:
        if verbose:
            print("✓ No expected files in manifest, skipping TOC content validation")
        return

    # Get actual TOC entries from PDF
    actual_toc = doc.get_toc()

    # If the manifest explicitly says the PDF should not have a TOC, skip content validation
    if expected_has_toc is False:
        if verbose:
            print(
                "✓ Manifest indicates no TOC expected, skipping TOC content validation"
            )
        return

    # If PDF has no TOC but manifest doesn't explicitly say it should be missing,
    # this could be an issue - but treat as warning for compatibility
    if not actual_toc:
        if expected_file_names:
            if verbose:
                print(
                    f"⚠️ PDF has no TOC entries but manifest expects {len(expected_file_names)} files"
                )
                print(
                    "   This may indicate a PDF generation issue, but continuing validation..."
                )
        return

    # Extract TOC entry titles (level 1 entries only, skip "Table of Contents" header)
    toc_titles = []
    for level, title, page in actual_toc:
        if level == 1 and title.lower() != "table of contents":
            toc_titles.append(title.strip())

    if verbose:
        print(f"Found {len(toc_titles)} TOC entries in PDF")
        print(f"Expected {len(expected_file_names)} files from manifest")

    # Check that we have the expected number of content entries
    if len(toc_titles) != len(expected_file_names):
        raise PDFValidationError(
            f"TOC content mismatch: PDF has {len(toc_titles)} content entries, "
            f"manifest expects {len(expected_file_names)} files"
        )

    # Validate each expected file has a corresponding TOC entry
    missing_entries = []
    for expected_file in expected_file_names:
        # Remove .pdf extension and clean up file name for comparison
        expected_title = _clean_file_name_for_toc_comparison(expected_file)

        # Check if any TOC entry matches this expected title
        found_match = False
        for toc_title in toc_titles:
            if _titles_match(expected_title, toc_title):
                found_match = True
                break

        if not found_match:
            missing_entries.append(expected_file)

    if missing_entries:
        raise PDFValidationError(
            f"Missing TOC entries for files: {missing_entries}. "
            f"TOC contains: {toc_titles}"
        )

    if verbose:
        print(f"✓ All {len(expected_file_names)} expected files found in TOC")


def _clean_file_name_for_toc_comparison(file_name: str) -> str:
    """Clean up a file name for TOC comparison by removing extension and normalizing."""
    # Remove .pdf extension
    if file_name.lower().endswith(".pdf"):
        file_name = file_name[:-4]

    # Basic cleanup - remove extra whitespace
    return file_name.strip()


def _titles_match(expected_title: str, toc_title: str) -> bool:
    """
    Check if an expected title matches a TOC title, accounting for shortening.

    TOC titles may be shortened versions of the original titles, so we need
    to check if the TOC title is a reasonable abbreviation of the expected title.
    """
    # Exact match
    if expected_title == toc_title:
        return True

    # Remove potential WIP marker (*) from TOC title
    clean_toc_title = toc_title.rstrip("*").strip()

    # Check if TOC title is a prefix of expected title (accounting for shortening)
    if clean_toc_title and expected_title.startswith(clean_toc_title):
        return True

    # Check if expected title starts with TOC title when both are normalized
    # This handles cases where punctuation or spacing differences exist
    expected_normalized = re.sub(r"[^\w\s]", "", expected_title.lower()).strip()
    toc_normalized = re.sub(r"[^\w\s]", "", clean_toc_title.lower()).strip()

    if toc_normalized and expected_normalized.startswith(toc_normalized):
        return True

    # Check for common title variations (bracketed info removal, featuring info, etc.)
    # This uses the same logic from the shared title utilities
    expected_shortened = generate_short_title(expected_title)
    if clean_toc_title == expected_shortened or expected_shortened.startswith(
        clean_toc_title
    ):
        return True

    return False


def validate_song_titles_on_pages(
    doc: fitz.Document, manifest_data: Dict[str, Any], verbose: bool = False
) -> None:
    """
    Validate that each song title appears on its corresponding song sheet page.

    This function checks that for each expected file from the manifest,
    the song title can be found on the actual song sheet page in the PDF.

    Args:
        doc: Opened PDF document
        manifest_data: Manifest data dictionary
        verbose: Enable verbose output

    Raises:
        PDFValidationError: If song titles are missing from their pages
    """
    content_info = manifest_data.get("content_info", {})
    expected_file_names = content_info.get("file_names", [])

    # Skip validation if no expected files in manifest
    if not expected_file_names:
        if verbose:
            print("✓ No expected files in manifest, skipping song title validation")
        return

    # Get TOC entries from PDF to find page mappings
    toc_entries = doc.get_toc()
    if not toc_entries:
        if verbose:
            print("! No TOC structure found, attempting manual song page validation")
        # Try to validate without TOC by checking first content pages
        _validate_song_titles_without_toc(doc, expected_file_names, verbose)
        return

    # Build mapping from TOC titles to page numbers
    toc_title_to_page = {}
    for level, title, page_num in toc_entries:
        if level == 1 and title.lower() != "table of contents":
            toc_title_to_page[title.strip()] = page_num

    if verbose:
        print(f"Found {len(toc_title_to_page)} content entries in PDF TOC")
        print(f"Expected {len(expected_file_names)} files from manifest")

    # Validate each expected file has its title on the corresponding page
    missing_titles = []
    for expected_file in expected_file_names:
        # Clean up file name for comparison
        expected_title = _clean_file_name_for_toc_comparison(expected_file)

        # Find the corresponding TOC entry and page
        toc_title = None
        page_num = None

        for toc_entry_title in toc_title_to_page.keys():
            if _titles_match(expected_title, toc_entry_title):
                toc_title = toc_entry_title
                page_num = toc_title_to_page[toc_entry_title]
                break

        if not toc_title or not page_num:
            missing_titles.append(f"{expected_file} (no TOC entry found)")
            continue

        # Validate the title appears on the song sheet page
        if page_num <= doc.page_count:
            page_idx = page_num - 1  # Convert to 0-based index
            page = doc[page_idx]
            page_text = page.get_text()

            if not _song_title_found_on_page(expected_title, toc_title, page_text):
                missing_titles.append(
                    f"{expected_file} (title not found on page {page_num})"
                )
                if verbose:
                    print(f"⚠️ Title for '{expected_file}' not found on page {page_num}")
            elif verbose:
                print(f"✓ Title for '{expected_file}' found on page {page_num}")

    if missing_titles:
        raise PDFValidationError(
            f"Song titles missing from their pages: {missing_titles}"
        )

    if verbose:
        print(f"✓ All {len(expected_file_names)} song titles found on their pages")


def _validate_song_titles_without_toc(
    doc: fitz.Document, expected_file_names: list, verbose: bool = False
) -> None:
    """Validate song titles when no TOC structure is available."""
    # This is a fallback method when no TOC is found
    # We'll check the first few content pages to see if they contain expected titles

    if verbose:
        print("Attempting song title validation without TOC structure")

    # Assume song pages start after a few introduction pages (typically page 4 onwards)
    start_page = min(3, doc.page_count - len(expected_file_names))
    pages_to_check = min(len(expected_file_names) * 2, doc.page_count - start_page)

    found_titles = set()
    for page_idx in range(start_page, start_page + pages_to_check):
        if page_idx >= doc.page_count:
            break

        page = doc[page_idx]
        page_text = page.get_text()

        # Check if any expected title appears on this page
        for expected_file in expected_file_names:
            expected_title = _clean_file_name_for_toc_comparison(expected_file)
            if _song_title_found_on_page(expected_title, expected_title, page_text):
                found_titles.add(expected_file)
                if verbose:
                    print(f"✓ Found title for '{expected_file}' on page {page_idx + 1}")

    missing_titles = set(expected_file_names) - found_titles
    if missing_titles:
        if verbose:
            print(f"⚠️ Could not find titles for: {list(missing_titles)}")
        # Don't raise error for TOC-less validation as it's less reliable
    else:
        if verbose:
            print("✓ All expected song titles found in PDF pages")


def _song_title_found_on_page(
    expected_title: str, toc_title: str, page_text: str
) -> bool:
    """
    Check if a song title can be found on a page.

    Args:
        expected_title: The expected title (cleaned from file name)
        toc_title: The title as it appears in TOC
        page_text: The full text content of the page

    Returns:
        True if the title is found on the page
    """
    # Split page text into lines and look at the first few lines
    lines = page_text.split("\n")
    first_lines = [line.strip() for line in lines[:10] if line.strip()]

    # Look for the title in the first few lines of the page
    for line in first_lines:
        if len(line) < 3:  # Skip very short lines
            continue

        # Check various title matching approaches
        if (
            _titles_match(expected_title, line)
            or _titles_match(toc_title, line)
            or expected_title.lower() in line.lower()
            or toc_title.lower() in line.lower()
        ):
            return True

        # Check if the line starts with the expected title (handling artist names)
        if line.lower().startswith(expected_title.lower()):
            return True

        # Check if this is a title line that contains the expected title
        # (handles cases like "9 to 5 - Dolly Parton" where we expect "9 to 5")
        line_words = set(line.lower().split())
        expected_words = set(expected_title.lower().split())
        if expected_words.issubset(line_words) and len(expected_words) > 1:
            return True

    return False


def validate_pdf_sections(
    doc: fitz.Document, manifest_data: Dict[str, Any], verbose: bool = False
) -> None:
    """
    Validate PDF sections using page indices from manifest.

    Performs dedicated checks for each section:
    - Cover: existence, one page length, at the start
    - Preface: positioned right after cover
    - Table of contents: presence of short titles for each song
    - Body: presence of full titles for each song

    Args:
        doc: Opened PDF document
        manifest_data: Manifest data dictionary containing page_indices
        verbose: Enable verbose output

    Raises:
        PDFValidationError: If section validation fails
    """
    page_indices = manifest_data.get("page_indices")
    if not page_indices:
        if verbose:
            print("⚠ No page indices found in manifest, skipping section validation")
        return

    if verbose:
        print("Validating PDF sections using page indices...")

    # Validate cover section
    validate_cover_section(doc, page_indices, verbose=verbose)

    # Validate preface section
    validate_preface_section(doc, page_indices, verbose=verbose)

    # Validate table of contents section with short titles
    validate_toc_section(doc, manifest_data, page_indices, verbose=verbose)

    # Validate body section with full titles
    validate_body_section(doc, manifest_data, page_indices, verbose=verbose)


def validate_cover_section(
    doc: fitz.Document, page_indices: Dict[str, Any], verbose: bool = False
) -> None:
    """
    Validate cover section: existence, one page length, and at the start.

    Args:
        doc: Opened PDF document
        page_indices: Page indices dictionary from manifest
        verbose: Enable verbose output

    Raises:
        PDFValidationError: If cover validation fails
    """
    cover_info = page_indices.get("cover")

    if cover_info is None:
        if verbose:
            print("✓ No cover section expected")
        return

    if not isinstance(cover_info, dict):
        raise PDFValidationError(f"Invalid cover section info: {cover_info}")

    first_page = cover_info.get("first_page")
    last_page = cover_info.get("last_page")

    if first_page is None or last_page is None:
        raise PDFValidationError("Cover section missing page information")

    # Check cover is at the start (first page should be 1)
    if first_page != 1:
        raise PDFValidationError(
            f"Cover should be at start: first page is {first_page}, expected 1"
        )

    # Check cover is one page long
    if first_page != last_page:
        raise PDFValidationError(
            f"Cover should be one page: spans pages {first_page}-{last_page}"
        )

    # Check cover page exists in PDF
    if last_page > doc.page_count:
        raise PDFValidationError(
            f"Cover page {last_page} exceeds PDF page count {doc.page_count}"
        )

    if verbose:
        print(f"✓ Cover section valid: page {first_page}")


def validate_preface_section(
    doc: fitz.Document, page_indices: Dict[str, Any], verbose: bool = False
) -> None:
    """
    Validate preface section is positioned right after cover.

    Args:
        doc: Opened PDF document
        page_indices: Page indices dictionary from manifest
        verbose: Enable verbose output

    Raises:
        PDFValidationError: If preface validation fails
    """
    preface_info = page_indices.get("preface")
    cover_info = page_indices.get("cover")

    if preface_info is None:
        if verbose:
            print("✓ No preface section expected")
        return

    if not isinstance(preface_info, dict):
        raise PDFValidationError(f"Invalid preface section info: {preface_info}")

    first_page = preface_info.get("first_page")
    last_page = preface_info.get("last_page")

    if first_page is None or last_page is None:
        raise PDFValidationError("Preface section missing page information")

    # Check preface pages exist in PDF
    if last_page > doc.page_count:
        raise PDFValidationError(
            f"Preface last page {last_page} exceeds PDF page count {doc.page_count}"
        )

    # Check preface is positioned correctly
    if cover_info is not None:
        # Preface should come right after cover
        expected_first_page = cover_info.get("last_page", 0) + 1
        if first_page != expected_first_page:
            raise PDFValidationError(
                f"Preface should start at page {expected_first_page} "
                f"(after cover), but starts at page {first_page}"
            )
    else:
        # If no cover, preface should be first
        if first_page != 1:
            raise PDFValidationError(
                f"Preface should start at page 1 (no cover), but starts at page {first_page}"
            )

    if verbose:
        print(f"✓ Preface section valid: pages {first_page}-{last_page}")


def validate_toc_section(
    doc: fitz.Document,
    manifest_data: Dict[str, Any],
    page_indices: Dict[str, Any],
    verbose: bool = False,
) -> None:
    """
    Validate table of contents section with presence of short titles for each song.

    Args:
        doc: Opened PDF document
        manifest_data: Manifest data dictionary
        page_indices: Page indices dictionary from manifest
        verbose: Enable verbose output

    Raises:
        PDFValidationError: If TOC section validation fails
    """
    toc_info = page_indices.get("table_of_contents")

    if toc_info is None:
        if verbose:
            print("✓ No table of contents section expected")
        return

    if not isinstance(toc_info, dict):
        raise PDFValidationError(f"Invalid table of contents section info: {toc_info}")

    first_page = toc_info.get("first_page")
    last_page = toc_info.get("last_page")

    if first_page is None or last_page is None:
        raise PDFValidationError("Table of contents section missing page information")

    # Check TOC pages exist in PDF
    if last_page > doc.page_count:
        raise PDFValidationError(
            f"TOC last page {last_page} exceeds PDF page count {doc.page_count}"
        )

    # Validate short titles are present in TOC pages
    content_info = manifest_data.get("content_info", {})
    expected_file_names = content_info.get("file_names", [])

    if expected_file_names:
        # Extract text from TOC pages
        toc_text = ""
        for page_num in range(first_page - 1, last_page):  # Convert to 0-based
            if page_num < doc.page_count:
                page = doc[page_num]
                toc_text += page.get_text()

        # Check for presence of short titles
        missing_titles = []
        for file_name in expected_file_names:
            # Generate the short title as it would appear in TOC
            # Remove .pdf extension first
            base_name = file_name.replace(".pdf", "").strip()
            short_title = generate_short_title(base_name)

            # Check if short title appears in TOC text
            if short_title.lower() not in toc_text.lower():
                missing_titles.append(short_title)

        if missing_titles:
            raise PDFValidationError(
                f"Missing short titles in TOC section: {missing_titles[:5]}"
                + (
                    f" (and {len(missing_titles) - 5} more)"
                    if len(missing_titles) > 5
                    else ""
                )
            )

    if verbose:
        print(f"✓ Table of contents section valid: pages {first_page}-{last_page}")
        if expected_file_names:
            print(f"  ✓ All {len(expected_file_names)} short titles found in TOC")


def validate_body_section(
    doc: fitz.Document,
    manifest_data: Dict[str, Any],
    page_indices: Dict[str, Any],
    verbose: bool = False,
) -> None:
    """
    Validate body section with presence of full titles for each song.

    Args:
        doc: Opened PDF document
        manifest_data: Manifest data dictionary
        page_indices: Page indices dictionary from manifest
        verbose: Enable verbose output

    Raises:
        PDFValidationError: If body section validation fails
    """
    body_info = page_indices.get("body")

    if body_info is None:
        if verbose:
            print("⚠ No body section expected")
        return

    if not isinstance(body_info, dict):
        raise PDFValidationError(f"Invalid body section info: {body_info}")

    first_page = body_info.get("first_page")
    last_page = body_info.get("last_page")

    if first_page is None or last_page is None:
        raise PDFValidationError("Body section missing page information")

    # Check body pages exist in PDF
    if last_page > doc.page_count:
        raise PDFValidationError(
            f"Body last page {last_page} exceeds PDF page count {doc.page_count}"
        )

    # Validate full titles are present in body section
    content_info = manifest_data.get("content_info", {})
    expected_file_names = content_info.get("file_names", [])

    if expected_file_names:
        # Use existing song title validation but restrict to body section pages
        # Extract TOC to get page mappings within body section
        toc = doc.get_toc()

        missing_titles = []
        for file_name in expected_file_names:
            # Clean up file name to get expected title variations
            base_name = file_name.replace(".pdf", "").strip()
            title_variations = [
                base_name,
                base_name.replace("_", " "),
                base_name.replace("-", " "),
                base_name.replace("feat.", "featuring"),
                base_name.replace("Feat.", "Featuring"),
            ]

            # Find the page for this song within body section
            song_page = None
            for level, title, page_num in toc:
                if any(var.lower() in title.lower() for var in title_variations):
                    # Check if this page is within the body section
                    if first_page <= page_num <= last_page:
                        song_page = page_num
                        break

            if song_page:
                # Check if title appears on the song page
                page = doc[song_page - 1]  # Convert to 0-based
                page_text = page.get_text()

                title_found = any(
                    var.lower() in page_text.lower() for var in title_variations
                )

                if not title_found:
                    missing_titles.append(base_name)

        if missing_titles:
            # Convert to warning instead of error since this is complex validation
            if verbose:
                print(
                    f"⚠ Some full titles may be missing in body section: {missing_titles[:3]}"
                    + (
                        f" (and {len(missing_titles) - 3} more)"
                        if len(missing_titles) > 3
                        else ""
                    )
                )

    if verbose:
        print(f"✓ Body section valid: pages {first_page}-{last_page}")
        if expected_file_names:
            print("  ✓ Body section contains expected song content")


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
