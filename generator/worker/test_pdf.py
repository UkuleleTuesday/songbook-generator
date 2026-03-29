import fitz
import pytest
from datetime import datetime, timezone
from pathlib import Path
from ..common.config import Edition
from .pdf import (
    _resolve_songs_from_folder,
    add_page_number,
    categorize_folder_files,
    collect_and_sort_files,
    copy_pdfs,
    generate_songbook,
    generate_songbook_from_drive_folder,
    generate_songbook_from_edition,
    generate_manifest,
    load_edition_from_drive_folder,
    resolve_folder_components,
)
from .exceptions import PdfCacheMissException, PdfCacheNotFound
from ..common.filters import PropertyFilter, FilterOperator, FilterGroup
from .models import File

TEST_DATA_DIR = Path(__file__).parent / "test_data"


@pytest.fixture
def mock_gdrive_client(mocker):
    """Fixture to mock GoogleDriveClient."""
    mock_client = mocker.Mock()
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


def test_add_page_number_inserts_text():
    """Test that add_page_number inserts text on the page."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)

    add_page_number(page, 42)

    # Verify the page number text was inserted
    text = page.get_text()
    assert "42" in text


def test_add_page_number_position_within_page():
    """Test that the page number is positioned within page bounds."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)

    add_page_number(page, 1)

    # Inspect the text block bounding box to confirm it stays within the page
    blocks = page.get_text("dict")["blocks"]
    assert len(blocks) > 0
    for block in blocks:
        # Block rect should be within page dimensions
        assert block["bbox"][0] >= 0
        assert block["bbox"][2] <= page.rect.width
        assert block["bbox"][1] >= 0
        assert block["bbox"][3] <= page.rect.height


def test_add_page_number_no_overlap_with_running_headers():
    """Integration test: page numbers stay within bounds on real song sheets.

    The fixture includes pages with long titles that extend close to the right
    margin, previously identified as potential overlap candidates:
      - "Jolene - Dolly Parton"
      - "Valerie (feat. Amy Winehouse) (Version Revisited) - Mark Ronson"
      - "You're The One That I Want - John Travolta, Olivia Newton-John"
    """
    fixture_path = TEST_DATA_DIR / "sample_songbook.pdf"
    assert fixture_path.exists(), f"Test fixture not found: {fixture_path}"
    doc = fitz.open(str(fixture_path))

    for i, page in enumerate(doc):
        add_page_number(page, i + 1)

    for i, page in enumerate(doc):
        expected_num = str(i + 1)

        # Page number text must be present
        assert expected_num in page.get_text(), (
            f"Page number {expected_num} not found on page {i + 1}"
        )

        # Locate the page number text block and verify it stays within bounds
        num_blocks = [
            b
            for b in page.get_text("dict")["blocks"]
            if b["type"] == 0
            and "".join(
                s.get("text", "")
                for line in b.get("lines", [])
                for s in line.get("spans", [])
            ).strip()
            == expected_num
        ]
        assert len(num_blocks) == 1, (
            f"Expected exactly 1 page number block on page {i + 1}, "
            f"got {len(num_blocks)}"
        )
        x1, y1, x2, y2 = num_blocks[0]["bbox"]
        assert x1 >= 0
        assert x2 <= page.rect.width
        assert y1 >= 0
        assert y2 <= page.rect.height

    doc.close()


# ---------------------------------------------------------------------------
# categorize_folder_files tests
# ---------------------------------------------------------------------------


def _make_file(name, file_id=None):
    return File(name=name, id=file_id or name)


def test_categorize_cover_identified():
    files = [_make_file("_cover.gdoc"), _make_file("Song A.pdf")]
    result = categorize_folder_files(files)
    assert result["cover"] is not None
    assert result["cover"].name == "_cover.gdoc"
    assert len(result["songs"]) == 1


def test_categorize_cover_case_insensitive():
    files = [_make_file("_Cover - My Edition.gdoc"), _make_file("Song A.pdf")]
    result = categorize_folder_files(files)
    assert result["cover"] is not None


