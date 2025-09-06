import fitz
import pytest
from datetime import datetime, timezone
from ..common.config import Edition
from .pdf import (
    collect_and_sort_files,
    generate_songbook,
    generate_songbook_from_edition,
    generate_manifest,
)
from ..common.filters import PropertyFilter, FilterOperator, FilterGroup
from .models import File
from ..common.gdrive import GoogleDriveClient


@pytest.fixture
def mock_gdrive_client(mocker):
    """Fixture to mock GoogleDriveClient."""
    mock_client = mocker.Mock(spec=GoogleDriveClient)
    return mock_client


@pytest.fixture
def mock_generate_songbook(mocker):
    return mocker.patch("generator.worker.pdf.generate_songbook")


def test_generate_songbook_from_edition_simple(mock_generate_songbook, mocker):
    """Test generating a songbook from an edition with a single filter."""
    mock_drive = mocker.Mock()
    mock_cache = mocker.Mock()
    edition = Edition(
        id="test-edition",
        title="Test Edition",
        description="A test edition",
        filters=[
            PropertyFilter(
                key="specialbooks", operator=FilterOperator.CONTAINS, value="test"
            )
        ],
    )

    generate_songbook_from_edition(
        drive=mock_drive,
        cache=mock_cache,
        source_folders=["folder1"],
        destination_path="out.pdf",
        edition=edition,
        limit=10,
    )

    mock_generate_songbook.assert_called_once()
    call_args = mock_generate_songbook.call_args[1]
    assert call_args["drive"] == mock_drive
    assert call_args["client_filter"] == edition.filters[0]
    assert call_args["limit"] == 10
    assert call_args["title"] == "Test Edition"
    assert call_args["subject"] == "A test edition"


def test_generate_songbook_from_edition_composite_filter(
    mock_generate_songbook, mocker
):
    """Test an edition with multiple filters gets combined into a FilterGroup."""
    mock_drive = mocker.Mock()
    mock_cache = mocker.Mock()
    edition = Edition(
        id="composite-edition",
        title="Composite Edition",
        description="A test edition",
        filters=[
            PropertyFilter(
                key="status", operator=FilterOperator.EQUALS, value="APPROVED"
            ),
            PropertyFilter(
                key="year", operator=FilterOperator.GREATER_EQUAL, value=2000
            ),
        ],
        cover_file_id="cover123",
        preface_file_ids=["preface123"],
        table_of_contents={"include_difficulty": False},
    )

    generate_songbook_from_edition(
        drive=mock_drive,
        cache=mock_cache,
        source_folders=[],
        destination_path="out.pdf",
        edition=edition,
        limit=None,
    )

    mock_generate_songbook.assert_called_once()
    call_args = mock_generate_songbook.call_args[1]

    # Check that a FilterGroup was created
    client_filter = call_args["client_filter"]
    assert isinstance(client_filter, FilterGroup)
    assert client_filter.operator == "AND"
    assert len(client_filter.filters) == 2

    # Check other parameters are passed through
    assert call_args["cover_file_id"] == "cover123"
    assert call_args["preface_file_ids"] == ["preface123"]
    assert call_args["title"] == "Composite Edition"
    assert call_args["subject"] == "A test edition"
    assert call_args["edition_toc_config"] is not None
    assert call_args["edition_toc_config"].include_difficulty is False


