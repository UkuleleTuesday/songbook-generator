import fitz
import pytest
from ..common.config import Edition
from .pdf import collect_and_sort_files, generate_songbook, generate_songbook_from_edition
from ..common.filters import PropertyFilter, FilterOperator, FilterGroup
from .models import File


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


def test_generate_songbook_sets_metadata(mocker, tmp_path):
    """Verify that PDF metadata is correctly set in the generated songbook."""
    mock_drive = mocker.Mock()
    mock_cache = mocker.Mock()
    destination_path = tmp_path / "songbook.pdf"

    # Mock dependencies to isolate metadata setting
    mocker.patch(
        "generator.worker.pdf.collect_and_sort_files", return_value=[File(name="Test Song.pdf", id="123")]
    )
    mocker.patch("generator.worker.pdf.get_files_metadata_by_ids", return_value=[])
    mocker.patch("generator.worker.cover.CoverGenerator.generate_cover", return_value=fitz.open())
    mocker.patch(
        "generator.worker.toc.build_table_of_contents",
        side_effect=lambda files, page_offset: (fitz.open().new_page().parent, []),
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


def test_collect_and_sort_files_single_folder(mocker):
    """Test that files from a single folder are returned sorted by name."""
    mock_drive = mocker.Mock()

    # Mock files in non-alphabetical order
    mock_files = [
        File(name="zebra.pdf", id="3"),
        File(name="apple.pdf", id="1"),
        File(name="banana.pdf", id="2"),
    ]

    mock_query = mocker.patch(
        "generator.worker.pdf.query_drive_files_with_client_filter"
    )
    mock_query.return_value = mock_files

    result = collect_and_sort_files(
        drive=mock_drive,
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
    mock_query.assert_called_once_with(mock_drive, "folder1", None)


def test_collect_and_sort_files_multiple_folders(mocker):
    """Test that files from multiple folders are aggregated and sorted."""
    mock_drive = mocker.Mock()

    # Mock files from different folders
    folder1_files = [
        File(name="zebra.pdf", id="1"),
        File(name="banana.pdf", id="2"),
    ]
    folder2_files = [
        File(name="apple.pdf", id="3"),
        File(name="cherry.pdf", id="4"),
    ]

    def mock_query_side_effect(drive, folder, filter):
        if folder == "folder1":
            return folder1_files
        elif folder == "folder2":
            return folder2_files
        return []

    mock_query = mocker.patch(
        "generator.worker.pdf.query_drive_files_with_client_filter"
    )
    mock_query.side_effect = mock_query_side_effect

    result = collect_and_sort_files(
        drive=mock_drive,
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

    # Verify queries were called for both folders
    assert mock_query.call_count == 2


def test_collect_and_sort_files_with_client_filter(mocker):
    """Test that client filter is passed through correctly."""
    mock_drive = mocker.Mock()
    mock_filter = PropertyFilter(
        key="artist", operator=FilterOperator.EQUALS, value="Test Artist"
    )

    mock_files = [File(name="test.pdf", id="1")]

    mock_query = mocker.patch(
        "generator.worker.pdf.query_drive_files_with_client_filter"
    )
    mock_query.return_value = mock_files

    result = collect_and_sort_files(
        drive=mock_drive,
        source_folders=["folder1"],
        client_filter=mock_filter,
    )

    assert result == mock_files
    mock_query.assert_called_once_with(mock_drive, "folder1", mock_filter)


def test_collect_and_sort_files_empty_folders(mocker):
    """Test that empty folders return an empty list."""
    mock_drive = mocker.Mock()

    mock_query = mocker.patch(
        "generator.worker.pdf.query_drive_files_with_client_filter"
    )
    mock_query.return_value = []

    result = collect_and_sort_files(
        drive=mock_drive,
        source_folders=["empty_folder"],
    )

    assert result == []


def test_collect_and_sort_files_with_progress_step(mocker):
    """Test that progress is reported correctly when progress_step is provided."""
    mock_drive = mocker.Mock()
    mock_progress_step = mocker.Mock()

    folder1_files = [File(name="file1.pdf", id="1")]
    folder2_files = [File(name="file2.pdf", id="2")]

    def mock_query_side_effect(drive, folder, filter):
        if folder == "folder1":
            return folder1_files
        elif folder == "folder2":
            return folder2_files
        return []

    mock_query = mocker.patch(
        "generator.worker.pdf.query_drive_files_with_client_filter"
    )
    mock_query.side_effect = mock_query_side_effect

    result = collect_and_sort_files(
        drive=mock_drive,
        source_folders=["folder1", "folder2"],
        progress_step=mock_progress_step,
    )

    # Verify progress was reported for each folder
    assert mock_progress_step.increment.call_count == 2
    mock_progress_step.increment.assert_any_call(
        0.5, "Found 1 files in folder 1: folder1"
    )
    mock_progress_step.increment.assert_any_call(
        0.5, "Found 1 files in folder 2: folder2"
    )

    # Verify files are still sorted correctly
    expected = [
        File(name="file1.pdf", id="1"),
        File(name="file2.pdf", id="2"),
    ]
    assert result == expected


def test_collect_and_sort_files_no_progress_step(mocker):
    """Test that no progress reporting occurs when progress_step is None."""
    mock_drive = mocker.Mock()

    mock_files = [File(name="test.pdf", id="1")]

    mock_query = mocker.patch(
        "generator.worker.pdf.query_drive_files_with_client_filter"
    )
    mock_query.return_value = mock_files

    # Should not raise any errors when progress_step is None
    result = collect_and_sort_files(
        drive=mock_drive,
        source_folders=["folder1"],
        progress_step=None,
    )

    assert result == mock_files


def test_collect_and_sort_files_strips_artist_name(mocker):
    """Test that sorting handles different cases correctly."""
    mock_drive = mocker.Mock()

    mock_files = [
        File(name="ab - a.pdf", id="1"),
        File(name="a - cd.pdf", id="2"),
    ]

    mock_query = mocker.patch(
        "generator.worker.pdf.query_drive_files_with_client_filter"
    )
    mock_query.return_value = mock_files

    result = collect_and_sort_files(
        drive=mock_drive,
        source_folders=["folder1"],
    )

    expected = [
        File(name="a - cd.pdf", id="2"),
        File(name="ab - a.pdf", id="1"),
    ]
    assert result == expected


def test_collect_and_sort_files_case_sensitive_sorting(mocker):
    """Test that sorting handles different cases correctly."""
    mock_drive = mocker.Mock()

    mock_files = [
        File(name="Zebra.pdf", id="1"),
        File(name="apple.pdf", id="2"),
        File(name="Banana.pdf", id="3"),
    ]

    mock_query = mocker.patch(
        "generator.worker.pdf.query_drive_files_with_client_filter"
    )
    mock_query.return_value = mock_files

    result = collect_and_sort_files(
        drive=mock_drive,
        source_folders=["folder1"],
    )

    expected = [
        File(name="apple.pdf", id="2"),
        File(name="Banana.pdf", id="3"),
        File(name="Zebra.pdf", id="1"),
    ]
    assert result == expected


def test_collect_and_sort_files_strips_punctuation(mocker):
    mock_drive = mocker.Mock()

    mock_files = [
        File(name="!!banana.pdf", id="1"),
        File(name="apple", id="2"),
        File(name="cucumber.pdf", id="3"),
    ]

    mock_query = mocker.patch(
        "generator.worker.pdf.query_drive_files_with_client_filter"
    )
    mock_query.return_value = mock_files

    result = collect_and_sort_files(
        drive=mock_drive,
        source_folders=["folder1"],
    )

    expected = [
        File(name="apple", id="2"),
        File(name="!!banana.pdf", id="1"),
        File(name="cucumber.pdf", id="3"),
    ]
    assert result == expected


def test_collect_and_sort_files_accent_sensitive_sorting(mocker):
    mock_drive = mocker.Mock()

    mock_files = [
        File(name="çb.pdf", id="1"),
        File(name="ca", id="2"),
        File(name="cz.pdf", id="3"),
    ]

    mock_query = mocker.patch(
        "generator.worker.pdf.query_drive_files_with_client_filter"
    )
    mock_query.return_value = mock_files

    result = collect_and_sort_files(
        drive=mock_drive,
        source_folders=["folder1"],
    )

    expected = [
        File(name="ca", id="2"),
        File(name="çb.pdf", id="1"),
        File(name="cz.pdf", id="3"),
    ]
    assert result == expected


def test_collect_and_sort_files_numeral_sensitive_sorting(mocker):
    mock_drive = mocker.Mock()

    mock_files = [
        File(name="01 things.pdf", id="1"),
        File(name="things 100 things", id="2"),
        File(name="things 001 things.pdf", id="3"),
    ]

    mock_query = mocker.patch(
        "generator.worker.pdf.query_drive_files_with_client_filter"
    )
    mock_query.return_value = mock_files

    result = collect_and_sort_files(
        drive=mock_drive,
        source_folders=["folder1"],
    )
    expected = [
        File(name="01 things.pdf", id="1"),
        File(name="things 001 things.pdf", id="3"),
        File(name="things 100 things", id="2"),
    ]
    assert result == expected


def test_collect_and_sort_files_progress_increment_calculation(mocker):
    """Test that progress increments are calculated correctly for different folder counts."""
    mock_drive = mocker.Mock()
    mock_progress_step = mocker.Mock()

    # Test with 3 folders
    folder_files = [File(name="file.pdf", id="1")]

    mock_query = mocker.patch(
        "generator.worker.pdf.query_drive_files_with_client_filter"
    )
    mock_query.return_value = folder_files

    collect_and_sort_files(
        drive=mock_drive,
        source_folders=["folder1", "folder2", "folder3"],
        progress_step=mock_progress_step,
    )

    # Each folder should get 1/3 of the progress
    expected_increment = 1.0 / 3
    assert mock_progress_step.increment.call_count == 3
    for i in range(3):
        args, kwargs = mock_progress_step.increment.call_args_list[i]
        assert args[0] == expected_increment
        assert f"Found 1 files in folder {i + 1}: folder{i + 1}" in args[1]


def test_collect_and_sort_files_mixed_empty_and_non_empty_folders(mocker):
    """Test handling of mixed empty and non-empty folders."""
    mock_drive = mocker.Mock()

    def mock_query_side_effect(drive, folder, filter):
        if folder == "folder1":
            return [File(name="file1.pdf", id="1")]
        elif folder == "folder2":
            return []  # Empty folder
        elif folder == "folder3":
            return [File(name="file2.pdf", id="2")]
        return []

    mock_query = mocker.patch(
        "generator.worker.pdf.query_drive_files_with_client_filter"
    )
    mock_query.side_effect = mock_query_side_effect

    result = collect_and_sort_files(
        drive=mock_drive,
        source_folders=["folder1", "folder2", "folder3"],
    )

    # Should only return files from non-empty folders, sorted
    expected = [
        File(name="file1.pdf", id="1"),
        File(name="file2.pdf", id="2"),
    ]
    assert result == expected

    # Should have queried all folders
    assert mock_query.call_count == 3