def test_categorize_preface_identified():
    files = [
        _make_file("_preface1 - Welcome.gdoc"),
        _make_file("_preface2 - Rules.gdoc"),
        _make_file("Song A.pdf"),
    ]
    result = categorize_folder_files(files)
    assert len(result["preface"]) == 2
    assert len(result["songs"]) == 1


def test_categorize_postface_identified():
    files = [
        _make_file("Song A.pdf"),
        _make_file("_postface - Thanks.gdoc"),
    ]
    result = categorize_folder_files(files)
    assert len(result["postface"]) == 1
    assert len(result["songs"]) == 1


def test_categorize_songs_sorted_by_title():
    files = [
        _make_file("Zebra Song - Artist Z.pdf"),
        _make_file("Apple Song - Artist A.pdf"),
        _make_file("Mango Song - Artist M.pdf"),
    ]
    result = categorize_folder_files(files)
    names = [f.name for f in result["songs"]]
    assert names == [
        "Apple Song - Artist A.pdf",
        "Mango Song - Artist M.pdf",
        "Zebra Song - Artist Z.pdf",
    ]


def test_categorize_cover_first_alphabetically_used():
    """When multiple _cover files exist, the first alphabetically is chosen."""
    files = [
        _make_file("_cover-b.gdoc"),
        _make_file("_cover-a.gdoc"),
    ]
    result = categorize_folder_files(files)
    assert result["cover"].name == "_cover-a.gdoc"


def test_categorize_all_categories():
    files = [
        _make_file("_cover.gdoc"),
        _make_file("_preface - Intro.gdoc"),
        _make_file("_postface - Goodbye.gdoc"),
        _make_file("Song A.pdf"),
        _make_file("Song B.pdf"),
    ]
    result = categorize_folder_files(files)
    assert result["cover"].name == "_cover.gdoc"
    assert len(result["preface"]) == 1
    assert len(result["songs"]) == 2
    assert len(result["postface"]) == 1


def test_categorize_empty_list():
    result = categorize_folder_files([])
    assert result["cover"] is None
    assert result["preface"] == []
    assert result["songs"] == []
    assert result["postface"] == []


# ---------------------------------------------------------------------------
# generate_songbook_from_drive_folder tests
# ---------------------------------------------------------------------------


def test_generate_from_drive_folder_basic(mocker):
    """generate_songbook is called with categorised files from the folder."""
    mock_drive = mocker.Mock()
    mock_cache = mocker.Mock()

    folder_files = [
        File(
            id="cover_id",
            name="_cover.gdoc",
            mimeType="application/vnd.google-apps.document",
        ),
        File(
            id="preface_id",
            name="_preface.gdoc",
            mimeType="application/vnd.google-apps.document",
        ),
        File(id="song1_id", name="Song A.pdf", mimeType="application/pdf"),
        File(id="song2_id", name="Song B.pdf", mimeType="application/pdf"),
        File(
            id="postface_id",
            name="_postface.gdoc",
            mimeType="application/vnd.google-apps.document",
        ),
    ]

    mocker.patch(
        "generator.common.gdrive.GoogleDriveClient.list_folder_contents",
        return_value=folder_files,
    )
    mock_gen = mocker.patch("generator.worker.pdf.generate_songbook")

    generate_songbook_from_drive_folder(
        drive=mock_drive,
        cache=mock_cache,
        folder_id="folder123",
        destination_path=Path("out/test.pdf"),
        title="Test Songbook",
    )

    mock_gen.assert_called_once()
    kwargs = mock_gen.call_args[1]
    assert kwargs["cover_file_id"] == "cover_id"
    assert kwargs["preface_file_ids"] == ["preface_id"]
    assert kwargs["postface_file_ids"] == ["postface_id"]
    assert len(kwargs["files"]) == 2
    assert kwargs["files"][0].id == "song1_id"
    assert kwargs["title"] == "Test Songbook"
    assert kwargs["limit"] is None


def test_generate_from_drive_folder_no_songs_returns_none(mocker):
    """Returns None when the folder contains no song files."""
    mock_drive = mocker.Mock()
    mock_cache = mocker.Mock()

    mocker.patch(
        "generator.common.gdrive.GoogleDriveClient.list_folder_contents",
        return_value=[
            File(id="c", name="_cover.gdoc"),
        ],
    )
    mock_gen = mocker.patch("generator.worker.pdf.generate_songbook")

    result = generate_songbook_from_drive_folder(
        drive=mock_drive,
        cache=mock_cache,
        folder_id="folder123",
        destination_path=Path("out/test.pdf"),
    )

    assert result is None
    mock_gen.assert_not_called()