def test_generate_songbook_sets_metadata(mocker, tmp_path):
    """Verify that PDF metadata is correctly set in the generated songbook."""
    mock_drive = mocker.Mock()
    mock_cache = mocker.Mock()
    destination_path = tmp_path / "songbook.pdf"

    # Mock dependencies to isolate metadata setting
    mocker.patch(
        "generator.worker.pdf.collect_and_sort_files",
        return_value=[File(name="Test Song.pdf", id="123")],
    )
    mocker.patch(
        "generator.common.gdrive.GoogleDriveClient.get_files_metadata_by_ids",
        return_value=[],
    )
    mocker.patch("generator.worker.pdf.get_credentials")
    mocker.patch(
        "generator.worker.cover.CoverGenerator.generate_cover", return_value=fitz.open()
    )
    mocker.patch(
        "generator.worker.toc.build_table_of_contents",
        side_effect=lambda files, page_offset, edition_toc_config=None: (
            fitz.open().new_page().parent,
            [],
        ),
    )
    mocker.patch("generator.worker.pdf.copy_pdfs")
    mocker.patch("generator.worker.toc.add_toc_links_to_merged_pdf")

    generate_songbook(
        drive=mock_drive,
        cache=mock_cache,
        source_folders=["folder1"],
        destination_path=destination_path,
        limit=1,
        cover_file_id="cover123",
        title="My Test Songbook",
        subject="A collection of test songs.",
    )

    # Verify the generated PDF's metadata
    with fitz.open(destination_path) as doc:
        metadata = doc.metadata
        assert metadata["title"] == "My Test Songbook"
        assert metadata["subject"] == "A collection of test songs."
        assert metadata["author"] == "Ukulele Tuesday"
        assert metadata["producer"] == "PyMuPDF"
        assert metadata["creator"] == "Ukulele Tuesday Songbook Generator"


def test_collect_and_sort_files_single_folder(mocker, mock_gdrive_client):
    """Test that files from a single folder are returned sorted by name."""
    # Mock files in non-alphabetical order
    mock_files = [
        File(name="zebra.pdf", id="3"),
        File(name="apple.pdf", id="1"),
        File(name="banana.pdf", id="2"),
    ]

    mock_gdrive_client.query_drive_files_with_client_filter.return_value = mock_files

    result = collect_and_sort_files(
        gdrive_client=mock_gdrive_client,
        source_folders=["folder1"],
    )

    # Should be sorted alphabetically by name
    expected = [
        File(name="apple.pdf", id="1"),
        File(name="banana.pdf", id="2"),
        File(name="zebra.pdf", id="3"),
    ]
    assert result == expected

    # Verify the query was called correctly
    mock_gdrive_client.query_drive_files_with_client_filter.assert_called_once_with(
        ["folder1"], None
    )


def test_collect_and_sort_files_multiple_folders(mocker, mock_gdrive_client):
    """Test that files from multiple folders are aggregated and sorted."""
    # Mock files from different folders
    folder1_files = [
        File(name="zebra.pdf", id="1"),
        File(name="banana.pdf", id="2"),
    ]
    folder2_files = [
        File(name="apple.pdf", id="3"),
        File(name="cherry.pdf", id="4"),
    ]

    all_files = folder1_files + folder2_files
    mock_gdrive_client.query_drive_files_with_client_filter.return_value = all_files

    result = collect_and_sort_files(
        gdrive_client=mock_gdrive_client,
        source_folders=["folder1", "folder2"],
    )

    # Should be sorted alphabetically across all folders
    expected = [
        File(name="apple.pdf", id="3"),
        File(name="banana.pdf", id="2"),
        File(name="cherry.pdf", id="4"),
        File(name="zebra.pdf", id="1"),
    ]
    assert result == expected

    # Verify query was called once with both folders
    mock_gdrive_client.query_drive_files_with_client_filter.assert_called_once_with(
        ["folder1", "folder2"], None
    )


def test_collect_and_sort_files_with_client_filter(mocker, mock_gdrive_client):
    """Test that client filter is passed through correctly."""
    mock_filter = PropertyFilter(
        key="artist", operator=FilterOperator.EQUALS, value="Test Artist"
    )

    mock_files = [File(name="test.pdf", id="1")]

    mock_gdrive_client.query_drive_files_with_client_filter.return_value = mock_files

    result = collect_and_sort_files(
        gdrive_client=mock_gdrive_client,
        source_folders=["folder1"],
        client_filter=mock_filter,
    )

    assert result == mock_files
    mock_gdrive_client.query_drive_files_with_client_filter.assert_called_once_with(
        ["folder1"], mock_filter
    )


def test_collect_and_sort_files_empty_folders(mocker, mock_gdrive_client):
    """Test that empty folders return an empty list."""
    mock_gdrive_client.query_drive_files_with_client_filter.return_value = []

    result = collect_and_sort_files(
        gdrive_client=mock_gdrive_client,
        source_folders=["empty_folder"],
    )

    assert result == []


