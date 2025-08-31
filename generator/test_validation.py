import pytest
import fitz
from click.testing import CliRunner

from .validation import (
    validate_pdf_structure,
    validate_pdf_metadata,
    validate_pdf_content,
    validate_songbook_structure,
    PDFValidationError,
)
from .cli import validate_pdf_cli


@pytest.fixture
def valid_songbook_pdf(tmp_path):
    """Create a valid songbook PDF for testing."""
    pdf_path = tmp_path / "valid_songbook.pdf"

    doc = fitz.open()

    # Cover page
    cover_page = doc.new_page()
    cover_page.insert_text((100, 100), "Ukulele Tuesday Songbook", fontsize=20)

    # TOC page
    toc_page = doc.new_page()
    toc_page.insert_text((100, 100), "Table of Contents", fontsize=16)
    toc_page.insert_text((100, 150), "1. Test Song .................. 3", fontsize=12)

    # Content page
    content_page = doc.new_page()
    content_page.insert_text((100, 100), "Test Song", fontsize=16)
    content_page.insert_text((100, 150), "This is a test song content", fontsize=12)

    # Set proper metadata
    doc.set_metadata(
        {
            "title": "Test Songbook",
            "author": "Ukulele Tuesday",
            "creator": "Ukulele Tuesday Songbook Generator",
            "subject": "Test songbook for validation",
        }
    )

    doc.save(pdf_path)
    doc.close()

    return pdf_path


@pytest.fixture
def invalid_pdf(tmp_path):
    """Create an invalid PDF file for testing."""
    pdf_path = tmp_path / "invalid.pdf"
    pdf_path.write_text("This is not a PDF file")
    return pdf_path


@pytest.fixture
def empty_pdf(tmp_path):
    """Create an empty PDF file for testing."""
    pdf_path = tmp_path / "empty.pdf"
    pdf_path.write_bytes(b"")
    return pdf_path


@pytest.fixture
def pdf_with_missing_metadata(tmp_path):
    """Create a PDF with missing required metadata."""
    pdf_path = tmp_path / "missing_metadata.pdf"

    doc = fitz.open()
    for i in range(4):  # Enough pages to pass page count check
        page = doc.new_page()
        page.insert_text((100, 100), f"Page {i + 1} content", fontsize=12)

    # Missing required metadata
    doc.set_metadata({"title": ""})  # Empty title

    doc.save(pdf_path)
    doc.close()

    return pdf_path


@pytest.fixture
def pdf_too_few_pages(tmp_path):
    """Create a PDF with too few pages."""
    pdf_path = tmp_path / "few_pages.pdf"

    doc = fitz.open()
    page = doc.new_page()  # Only 1 page
    page.insert_text((100, 100), "Single page", fontsize=12)

    doc.set_metadata(
        {"title": "Test", "author": "Test Author", "creator": "Test Creator"}
    )

    doc.save(pdf_path)
    doc.close()

    return pdf_path


def test_validate_pdf_structure_valid_pdf(valid_songbook_pdf):
    """Test that valid PDF passes structure validation."""
    # Should not raise any exception
    validate_pdf_structure(valid_songbook_pdf)


def test_validate_pdf_structure_nonexistent_file(tmp_path):
    """Test that nonexistent file fails validation."""
    nonexistent_path = tmp_path / "nonexistent.pdf"

    with pytest.raises(PDFValidationError, match="PDF file does not exist"):
        validate_pdf_structure(nonexistent_path)


def test_validate_pdf_structure_empty_file(empty_pdf):
    """Test that empty file fails validation."""
    with pytest.raises(PDFValidationError, match="PDF file is empty"):
        validate_pdf_structure(empty_pdf)


def test_validate_pdf_structure_corrupted_file(invalid_pdf):
    """Test that corrupted file fails validation."""
    with pytest.raises(PDFValidationError, match="PDF file is corrupted"):
        validate_pdf_structure(invalid_pdf)


def test_validate_pdf_metadata_valid_metadata(valid_songbook_pdf):
    """Test that valid metadata passes validation."""
    # Should not raise any exception
    validate_pdf_metadata(valid_songbook_pdf)