def test_generate_from_drive_folder_limit_applied(mocker):
    """The limit parameter caps the number of song files passed to generate_songbook."""
    mock_drive = mocker.Mock()
    mock_cache = mocker.Mock()

    folder_files = [File(id=f"s{i}", name=f"Song {i}.pdf") for i in range(5)]

    mocker.patch(
        "generator.common.gdrive.GoogleDriveClient.list_folder_contents",
        return_value=folder_files,
    )
    mock_gen = mocker.patch("generator.worker.pdf.generate_songbook")

    generate_songbook_from_drive_folder(
        drive=mock_drive,
        cache=mock_cache,
        folder_id="folder123",
        destination_path=Path("out/test.pdf"),
        limit=2,
    )

    mock_gen.assert_called_once()
    assert len(mock_gen.call_args[1]["files"]) == 2


def test_generate_from_drive_folder_no_cover_or_preface(mocker):
    """Folder with only songs (no cover/preface/postface) works correctly."""
    mock_drive = mocker.Mock()
    mock_cache = mocker.Mock()

    folder_files = [
        File(id="s1", name="Song A.pdf"),
        File(id="s2", name="Song B.pdf"),
    ]

    mocker.patch(
        "generator.common.gdrive.GoogleDriveClient.list_folder_contents",
        return_value=folder_files,
    )
    mock_gen = mocker.patch("generator.worker.pdf.generate_songbook")

    generate_songbook_from_drive_folder(
        drive=mock_drive,
        cache=mock_cache,
        folder_id="folder123",
        destination_path=Path("out/test.pdf"),
    )

    mock_gen.assert_called_once()
    kwargs = mock_gen.call_args[1]
    assert kwargs["cover_file_id"] is None
    assert kwargs["preface_file_ids"] is None
    assert kwargs["postface_file_ids"] is None
    assert len(kwargs["files"]) == 2


# ---------------------------------------------------------------------------
# resolve_folder_components tests
# ---------------------------------------------------------------------------


def _make_edition_with_folder_components(**kwargs):
    """Helper: build a minimal Edition with use_folder_components=True."""
    defaults = dict(
        id="test",
        title="Test",
        description="Test",
        use_folder_components=True,
        filters=[
            PropertyFilter(
                key="status", operator=FilterOperator.EQUALS, value="APPROVED"
            )
        ],
    )
    defaults.update(kwargs)
    return Edition(**defaults)


def test_resolve_folder_components_disabled_returns_edition_unchanged(mocker):
    """When use_folder_components is False the edition is returned as-is."""
    mock_gdrive = mocker.Mock()
    edition = Edition(
        id="test",
        title="Test",
        description="Test",
        use_folder_components=False,
        filters=[],
    )
    result = resolve_folder_components(mock_gdrive, "folder_id", edition)
    assert result is edition
    mock_gdrive.find_subfolder_by_name.assert_not_called()


def test_resolve_folder_components_cover_from_subfolder(mocker):
    """Cover file is resolved from the Cover subfolder when not in YAML."""
    mock_gdrive = mocker.Mock()
    mock_gdrive.find_subfolder_by_name.side_effect = lambda fid, name: (
        "cover_subfolder" if name.lower() == "cover" else None
    )
    mock_gdrive.list_folder_contents.return_value = [
        File(id="cover_file_id", name="My Cover.gdoc"),
    ]
    edition = _make_edition_with_folder_components()

    result = resolve_folder_components(mock_gdrive, "folder_id", edition)

    assert result.cover_file_id == "cover_file_id"
    assert result.preface_file_ids is None
    assert result.postface_file_ids is None
    # Original edition not mutated
    assert edition.cover_file_id is None