def test_collect_and_sort_files_with_progress_step(mocker, mock_gdrive_client):
    """Test that progress is reported correctly when progress_step is provided."""
    mock_progress_step = mocker.Mock()

    folder1_files = [File(name="file1.pdf", id="1")]
    folder2_files = [File(name="file2.pdf", id="2")]

    mock_gdrive_client.query_drive_files_with_client_filter.return_value = (
        folder1_files + folder2_files
    )

    result = collect_and_sort_files(
        gdrive_client=mock_gdrive_client,
        source_folders=["folder1", "folder2"],
        progress_step=mock_progress_step,
    )

    # Verify progress was reported once
    mock_progress_step.increment.assert_called_once_with(
        1.0, "Found 2 files in 2 folder(s)"
    )

    # Verify files are still sorted correctly
    expected = [
        File(name="file1.pdf", id="1"),
        File(name="file2.pdf", id="2"),
    ]
    assert result == expected


def test_collect_and_sort_files_no_progress_step(mocker, mock_gdrive_client):
    """Test that no progress reporting occurs when progress_step is None."""
    mock_files = [File(name="test.pdf", id="1")]

    mock_gdrive_client.query_drive_files_with_client_filter.return_value = mock_files

    # Should not raise any errors when progress_step is None
    result = collect_and_sort_files(
        gdrive_client=mock_gdrive_client,
        source_folders=["folder1"],
        progress_step=None,
    )

    assert result == mock_files


def test_collect_and_sort_files_strips_artist_name(mocker, mock_gdrive_client):
    """Test that sorting handles different cases correctly."""
    mock_files = [
        File(name="ab - a.pdf", id="1"),
        File(name="a - cd.pdf", id="2"),
    ]

    mock_gdrive_client.query_drive_files_with_client_filter.return_value = mock_files

    result = collect_and_sort_files(
        gdrive_client=mock_gdrive_client,
        source_folders=["folder1"],
    )

    expected = [
        File(name="a - cd.pdf", id="2"),
        File(name="ab - a.pdf", id="1"),
    ]
    assert result == expected


def test_collect_and_sort_files_case_sensitive_sorting(mocker, mock_gdrive_client):
    """Test that sorting handles different cases correctly."""
    mock_files = [
        File(name="Zebra.pdf", id="1"),
        File(name="apple.pdf", id="2"),
        File(name="Banana.pdf", id="3"),
    ]

    mock_gdrive_client.query_drive_files_with_client_filter.return_value = mock_files

    result = collect_and_sort_files(
        gdrive_client=mock_gdrive_client,
        source_folders=["folder1"],
    )

    expected = [
        File(name="apple.pdf", id="2"),
        File(name="Banana.pdf", id="3"),
        File(name="Zebra.pdf", id="1"),
    ]
    assert result == expected


def test_collect_and_sort_files_strips_punctuation(mocker, mock_gdrive_client):
    mock_files = [
        File(name="!!banana.pdf", id="1"),
        File(name="apple", id="2"),
        File(name="cucumber.pdf", id="3"),
    ]

    mock_gdrive_client.query_drive_files_with_client_filter.return_value = mock_files

    result = collect_and_sort_files(
        gdrive_client=mock_gdrive_client,
        source_folders=["folder1"],
    )

    expected = [
        File(name="apple", id="2"),
        File(name="!!banana.pdf", id="1"),
        File(name="cucumber.pdf", id="3"),
    ]
    assert result == expected


def test_collect_and_sort_files_accent_sensitive_sorting(mocker, mock_gdrive_client):
    mock_files = [
        File(name="çb.pdf", id="1"),
        File(name="ca", id="2"),
        File(name="cz.pdf", id="3"),
    ]

    mock_gdrive_client.query_drive_files_with_client_filter.return_value = mock_files

    result = collect_and_sort_files(
        gdrive_client=mock_gdrive_client,
        source_folders=["folder1"],
    )

    expected = [
        File(name="ca", id="2"),
        File(name="çb.pdf", id="1"),
        File(name="cz.pdf", id="3"),
    ]
    assert result == expected


