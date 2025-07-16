from .pdf import collect_and_sort_files
from .filters import PropertyFilter, FilterOperator


def test_collect_and_sort_files_single_folder(mocker):
    """Test that files from a single folder are returned sorted by name."""
    mock_drive = mocker.Mock()

    # Mock files in non-alphabetical order
    mock_files = [
        {"name": "zebra.pdf", "id": "3"},
        {"name": "apple.pdf", "id": "1"},
        {"name": "banana.pdf", "id": "2"},
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
        {"name": "apple.pdf", "id": "1"},
        {"name": "banana.pdf", "id": "2"},
        {"name": "zebra.pdf", "id": "3"},
    ]
    assert result == expected

    # Verify the query was called correctly
    mock_query.assert_called_once_with(mock_drive, "folder1", None)


def test_collect_and_sort_files_multiple_folders(mocker):
    """Test that files from multiple folders are aggregated and sorted."""
    mock_drive = mocker.Mock()

    # Mock files from different folders
    folder1_files = [
        {"name": "zebra.pdf", "id": "1"},
        {"name": "banana.pdf", "id": "2"},
    ]
    folder2_files = [
        {"name": "apple.pdf", "id": "3"},
        {"name": "cherry.pdf", "id": "4"},
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
        {"name": "apple.pdf", "id": "3"},
        {"name": "banana.pdf", "id": "2"},
        {"name": "cherry.pdf", "id": "4"},
        {"name": "zebra.pdf", "id": "1"},
    ]
    assert result == expected

    # Verify queries were called for both folders
    assert mock_query.call_count == 2


def test_collect_and_sort_files_with_client_filter(mocker):
    """Test that client filter is passed through correctly."""
    mock_drive = mocker.Mock()
    mock_filter = PropertyFilter("artist", FilterOperator.EQUALS, "Test Artist")

    mock_files = [{"name": "test.pdf", "id": "1"}]

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

    folder1_files = [{"name": "file1.pdf", "id": "1"}]
    folder2_files = [{"name": "file2.pdf", "id": "2"}]

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
        {"name": "file1.pdf", "id": "1"},
        {"name": "file2.pdf", "id": "2"},
    ]
    assert result == expected


def test_collect_and_sort_files_no_progress_step(mocker):
    """Test that no progress reporting occurs when progress_step is None."""
    mock_drive = mocker.Mock()

    mock_files = [{"name": "test.pdf", "id": "1"}]

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
        {"name": "ab - a.pdf", "id": "1"},
        {"name": "a - cd.pdf", "id": "2"},
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
        {"name": "a - cd.pdf", "id": "2"},
        {"name": "ab - a.pdf", "id": "1"},
    ]
    assert result == expected


def test_collect_and_sort_files_case_sensitive_sorting(mocker):
    """Test that sorting handles different cases correctly."""
    mock_drive = mocker.Mock()

    mock_files = [
        {"name": "Zebra.pdf", "id": "1"},
        {"name": "apple.pdf", "id": "2"},
        {"name": "Banana.pdf", "id": "3"},
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
        {"name": "apple.pdf", "id": "2"},
        {"name": "Banana.pdf", "id": "3"},
        {"name": "Zebra.pdf", "id": "1"},
    ]
    assert result == expected


def test_collect_and_sort_files_strips_punctuation(mocker):
    mock_drive = mocker.Mock()

    mock_files = [
        {"name": "!!banana.pdf", "id": "1"},
        {"name": "apple", "id": "2"},
        {"name": "cucumber.pdf", "id": "3"},
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
        {"name": "apple", "id": "2"},
        {"name": "!!banana.pdf", "id": "1"},
        {"name": "cucumber.pdf", "id": "3"},
    ]
    assert result == expected


def test_collect_and_sort_files_accent_sensitive_sorting(mocker):
    mock_drive = mocker.Mock()

    mock_files = [
        {"name": "çb.pdf", "id": "1"},
        {"name": "ca", "id": "2"},
        {"name": "cz.pdf", "id": "3"},
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
        {"name": "ca", "id": "2"},
        {"name": "çb.pdf", "id": "1"},
        {"name": "cz.pdf", "id": "3"},
    ]
    assert result == expected


def test_collect_and_sort_files_numeral_sensitive_sorting(mocker):
    mock_drive = mocker.Mock()

    mock_files = [
        {"name": "01 things.pdf", "id": "1"},
        {"name": "things 100 things", "id": "2"},
        {"name": "things 001 things.pdf", "id": "3"},
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
        {"name": "01 things.pdf", "id": "1"},
        {"name": "things 001 things.pdf", "id": "3"},
        {"name": "things 100 things", "id": "2"},
    ]
    assert result == expected


def test_collect_and_sort_files_progress_increment_calculation(mocker):
    """Test that progress increments are calculated correctly for different folder counts."""
    mock_drive = mocker.Mock()
    mock_progress_step = mocker.Mock()

    # Test with 3 folders
    folder_files = [{"name": "file.pdf", "id": "1"}]

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
            return [{"name": "file1.pdf", "id": "1"}]
        elif folder == "folder2":
            return []  # Empty folder
        elif folder == "folder3":
            return [{"name": "file2.pdf", "id": "2"}]
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
        {"name": "file1.pdf", "id": "1"},
        {"name": "file2.pdf", "id": "2"},
    ]
    assert result == expected

    # Should have queried all folders
    assert mock_query.call_count == 3