def test_resolve_folder_components_preface_from_subfolder(mocker):
    """Preface files are resolved from the Preface subfolder when not in YAML."""
    mock_gdrive = mocker.Mock()
    mock_gdrive.find_subfolder_by_name.side_effect = lambda fid, name: (
        "preface_subfolder" if name.lower() == "preface" else None
    )
    mock_gdrive.list_folder_contents.return_value = [
        File(id="preface_1", name="Welcome.gdoc"),
        File(id="preface_2", name="About.gdoc"),
    ]
    edition = _make_edition_with_folder_components()

    result = resolve_folder_components(mock_gdrive, "folder_id", edition)

    assert result.preface_file_ids == ["preface_1", "preface_2"]
    assert result.cover_file_id is None
    assert result.postface_file_ids is None


def test_resolve_folder_components_postface_from_subfolder(mocker):
    """Postface files are resolved from the Postface subfolder when not in YAML."""
    mock_gdrive = mocker.Mock()
    mock_gdrive.find_subfolder_by_name.side_effect = lambda fid, name: (
        "postface_subfolder" if name.lower() == "postface" else None
    )
    mock_gdrive.list_folder_contents.return_value = [
        File(id="postface_1", name="Credits.gdoc"),
    ]
    edition = _make_edition_with_folder_components()

    result = resolve_folder_components(mock_gdrive, "folder_id", edition)

    assert result.postface_file_ids == ["postface_1"]
    assert result.cover_file_id is None
    assert result.preface_file_ids is None


def test_resolve_folder_components_yaml_cover_takes_precedence(mocker):
    """Explicit YAML cover_file_id overrides any subfolder detection."""
    mock_gdrive = mocker.Mock()
    mock_gdrive.find_subfolder_by_name.return_value = "cover_subfolder"
    mock_gdrive.list_folder_contents.return_value = [
        File(id="subfolder_cover", name="Different Cover.gdoc"),
    ]
    edition = _make_edition_with_folder_components(cover_file_id="yaml_cover_id")

    result = resolve_folder_components(mock_gdrive, "folder_id", edition)

    assert result.cover_file_id == "yaml_cover_id"
    # find_subfolder_by_name should NOT be called for cover because YAML has it
    calls = [
        c.args[1].lower() for c in mock_gdrive.find_subfolder_by_name.call_args_list
    ]
    assert "cover" not in calls


def test_resolve_folder_components_yaml_preface_takes_precedence(mocker):
    """Explicit YAML preface_file_ids overrides subfolder detection."""
    mock_gdrive = mocker.Mock()
    mock_gdrive.find_subfolder_by_name.return_value = "preface_subfolder"
    mock_gdrive.list_folder_contents.return_value = [
        File(id="subfolder_preface", name="Intro.gdoc"),
    ]
    edition = _make_edition_with_folder_components(preface_file_ids=["yaml_preface_id"])

    result = resolve_folder_components(mock_gdrive, "folder_id", edition)

    assert result.preface_file_ids == ["yaml_preface_id"]
    calls = [
        c.args[1].lower() for c in mock_gdrive.find_subfolder_by_name.call_args_list
    ]
    assert "preface" not in calls


def test_resolve_folder_components_empty_subfolder_skipped(mocker):
    """When a subfolder exists but is empty no file ID is set."""
    mock_gdrive = mocker.Mock()
    mock_gdrive.find_subfolder_by_name.return_value = "cover_subfolder"
    mock_gdrive.list_folder_contents.return_value = []  # Empty subfolder
    edition = _make_edition_with_folder_components()

    result = resolve_folder_components(mock_gdrive, "folder_id", edition)

    assert result.cover_file_id is None


def test_resolve_folder_components_no_subfolders(mocker):
    """When no component subfolders exist the edition is returned unchanged."""
    mock_gdrive = mocker.Mock()
    mock_gdrive.find_subfolder_by_name.return_value = None
    edition = _make_edition_with_folder_components()

    result = resolve_folder_components(mock_gdrive, "folder_id", edition)

    assert result.cover_file_id is None
    assert result.preface_file_ids is None
    assert result.postface_file_ids is None