def test_collect_and_sort_files_numeral_sensitive_sorting(mocker, mock_gdrive_client):
    mock_files = [
        File(name="01 things.pdf", id="1"),
        File(name="things 100 things", id="2"),
        File(name="things 001 things.pdf", id="3"),
    ]

    mock_gdrive_client.query_drive_files_with_client_filter.return_value = mock_files

    result = collect_and_sort_files(
        gdrive_client=mock_gdrive_client,
        source_folders=["folder1"],
    )
    expected = [
        File(name="01 things.pdf", id="1"),
        File(name="things 001 things.pdf", id="3"),
        File(name="things 100 things", id="2"),
    ]
    assert result == expected


def test_collect_and_sort_files_progress_increment_calculation(
    mocker, mock_gdrive_client
):
    """Test that progress increments are calculated correctly for different folder counts."""
    mock_progress_step = mocker.Mock()

    # Test with 3 folders
    folder_files = [File(name="file.pdf", id="1")]

    mock_gdrive_client.query_drive_files_with_client_filter.return_value = folder_files

    collect_and_sort_files(
        gdrive_client=mock_gdrive_client,
        source_folders=["folder1", "folder2", "folder3"],
        progress_step=mock_progress_step,
    )

    # Progress should be reported once for the entire operation
    mock_progress_step.increment.assert_called_once_with(
        1.0, "Found 1 files in 3 folder(s)"
    )


def test_collect_and_sort_files_mixed_empty_and_non_empty_folders(
    mocker, mock_gdrive_client
):
    """Test handling of mixed empty and non-empty folders."""

    mock_gdrive_client.query_drive_files_with_client_filter.return_value = [
        File(name="file2.pdf", id="2"),
        File(name="file1.pdf", id="1"),
    ]

    result = collect_and_sort_files(
        gdrive_client=mock_gdrive_client,
        source_folders=["folder1", "folder2", "folder3"],
    )

    # Should only return files from non-empty folders, sorted
    expected = [
        File(name="file1.pdf", id="1"),
        File(name="file2.pdf", id="2"),
    ]
    assert result == expected

    # Should have queried all folders once
    mock_gdrive_client.query_drive_files_with_client_filter.assert_called_once_with(
        ["folder1", "folder2", "folder3"], None
    )


def test_generate_manifest(tmp_path):
    """Test that generate_manifest creates comprehensive metadata."""
    # Create a temporary PDF for testing
    pdf_path = tmp_path / "test.pdf"
    doc = fitz.open()  # Create empty PDF
    doc.new_page()
    doc.new_page()  # 2 pages
    doc.save(pdf_path)
    doc.close()

    # Create test data
    job_id = "test-job-123"
    params = {
        "edition": "current",
        "limit": 10,
        "force": False,
    }
    files = [
        File(name="Song 1.pdf", id="file1"),
        File(name="Song 2.pdf", id="file2"),
    ]
    edition = Edition(
        id="current",
        title="Test Edition",
        description="A test edition",
        cover_file_id="cover123",
        filters=[
            PropertyFilter(
                key="status", operator=FilterOperator.EQUALS, value="APPROVED"
            )
        ],
    )
    title = "Test Songbook"
    subject = "Test Subject"
    source_folders = ["folder1", "folder2"]
    start_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    end_time = datetime(2024, 1, 1, 12, 5, 0, tzinfo=timezone.utc)

    # Generate manifest
    manifest = generate_manifest(
        job_id=job_id,
        params=params,
        destination_path=pdf_path,
        files=files,
        edition=edition,
        title=title,
        subject=subject,
        source_folders=source_folders,
        generation_start_time=start_time,
        generation_end_time=end_time,
    )

    # Verify manifest structure and content
    assert manifest["job_id"] == job_id
    assert "generated_at" in manifest

    # Verify generation info
    gen_info = manifest["generation_info"]
    assert gen_info["start_time"] == start_time.isoformat()
    assert gen_info["end_time"] == end_time.isoformat()
    assert gen_info["duration_seconds"] == 300.0  # 5 minutes

    # Verify input parameters
    assert manifest["input_parameters"] == params

    # Verify PDF info
    pdf_info = manifest["pdf_info"]
    assert pdf_info["title"] == title
    assert pdf_info["subject"] == subject
    assert pdf_info["author"] == "Ukulele Tuesday"
    assert pdf_info["creator"] == "Ukulele Tuesday Songbook Generator"
    assert pdf_info["producer"] == "PyMuPDF"
    assert pdf_info["page_count"] == 2
    assert pdf_info["file_size_bytes"] > 0
    assert pdf_info["has_toc"] is False
    assert pdf_info["toc_entries"] == 0

    # Verify content info
    content_info = manifest["content_info"]
    assert content_info["total_files"] == 2
    assert content_info["file_names"] == ["Song 1.pdf", "Song 2.pdf"]
    assert content_info["source_folders"] == source_folders

    # Verify edition info
    edition_info = manifest["edition"]
    assert edition_info["id"] == "current"
    assert edition_info["title"] == "Test Edition"
    assert edition_info["description"] == "A test edition"
    assert edition_info["cover_file_id"] == "cover123"
    assert len(edition_info["filters"]) == 1
    assert edition_info["filters"][0]["key"] == "status"


