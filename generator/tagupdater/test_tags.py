import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from ..worker.models import File
from .tags import (
    FOLDER_ID_APPROVED,
    FOLDER_ID_READY_TO_PLAY,
    Tagger,
    status,
    tag,
    Context,
    GoogleDocument,
)

TEST_DATA_DIR = Path(__file__).parent / "test_data"


@pytest.fixture
def doc_json(request):
    """A fixture to load a JSON file from the test_data directory."""
    file_path = TEST_DATA_DIR / request.param
    with open(file_path) as f:
        return json.load(f)


@pytest.fixture
def mock_drive_service():
    """Create a mock Google Drive service object."""
    return Mock()


@pytest.fixture
def mock_docs_service():
    """Create a mock Google Docs service object."""
    return Mock()


def test_status_tagger():
    """Test the status tag function logic."""
    file_approved = File(id="1", name="f1", parents=[FOLDER_ID_APPROVED])
    assert status(Context(file=file_approved)) == "APPROVED"

    file_ready = File(id="2", name="f2", parents=[FOLDER_ID_READY_TO_PLAY])
    assert status(Context(file=file_ready)) == "READY_TO_PLAY"

    file_other = File(id="3", name="f3", parents=["some_other_folder"])
    assert status(Context(file=file_other)) is None

    file_no_parents = File(id="4", name="f4")
    assert status(Context(file=file_no_parents)) is None


def test_update_tags_with_status_tag(mock_drive_service, mock_docs_service):
    """Test Tagger.update_tags with the status tag."""
    tagger = Tagger(mock_drive_service, mock_docs_service)
    file_to_tag = File(
        id="file123",
        name="test.pdf",
        parents=[FOLDER_ID_APPROVED],
    )

    tagger.update_tags(file_to_tag)

    expected_body = {"properties": {"status": "APPROVED"}}
    mock_drive_service.files.return_value.update.assert_called_once_with(
        fileId="file123", body=expected_body, fields="properties"
    )


@pytest.mark.parametrize(
    "doc_json, tag_func, expected_value",
    [
        (
            "all_the_small_things.json",
            "chords",
            "G,F,C",
        ),
        (
            "all_the_small_things.json",
            "artist",
            "Blink-182",
        ),
        (
            "all_the_small_things.json",
            "song_title",
            "All The Small Things",
        ),
        (
            "all_the_small_things.json",
            "bpm",
            "149",
        ),
        (
            "all_the_small_things.json",
            "time_signature",
            "4/4",
        ),
        (
            "space_oddity.json",
            "song_title",
            "Space Oddity",
        ),
        (
            "space_oddity.json",
            "artist",
            "David Bowie",
        ),
        (
            "mustang_sally.json",
            "song_title",
            "Kiss/Mustang Sally Medley",
        ),
        (
            "mustang_sally.json",
            "artist",
            "Prince/The Commitments",
        ),
        (
            "final_countdown.json",
            "song_title",
            "The Final Countdown",
        ),
        (
            "final_countdown.json",
            "artist",
            "Europe",
        ),
        (
            "we_are_young.json",
            "song_title",
            "We Are Young",
        ),
        (
            "we_are_young.json",
            "artist",
            "fun. (feat. Janelle Monáe)",
        ),
        (
            "space_oddity.json",
            "chords",
            "FMaj7,Em,C,Am,Am7,D7,E7,F,Fm,BbMaj7,G,A,D,E",
        ),
        (
            "space_oddity.json",
            "bpm",
            "70",
        ),
        (
            "space_oddity.json",
            "time_signature",
            "4/4",
        ),
        (
            "mustang_sally.json",
            "chords",
            "B7sus4,A,D7,A7,E7,D7sus4,Dsus4,D,Dsus2,A7no5,F#m,Eb7",
        ),
        (
            "mustang_sally.json",
            "bpm",
            "111",
        ),
        (
            "mustang_sally.json",
            "time_signature",
            "4/4",
        ),
        (
            "final_countdown.json",
            "chords",
            "F#m,D,Bm,E,C#,A,C#7sus4,C#7,C#m,G,Em",
        ),
        (
            "final_countdown.json",
            "bpm",
            "118",
        ),
        (
            "final_countdown.json",
            "time_signature",
            "4/4",
        ),
        (
            "we_are_young.json",
            "chords",
            "feat. Janelle Monáe,F,Dm,Gm,Bb,C,Am,Csus4",
        ),
        (
            "we_are_young.json",
            "bpm",
            "116,92",
        ),
        (
            "we_are_young.json",
            "time_signature",
            "4/4",
        ),
        # Test cases for love_me_do.json
        (
            "love_me_do.json",
            "song_title",
            "Love Me Do",
        ),
        (
            "love_me_do.json",
            "artist",
            "The Beatles",
        ),
        (
            "love_me_do.json",
            "chords",
            "G,C,D,D7",
        ),
        (
            "love_me_do.json",
            "bpm",
            "148",
        ),
        (
            "love_me_do.json",
            "time_signature",
            "4/4",
        ),
        (
            "love_me_do.json",
            "features",
            "no_chord,swing",
        ),
    ],
    indirect=["doc_json"],  # Tells pytest to pass the param to the fixture
)
def test_tagger_functions(doc_json, tag_func, expected_value):
    """Test tagger functions using real JSON fixtures."""
    from . import tags

    # Dynamically get the tagger function by name
    func = getattr(tags, tag_func)
    context = Context(file=Mock(), document=GoogleDocument(json=doc_json))
    assert func(context) == expected_value