def test_resolve_folder_components_all_resolved(mocker):
    """All three components are resolved from their respective subfolders."""

    def find_subfolder(fid, name):
        return f"{name.lower()}_subfolder"

    def list_folder(subfolder_id):
        if subfolder_id == "cover_subfolder":
            return [File(id="cover_id", name="Cover.gdoc")]
        if subfolder_id == "preface_subfolder":
            return [
                File(id="pre_1", name="Intro.gdoc"),
                File(id="pre_2", name="Welcome.gdoc"),
            ]
        if subfolder_id == "postface_subfolder":
            return [File(id="post_1", name="Credits.gdoc")]
        return []

    mock_gdrive = mocker.Mock()
    mock_gdrive.find_subfolder_by_name.side_effect = find_subfolder
    mock_gdrive.list_folder_contents.side_effect = list_folder
    edition = _make_edition_with_folder_components()

    result = resolve_folder_components(mock_gdrive, "folder_id", edition)

    assert result.cover_file_id == "cover_id"
    assert result.preface_file_ids == ["pre_1", "pre_2"]
    assert result.postface_file_ids == ["post_1"]


def test_load_edition_from_drive_folder_resolves_components(mocker):
    """load_edition_from_drive_folder calls resolve_folder_components."""
    import yaml as _yaml

    yaml_content = _yaml.dump(
        {
            "id": "test",
            "title": "Test Edition",
            "description": "Desc",
            "use_folder_components": True,
            "filters": [],
        }
    ).encode()

    mock_gdrive_client = mocker.Mock()
    mock_gdrive_client.find_file_in_folder.return_value = File(
        id="yaml_id", name=".songbook.yaml"
    )
    mock_gdrive_client.download_raw_bytes.return_value = yaml_content

    mock_resolve = mocker.patch("generator.worker.pdf.resolve_folder_components")
    mock_resolve.side_effect = lambda gd, fid, ed: ed  # pass-through
    mocker.patch("generator.worker.pdf._resolve_songs_from_folder", return_value=None)

    edition, songs_files = load_edition_from_drive_folder(
        mock_gdrive_client, "folder_id"
    )

    mock_resolve.assert_called_once()
    call_args = mock_resolve.call_args
    assert call_args.args[1] == "folder_id"
    loaded_edition = call_args.args[2]
    assert loaded_edition.use_folder_components is True


def test_load_edition_from_drive_folder_no_components_when_disabled(mocker):
    """resolve_folder_components receives the edition even when disabled."""
    import yaml as _yaml

    yaml_content = _yaml.dump(
        {
            "id": "test",
            "title": "Test Edition",
            "description": "Desc",
            "use_folder_components": False,
            "filters": [],
        }
    ).encode()

    mock_gdrive_client = mocker.Mock()
    mock_gdrive_client.find_file_in_folder.return_value = File(
        id="yaml_id", name=".songbook.yaml"
    )
    mock_gdrive_client.download_raw_bytes.return_value = yaml_content

    mock_resolve = mocker.patch("generator.worker.pdf.resolve_folder_components")
    mock_resolve.side_effect = lambda gd, fid, ed: ed  # pass-through

    edition, songs_files = load_edition_from_drive_folder(
        mock_gdrive_client, "folder_id"
    )

    # resolve_folder_components is always called; it exits early internally
    mock_resolve.assert_called_once()
    loaded_edition = mock_resolve.call_args.args[2]
    assert loaded_edition.use_folder_components is False
    # Songs scanning is skipped when use_folder_components is False
    assert songs_files is None


def test_load_edition_from_drive_folder_returns_songs_files(mocker):
    """When use_folder_components=True and a Songs subfolder exists, the
    second element of the tuple contains the resolved song files."""
    import yaml as _yaml

    yaml_content = _yaml.dump(
        {
            "id": "test",
            "title": "Test Edition",
            "description": "Desc",
            "use_folder_components": True,
            "filters": [],
        }
    ).encode()

    expected_songs = [
        File(id="song_1", name="Song A.pdf"),
        File(id="song_2", name="Song B.pdf"),
    ]

    mock_gdrive_client = mocker.Mock()
    mock_gdrive_client.find_file_in_folder.return_value = File(
        id="yaml_id", name=".songbook.yaml"
    )
    mock_gdrive_client.download_raw_bytes.return_value = yaml_content

    mocker.patch(
        "generator.worker.pdf.resolve_folder_components",
        side_effect=lambda gd, fid, ed: ed,
    )
    mocker.patch(
        "generator.worker.pdf._resolve_songs_from_folder",
        return_value=expected_songs,
    )

    edition, songs_files = load_edition_from_drive_folder(
        mock_gdrive_client, "folder_id"
    )

    assert songs_files == expected_songs