def test_generate_manifest_without_edition(tmp_path):
    """Test that generate_manifest works without an edition (legacy mode)."""
    # Create a temporary PDF for testing
    pdf_path = tmp_path / "test.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(pdf_path)
    doc.close()

    # Create minimal test data
    job_id = "test-job-456"
    params = {"limit": 5}
    files = [File(name="Song.pdf", id="file1")]

    manifest = generate_manifest(
        job_id=job_id,
        params=params,
        destination_path=pdf_path,
        files=files,
    )

    # Verify basic structure
    assert manifest["job_id"] == job_id
    assert manifest["input_parameters"] == params
    assert manifest["content_info"]["total_files"] == 1
    assert manifest["pdf_info"]["page_count"] == 1

    # Edition should not be present in legacy mode
    assert "edition" not in manifest


def test_generate_manifest_with_page_indices(tmp_path):
    """Test that generate_manifest includes page indices when provided."""
    # Create a temporary PDF for testing
    pdf_path = tmp_path / "test.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.new_page()
    doc.new_page()
    doc.save(pdf_path)
    doc.close()

    # Create test data with page indices
    job_id = "test-job-789"
    params = {"edition": "complete"}
    files = [File(name="Song.pdf", id="file1")]
    page_indices = {
        "cover": {"first_page": 1, "last_page": 1},
        "preface": None,
        "table_of_contents": {"first_page": 2, "last_page": 2},
        "body": {"first_page": 3, "last_page": 3},
        "postface": None,
    }

    manifest = generate_manifest(
        job_id=job_id,
        params=params,
        destination_path=pdf_path,
        files=files,
        page_indices=page_indices,
    )

    # Verify basic structure
    assert manifest["job_id"] == job_id
    assert manifest["content_info"]["total_files"] == 1
    assert manifest["pdf_info"]["page_count"] == 3

    # Verify page indices are included correctly
    assert "page_indices" in manifest
    assert manifest["page_indices"] == page_indices
    assert manifest["page_indices"]["cover"]["first_page"] == 1
    assert manifest["page_indices"]["cover"]["last_page"] == 1
    assert manifest["page_indices"]["preface"] is None
    assert manifest["page_indices"]["table_of_contents"]["first_page"] == 2
    assert manifest["page_indices"]["table_of_contents"]["last_page"] == 2
    assert manifest["page_indices"]["body"]["first_page"] == 3
    assert manifest["page_indices"]["body"]["last_page"] == 3
    assert manifest["page_indices"]["postface"] is None


def test_generate_manifest_without_page_indices(tmp_path):
    """Test that generate_manifest works without page indices."""
    # Create a temporary PDF for testing
    pdf_path = tmp_path / "test.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(pdf_path)
    doc.close()

    # Create test data without page indices
    job_id = "test-job-000"
    params = {"edition": "minimal"}
    files = [File(name="Song.pdf", id="file1")]

    manifest = generate_manifest(
        job_id=job_id,
        params=params,
        destination_path=pdf_path,
        files=files,
        page_indices=None,
    )

    # Verify basic structure
    assert manifest["job_id"] == job_id
    assert manifest["content_info"]["total_files"] == 1
    assert manifest["pdf_info"]["page_count"] == 1

    # Verify page indices are not included when not provided
    assert "page_indices" not in manifest
