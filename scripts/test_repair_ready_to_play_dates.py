"""Unit tests for the pure logic of the #442 date-repair script."""

from repair_ready_to_play_dates import (
    UNKNOWN,
    choose_new_value,
    find_corrupt_docs,
    is_corrupt,
    parse_iso,
    parse_legacy_date,
)

# The 2026-06-19 corruption window (whole UTC day).
START = parse_iso("2026-06-19T00:00:00Z")
END = parse_iso("2026-06-20T00:00:00Z")


def test_parse_legacy_date_converts_yyyymmdd_to_iso_midnight():
    assert parse_legacy_date("20211102") == "2021-11-02T00:00:00Z"


def test_parse_legacy_date_rejects_bad_input():
    assert parse_legacy_date(None) is None
    assert parse_legacy_date("") is None
    assert parse_legacy_date("not-a-date") is None
    assert parse_legacy_date("unknown") is None


def test_is_corrupt_detects_values_in_window():
    assert is_corrupt("2026-06-19T09:53:00Z", START, END) is True
    # Just outside the window on either side.
    assert is_corrupt("2026-06-18T23:59:59Z", START, END) is False
    assert is_corrupt("2026-06-20T00:00:00Z", START, END) is False
    # Non-values are never corrupt.
    assert is_corrupt(None, START, END) is False
    assert is_corrupt(UNKNOWN, START, END) is False


def test_move_on_or_before_first_played_is_kept():
    # ready_to_play precedes first-played: the derived move date is valid.
    value, source = choose_new_value("2024-09-04T00:05:00Z", "20250415")
    assert value == "2024-09-04T00:05:00Z"
    assert source == "activity"


def test_move_after_first_played_falls_back_to_legacy_date():
    # A song can't become ready-to-play after it was first played; the move date
    # is a bulk-migration artifact, so use the legacy first-played date.
    value, source = choose_new_value("2024-08-06T16:10:00Z", "20230620")
    assert value == "2023-06-20T00:00:00Z"
    assert source == "legacy-date"


def test_move_same_day_as_first_played_is_kept():
    # Same-day (legacy is midnight-precise): keep the more precise move time.
    value, source = choose_new_value("2023-06-20T10:00:00Z", "20230620")
    assert value == "2023-06-20T10:00:00Z"
    assert source == "activity"


def test_move_with_no_legacy_date_is_kept():
    value, source = choose_new_value("2024-09-04T00:05:00Z", None)
    assert value == "2024-09-04T00:05:00Z"
    assert source == "activity"


def test_no_move_falls_back_to_legacy_date():
    value, source = choose_new_value(None, "20230620")
    assert value == "2023-06-20T00:00:00Z"
    assert source == "legacy-date"


def test_no_move_and_no_legacy_date_becomes_unknown():
    value, source = choose_new_value(None, None)
    assert value == UNKNOWN
    assert source == "unknown"


def test_find_corrupt_docs_filters_and_sorts_by_name():
    docs = {
        "corruptB": {
            "gdrive_file_name": "Zebra - Band",
            "properties": {"ready_to_play_date": "2026-06-19T10:00:00Z"},
        },
        "corruptA": {
            "gdrive_file_name": "Apple - Band",
            "properties": {"ready_to_play_date": "2026-06-19T09:49:00Z"},
        },
        "clean": {
            "gdrive_file_name": "Real - Band",
            "properties": {"ready_to_play_date": "2023-06-20T10:02:00Z"},
        },
        "unknown_val": {
            "gdrive_file_name": "Sentinel - Band",
            "properties": {"ready_to_play_date": "unknown"},
        },
        "no_field": {"gdrive_file_name": "None - Band", "properties": {}},
    }

    result = find_corrupt_docs(docs, "ready_to_play_date", START, END)

    # Only the two in-window docs, sorted by song name (Apple before Zebra).
    assert [file_id for file_id, _doc, _val in result] == ["corruptA", "corruptB"]
    assert result[0][2] == "2026-06-19T09:49:00Z"