# ---------------------------------------------------------------------------
# _resolve_songs_from_folder tests
# ---------------------------------------------------------------------------


def test_resolve_songs_from_folder_returns_sorted_files(mocker):
    """Files from the Songs subfolder are returned sorted by song sort key."""
    mock_gdrive = mocker.Mock()
    mock_gdrive.find_subfolder_by_name.return_value = "songs_subfolder"
    mock_gdrive.list_folder_contents.return_value = [
        File(id="song_2", name="Bohemian Rhapsody.pdf"),
        File(id="song_1", name="Amazing Grace.pdf"),
    ]

    result = _resolve_songs_from_folder(mock_gdrive, "folder_id")

    assert result is not None
    assert len(result) == 2
    assert result[0].name == "Amazing Grace.pdf"
    assert result[1].name == "Bohemian Rhapsody.pdf"
    mock_gdrive.find_subfolder_by_name.assert_called_once_with("folder_id", "Songs")


def test_resolve_songs_from_folder_no_subfolder_returns_none(mocker):
    """When no Songs subfolder exists, None is returned."""
    mock_gdrive = mocker.Mock()
    mock_gdrive.find_subfolder_by_name.return_value = None

    result = _resolve_songs_from_folder(mock_gdrive, "folder_id")

    assert result is None


def test_resolve_songs_from_folder_empty_subfolder_returns_none(mocker):
    """When the Songs subfolder is empty, None is returned."""
    mock_gdrive = mocker.Mock()
    mock_gdrive.find_subfolder_by_name.return_value = "songs_subfolder"
    mock_gdrive.list_folder_contents.return_value = []

    result = _resolve_songs_from_folder(mock_gdrive, "folder_id")

    assert result is None


# ---------------------------------------------------------------------------
# resolve_folder_components – cover/preface/postface only (no songs)
# ---------------------------------------------------------------------------


def test_resolve_folder_components_all_three_resolved(mocker):
    """Cover, preface, and postface are all resolved from subfolders."""

    def find_subfolder(fid, name):
        return f"{name.lower()}_subfolder"

    def list_folder(subfolder_id):
        if subfolder_id == "cover_subfolder":
            return [File(id="cover_id", name="Cover.gdoc")]
        if subfolder_id == "preface_subfolder":
            return [File(id="pre_1", name="Intro.gdoc")]
        if subfolder_id == "postface_subfolder":
            return [File(id="post_1", name="Credits.gdoc")]
        return []

    mock_gdrive = mocker.Mock()
    mock_gdrive.find_subfolder_by_name.side_effect = find_subfolder
    mock_gdrive.list_folder_contents.side_effect = list_folder
    edition = _make_edition_with_folder_components()

    result = resolve_folder_components(mock_gdrive, "folder_id", edition)

    assert result.cover_file_id == "cover_id"
    assert result.preface_file_ids == ["pre_1"]
    assert result.postface_file_ids == ["post_1"]
    # Songs are no longer part of resolve_folder_components
    calls = [
        c.args[1].lower() for c in mock_gdrive.find_subfolder_by_name.call_args_list
    ]
    assert "songs" not in calls


# ---------------------------------------------------------------------------
# generate_songbook_from_edition – files parameter tests
# ---------------------------------------------------------------------------


def test_generate_songbook_from_edition_with_pre_supplied_files(mocker):
    """When files= is provided, it is passed directly to generate_songbook."""
    from ..common.config import Edition as Cfg_Edition

    song_files = [
        File(id="song_1", name="Amazing Grace.pdf"),
        File(id="song_2", name="Bohemian Rhapsody.pdf"),
    ]
    mock_generate = mocker.patch("generator.worker.pdf.generate_songbook")

    edition = Cfg_Edition(
        id="test",
        title="Test",
        description="Test",
        filters=[],
    )

    generate_songbook_from_edition(
        drive="mock_drive",
        cache="mock_cache",
        source_folders=["folder_id"],
        destination_path=Path("/tmp/out.pdf"),
        edition=edition,
        limit=None,
        files=song_files,
    )

    call_kwargs = mock_generate.call_args.kwargs
    assert call_kwargs["files"] is song_files