def test_validate_pdf_metadata_with_expected_values(valid_songbook_pdf):
    """Test metadata validation with expected values."""
    expected = {"title": "Test Songbook", "author": "Ukulele Tuesday"}

    # Should not raise any exception
    validate_pdf_metadata(valid_songbook_pdf, expected)


def test_validate_pdf_metadata_missing_required_field(pdf_with_missing_metadata):
    """Test that missing required metadata fails validation."""
    with pytest.raises(
        PDFValidationError, match="Missing or empty required metadata field: title"
    ):
        validate_pdf_metadata(pdf_with_missing_metadata)


def test_validate_pdf_metadata_wrong_expected_value(valid_songbook_pdf):
    """Test that wrong expected metadata value fails validation."""
    expected = {"title": "Wrong Title"}

    with pytest.raises(
        PDFValidationError,
        match="Metadata field 'title' has value 'Test Songbook', expected 'Wrong Title'",
    ):
        validate_pdf_metadata(valid_songbook_pdf, expected)


def test_validate_pdf_content_valid_content(valid_songbook_pdf):
    """Test that valid content passes validation."""
    # Should not raise any exception
    validate_pdf_content(valid_songbook_pdf, min_pages=3, max_size_mb=25)


def test_validate_pdf_content_too_few_pages(pdf_too_few_pages):
    """Test that PDF with too few pages fails validation."""
    with pytest.raises(
        PDFValidationError, match="PDF has too few pages: 1 \\(min: 3\\)"
    ):
        validate_pdf_content(pdf_too_few_pages, min_pages=3)


def test_validate_songbook_structure_valid_structure(valid_songbook_pdf):
    """Test that valid songbook structure passes validation."""
    # Should not raise any exception
    validate_songbook_structure(valid_songbook_pdf)


def test_validate_songbook_structure_too_short(pdf_too_few_pages):
    """Test that songbook with too few pages fails validation."""
    with pytest.raises(
        PDFValidationError,
        match="Songbook too short: 1 pages \\(expected at least 3\\)",
    ):
        validate_songbook_structure(pdf_too_few_pages)


def test_validate_songbook_structure_no_toc(tmp_path):
    """Test that songbook without TOC fails validation."""
    pdf_path = tmp_path / "no_toc.pdf"

    doc = fitz.open()
    for i in range(4):
        page = doc.new_page()
        page.insert_text((100, 100), f"Page {i + 1} - no TOC here", fontsize=12)

    doc.set_metadata(
        {"title": "Test", "author": "Test Author", "creator": "Test Creator"}
    )

    doc.save(pdf_path)
    doc.close()

    with pytest.raises(
        PDFValidationError, match="No table of contents found in first 5 pages"
    ):
        validate_songbook_structure(pdf_path)


def test_cli_valid_pdf(valid_songbook_pdf):
    """Test CLI with valid PDF."""
    runner = CliRunner()
    result = runner.invoke(validate_pdf_cli, [str(valid_songbook_pdf), "--verbose"])

    assert result.exit_code == 0
    assert "✅ PDF validation passed" in result.output
    assert "Pages: 3" in result.output


def test_cli_invalid_pdf(invalid_pdf):
    """Test CLI with invalid PDF."""
    runner = CliRunner()
    result = runner.invoke(validate_pdf_cli, [str(invalid_pdf)])

    assert result.exit_code == 1
    assert "❌ PDF validation failed" in result.output


def test_cli_with_expected_metadata(valid_songbook_pdf):
    """Test CLI with expected metadata parameters."""
    runner = CliRunner()
    result = runner.invoke(
        validate_pdf_cli,
        [
            str(valid_songbook_pdf),
            "--expected-title",
            "Test Songbook",
            "--expected-author",
            "Ukulele Tuesday",
            "--verbose",
        ],
    )

    assert result.exit_code == 0
    assert "✅ PDF validation passed" in result.output


def test_cli_with_wrong_expected_metadata(valid_songbook_pdf):
    """Test CLI with wrong expected metadata."""
    runner = CliRunner()
    result = runner.invoke(
        validate_pdf_cli, [str(valid_songbook_pdf), "--expected-title", "Wrong Title"]
    )

    assert result.exit_code == 1
    assert "❌ PDF validation failed" in result.output
    assert "Wrong Title" in result.output