def test_update_tags_no_update_if_tag_returns_none(mock_drive_service, mock_docs_service):
    """Test that no update is made if the tag function returns None."""
    tagger = Tagger(mock_drive_service, mock_docs_service)
    file_to_tag = File(id="file123", name="test.pdf", parents=["other_folder"])

    tagger.update_tags(file_to_tag)

    mock_drive_service.files.return_value.update.assert_not_called()


def test_update_tags_no_update_if_tags_are_identical(
    mock_drive_service, mock_docs_service
):
    """Test that no update is made if the generated tags match existing ones."""
    tagger = Tagger(mock_drive_service, mock_docs_service)
    file_to_tag = File(
        id="file123",
        name="test.pdf",
        parents=[FOLDER_ID_APPROVED],
        properties={"status": "APPROVED"},
    )

    tagger.update_tags(file_to_tag)

    mock_drive_service.files.return_value.update.assert_not_called()


def test_update_tags_with_multiple_tags_and_preserves_existing(
    mock_drive_service, mock_docs_service
):
    """Test that multiple tags are applied and existing properties preserved."""

    @tag
    def another_tag(ctx: Context) -> str:
        return "another_value"

    try:
        tagger = Tagger(mock_drive_service, mock_docs_service)
        file_to_tag = File(
            id="file123",
            name="test.pdf",
            parents=[FOLDER_ID_APPROVED],
            properties={"existing_prop": "existing_value"},
        )

        tagger.update_tags(file_to_tag)

        expected_properties = {
            "status": "APPROVED",
            "another_tag": "another_value",
            "existing_prop": "existing_value",
        }
        expected_body = {"properties": expected_properties}

        mock_drive_service.files.return_value.update.assert_called_once_with(
            fileId="file123", body=expected_body, fields="properties"
        )

    finally:
        # Clean up the dynamically added tag to not affect other tests
        from . import tags

        tags._TAGGERS.pop()


def test_update_tags_no_tags_defined(mock_drive_service, mock_docs_service):
    """Test behavior when no tags are defined (beyond the default status)."""
    # Temporarily clear taggers for this test
    from . import tags

    original_taggers = tags._TAGGERS
    tags._TAGGERS = []

    try:
        tagger = Tagger(mock_drive_service, mock_docs_service)
        file_to_tag = File(
            id="file123",
            name="test.pdf",
            parents=[FOLDER_ID_APPROVED],
        )
        tagger.update_tags(file_to_tag)
        mock_drive_service.files.return_value.update.assert_not_called()
    finally:
        tags._TAGGERS = original_taggers