def test_generate_songbook_from_edition_without_files_passes_none(mocker):
    """When files= is not provided, None is passed so the standard
    filter-based query runs inside generate_songbook."""
    from ..common.config import Edition as Cfg_Edition

    mock_generate = mocker.patch("generator.worker.pdf.generate_songbook")

    edition = Cfg_Edition(
        id="test",
        title="Test",
        description="Test",
        filters=[],
    )

    generate_songbook_from_edition(
        drive="mock_drive",
        cache="mock_cache",
        source_folders=["folder_id"],
        destination_path=Path("/tmp/out.pdf"),
        edition=edition,
        limit=None,
    )

    call_kwargs = mock_generate.call_args.kwargs
    assert call_kwargs["files"] is None


# ---------------------------------------------------------------------------
# copy_pdfs – ID-based TOC lookup
# ---------------------------------------------------------------------------


def _make_merged_pdf_with_toc(file_id: str) -> bytes:
    """Build a minimal single-page merged PDF whose TOC entry uses *file_id*."""
    doc = fitz.open()
    doc.new_page()
    doc.set_toc([[1, file_id, 1]])
    buf = doc.tobytes()
    doc.close()
    return buf


def test_copy_pdfs_looks_up_by_file_id(mocker):
    """copy_pdfs succeeds when the TOC entry title matches file.id."""
    cached_pdf_bytes = _make_merged_pdf_with_toc("song_file_id_123")

    mock_cache = mocker.Mock()
    mock_cache.get.return_value = cached_pdf_bytes

    mock_step = mocker.Mock()

    dest = fitz.open()

    files = [File(id="song_file_id_123", name="Amazing Grace")]

    # Should not raise — ID is found in the TOC
    copy_pdfs(dest, files, mock_cache, page_offset=0, progress_step=mock_step)
    dest.close()


def test_copy_pdfs_misses_when_id_absent_even_if_name_matches(mocker):
    """A file whose ID is not in the TOC raises PdfCacheMissException,
    even if the TOC happens to contain the file's name as an entry title
    (i.e. an old name-keyed cache must not be used)."""
    # TOC keyed by name (simulates an old-style cache)
    cached_pdf_bytes = _make_merged_pdf_with_toc("Amazing Grace")

    mock_cache = mocker.Mock()
    mock_cache.get.return_value = cached_pdf_bytes

    mock_step = mocker.Mock()
    dest = fitz.open()

    files = [File(id="song_file_id_123", name="Amazing Grace")]

    with pytest.raises(PdfCacheMissException):
        copy_pdfs(dest, files, mock_cache, page_offset=0, progress_step=mock_step)

    dest.close()


def test_copy_pdfs_custom_file_with_same_name_misses_cache(mocker):
    """A custom drive-edition file with the same name as a cached original
    misses the cache because its ID differs, triggering the fallback."""
    original_id = "original_id_abc"
    custom_id = "custom_id_xyz"

    # Merged cache only knows the original file's ID
    cached_pdf_bytes = _make_merged_pdf_with_toc(original_id)

    mock_cache = mocker.Mock()
    mock_cache.get.return_value = cached_pdf_bytes

    mock_step = mocker.Mock()
    dest = fitz.open()

    # The pre-supplied file has the same name but a different ID
    files = [File(id=custom_id, name="Amazing Grace")]

    with pytest.raises(PdfCacheMissException):
        copy_pdfs(dest, files, mock_cache, page_offset=0, progress_step=mock_step)

    dest.close()


def test_copy_pdfs_raises_when_no_merged_cache(mocker):
    """PdfCacheNotFound is raised when the merged PDF is absent from cache."""
    mock_cache = mocker.Mock()
    mock_cache.get.return_value = None

    mock_step = mocker.Mock()
    dest = fitz.open()

    files = [File(id="any_id", name="Any Song")]

    with pytest.raises(PdfCacheNotFound):
        copy_pdfs(dest, files, mock_cache, page_offset=0, progress_step=mock_step)

    dest.close()
