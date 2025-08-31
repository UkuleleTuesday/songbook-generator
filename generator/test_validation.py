import pytest
import json
import fitz
from click.testing import CliRunner

from .validation import (
    validate_pdf_structure,
    validate_pdf_metadata,
    validate_pdf_content,
    validate_songbook_structure,
    validate_pdf_with_manifest,
    load_manifest,
    validate_pdf_against_manifest,
    validate_content_info,
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


@pytest.fixture
def sample_manifest_data():
    """Create sample manifest data for testing."""
    return {
        "job_id": "test-job-123",
        "generated_at": "2024-01-01T12:00:00Z",
        "generation_info": {
            "start_time": "2024-01-01T11:55:00Z",
            "end_time": "2024-01-01T12:00:00Z",
            "duration_seconds": 300.0,
        },
        "input_parameters": {"limit": 100, "edition": "current"},
        "pdf_info": {
            "title": "Test Songbook",
            "subject": "Test Subject",
            "author": "Ukulele Tuesday",
            "creator": "Ukulele Tuesday Songbook Generator",
            "producer": "PyMuPDF",
            "page_count": 3,
            "file_size_bytes": None,  # Will be set dynamically in tests
            "has_toc": True,
            "toc_entries": 2,
        },
        "content_info": {
            "total_files": 2,
            "file_names": ["Song 1.pdf", "Song 2.pdf"],
            "source_folders": ["folder1", "folder2"],
        },
        "edition": {
            "id": "current",
            "title": "Test Edition",
            "description": "Test edition for validation",
        },
    }


@pytest.fixture
def matching_pdf_and_manifest(tmp_path, sample_manifest_data):
    """Create a PDF and matching manifest file for testing."""
    pdf_path = tmp_path / "matching.pdf"

    doc = fitz.open()

    # Create 3 pages to match manifest page_count
    cover_page = doc.new_page()
    cover_page.insert_text((100, 100), "Test Songbook", fontsize=20)

    toc_page = doc.new_page()
    toc_page.insert_text((100, 100), "Table of Contents", fontsize=16)
    toc_page.insert_text((100, 150), "1. Song 1 .................. 3", fontsize=12)

    content_page = doc.new_page()
    content_page.insert_text((100, 100), "Song 1", fontsize=16)

    # Set metadata to match manifest
    pdf_info = sample_manifest_data["pdf_info"]
    doc.set_metadata(
        {
            "title": pdf_info["title"],
            "subject": pdf_info["subject"],
            "author": pdf_info["author"],
            "creator": pdf_info["creator"],
            "producer": pdf_info["producer"],
        }
    )

    # Add TOC to match manifest
    toc = [
        [1, "Table of Contents", 2],
        [1, "Song 1", 3],
    ]
    doc.set_toc(toc)

    doc.save(pdf_path)
    doc.close()

    # Update the manifest with the actual file size
    actual_file_size = pdf_path.stat().st_size
    sample_manifest_data["pdf_info"]["file_size_bytes"] = actual_file_size

    # Create manifest file
    manifest_path = tmp_path / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(sample_manifest_data, f, indent=2)

    return pdf_path, manifest_path


@pytest.fixture
def manifest_file(tmp_path, sample_manifest_data):
    """Create a manifest.json file for testing (with None file_size_bytes)."""
    manifest_path = tmp_path / "manifest.json"
    # Remove file_size_bytes for basic manifest testing
    manifest_data = sample_manifest_data.copy()
    manifest_data["pdf_info"] = manifest_data["pdf_info"].copy()
    manifest_data["pdf_info"]["file_size_bytes"] = None
    with open(manifest_path, "w") as f:
        json.dump(manifest_data, f, indent=2)
    return manifest_path


def test_load_manifest_valid(manifest_file):
    """Test loading a valid manifest file."""
    manifest_data = load_manifest(manifest_file)

    assert manifest_data["job_id"] == "test-job-123"
    assert "pdf_info" in manifest_data
    assert "content_info" in manifest_data


def test_load_manifest_nonexistent():
    """Test loading a nonexistent manifest file."""
    from pathlib import Path

    nonexistent = Path("/nonexistent/manifest.json")

    with pytest.raises(PDFValidationError, match="Manifest file does not exist"):
        load_manifest(nonexistent)


def test_load_manifest_invalid_json(tmp_path):
    """Test loading a manifest with invalid JSON."""
    manifest_path = tmp_path / "invalid.json"
    manifest_path.write_text("{ invalid json }")

    with pytest.raises(PDFValidationError, match="Invalid JSON in manifest file"):
        load_manifest(manifest_path)


def test_load_manifest_missing_required_section(tmp_path):
    """Test loading a manifest missing required sections."""
    manifest_path = tmp_path / "incomplete.json"
    with open(manifest_path, "w") as f:
        json.dump({"job_id": "test"}, f)  # Missing pdf_info

    with pytest.raises(
        PDFValidationError, match="Missing required section in manifest: pdf_info"
    ):
        load_manifest(manifest_path)


def test_validate_pdf_with_manifest_success(matching_pdf_and_manifest):
    """Test successful validation with matching PDF and manifest."""
    pdf_path, manifest_path = matching_pdf_and_manifest

    result = validate_pdf_with_manifest(
        pdf_path=pdf_path, manifest_path=manifest_path, verbose=False
    )

    assert result["valid"] is True
    assert result["manifest_validated"] is True
    assert "manifest_path" in result


def test_validate_pdf_against_manifest_page_count_mismatch(
    sample_manifest_data, valid_songbook_pdf
):
    """Test page count mismatch between PDF and manifest."""
    # Modify manifest to expect different page count
    sample_manifest_data["pdf_info"]["page_count"] = 5
    sample_manifest_data["pdf_info"]["file_size_bytes"] = None  # Don't check file size

    with pytest.raises(PDFValidationError, match="Page count mismatch"):
        validate_pdf_against_manifest(valid_songbook_pdf, sample_manifest_data)


def test_validate_pdf_against_manifest_file_size_mismatch(
    sample_manifest_data, valid_songbook_pdf
):
    """Test file size mismatch between PDF and manifest."""
    # Set unrealistic file size in manifest
    sample_manifest_data["pdf_info"]["file_size_bytes"] = (
        1000000  # 1MB, but PDF is much smaller
    )
    sample_manifest_data["pdf_info"]["page_count"] = None  # Don't check page count

    with pytest.raises(PDFValidationError, match="File size mismatch"):
        validate_pdf_against_manifest(valid_songbook_pdf, sample_manifest_data)


def test_validate_pdf_against_manifest_toc_presence_mismatch(
    sample_manifest_data, pdf_too_few_pages
):
    """Test TOC presence mismatch between PDF and manifest."""
    sample_manifest_data["pdf_info"]["has_toc"] = (
        True  # Expect TOC but pdf_too_few_pages has none
    )
    sample_manifest_data["pdf_info"]["page_count"] = (
        None  # Don't check page count (will fail first)
    )
    sample_manifest_data["pdf_info"]["file_size_bytes"] = None  # Don't check file size

    with pytest.raises(PDFValidationError, match="TOC presence mismatch"):
        validate_pdf_against_manifest(pdf_too_few_pages, sample_manifest_data)


def test_validate_pdf_against_manifest_metadata_mismatch(
    sample_manifest_data, valid_songbook_pdf
):
    """Test metadata mismatch between PDF and manifest."""
    sample_manifest_data["pdf_info"]["title"] = "Wrong Title"
    sample_manifest_data["pdf_info"]["page_count"] = None  # Don't check page count
    sample_manifest_data["pdf_info"]["file_size_bytes"] = None  # Don't check file size
    sample_manifest_data["pdf_info"]["has_toc"] = None  # Don't check TOC presence
    sample_manifest_data["pdf_info"]["toc_entries"] = None  # Don't check TOC entries

    with pytest.raises(PDFValidationError, match="Metadata field 'title' mismatch"):
        validate_pdf_against_manifest(valid_songbook_pdf, sample_manifest_data)


def test_validate_content_info_file_count_mismatch():
    """Test content info validation with file count mismatch."""
    manifest_data = {
        "content_info": {
            "total_files": 3,
            "file_names": [
                "file1.pdf",
                "file2.pdf",
            ],  # Only 2 files but total_files says 3
        }
    }

    with pytest.raises(PDFValidationError, match="Content info mismatch"):
        validate_content_info(manifest_data)


def test_validate_content_info_suspicious_duration():
    """Test content info validation with suspicious generation duration."""
    manifest_data = {
        "content_info": {"total_files": 1, "file_names": ["test.pdf"]},
        "generation_info": {"duration_seconds": 7200},  # 2 hours - too long
    }

    with pytest.raises(PDFValidationError, match="Suspicious generation duration"):
        validate_content_info(manifest_data)


def test_validate_content_info_success():
    """Test successful content info validation."""
    manifest_data = {
        "content_info": {
            "total_files": 2,
            "file_names": ["file1.pdf", "file2.pdf"],
        },
        "generation_info": {"duration_seconds": 300.0},
    }

    # Should not raise any exception
    validate_content_info(manifest_data, verbose=True)


def test_cli_with_manifest_success(matching_pdf_and_manifest):
    """Test CLI with manifest option - successful validation."""
    pdf_path, manifest_path = matching_pdf_and_manifest

    runner = CliRunner()
    result = runner.invoke(
        validate_pdf_cli, [str(pdf_path), "--manifest", str(manifest_path), "--verbose"]
    )

    assert result.exit_code == 0
    assert "✅ PDF validation passed" in result.output
    assert "Cross-validating PDF against manifest data" in result.output


def test_cli_with_manifest_failure(valid_songbook_pdf, tmp_path, sample_manifest_data):
    """Test CLI with manifest option - validation failure."""
    # Create manifest with mismatched data
    sample_manifest_data["pdf_info"]["title"] = "Wrong Title"
    sample_manifest_data["pdf_info"]["page_count"] = None  # Don't check page count
    sample_manifest_data["pdf_info"]["file_size_bytes"] = None  # Don't check file size

    manifest_path = tmp_path / "bad_manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(sample_manifest_data, f)

    runner = CliRunner()
    result = runner.invoke(
        validate_pdf_cli, [str(valid_songbook_pdf), "--manifest", str(manifest_path)]
    )

    assert result.exit_code == 1
    assert "❌ PDF validation failed" in result.output
