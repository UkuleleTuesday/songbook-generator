import json
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest
from google.api_core import exceptions as gcp_exceptions

from ..worker.models import File
from .tags import (
    FOLDER_ID_APPROVED,
    FOLDER_ID_READY_TO_PLAY,
    GCS_TAG_PREFIX,
    Tagger,
    status,
    tag,
    Context,
    SongSheetGoogleDocument,
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
    mock_drive_service.files.return_value.get.return_value.execute.return_value = {}
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
            "song",
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
            "song",
            "Space Oddity",
        ),
        (
            "space_oddity.json",
            "artist",
            "David Bowie",
        ),
        (
            "mustang_sally.json",
            "song",
            "Kiss/Mustang Sally Medley",
        ),
        (
            "mustang_sally.json",
            "artist",
            "Prince/The Commitments",
        ),
        (
            "final_countdown.json",
            "song",
            "The Final Countdown",
        ),
        (
            "final_countdown.json",
            "artist",
            "Europe",
        ),
        (
            "we_are_young.json",
            "song",
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
            "F,Dm,Gm,Bb,C,Am,Csus4",
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
            "song",
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
            "swing",
        ),
    ],
    indirect=["doc_json"],  # Tells pytest to pass the param to the fixture
)
def test_tagger_functions(doc_json, tag_func, expected_value):
    """Test tagger functions using real JSON fixtures."""
    from . import tags

    # Dynamically get the tagger function by name
    func = getattr(tags, tag_func)
    doc = SongSheetGoogleDocument(json=doc_json)
    context = Context(file=Mock(), document=doc)
    assert func(context) == expected_value


def test_update_tags_no_update_if_tag_returns_none(
    mock_drive_service, mock_docs_service
):
    """Test that no update is made if the tag function returns None."""
    mock_drive_service.files.return_value.get.return_value.execute.return_value = {}
    tagger = Tagger(mock_drive_service, mock_docs_service)
    file_to_tag = File(id="file123", name="test.pdf", parents=["other_folder"])

    tagger.update_tags(file_to_tag)

    mock_drive_service.files.return_value.update.assert_not_called()


def test_update_tags_no_update_if_tags_are_identical(
    mock_drive_service, mock_docs_service
):
    """Test that no update is made if the generated tags match existing ones."""
    mock_drive_service.files.return_value.get.return_value.execute.return_value = {}
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
    mock_drive_service.files.return_value.get.return_value.execute.return_value = {
        "owners": [{"displayName": "Test Owner"}]
    }

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
            "tabber": "Test owner",
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


def test_only_if_unset_does_not_update_existing_tag(
    mock_drive_service, mock_docs_service
):
    """Test that a tag with only_if_unset=True is not updated if it exists."""
    mock_drive_service.files.return_value.get.return_value.execute.return_value = {}

    @tag(only_if_unset=True)
    def tag_if_unset(ctx: Context) -> str:
        return "new_value"  # This value should not be set

    @tag
    def always_tag(ctx: Context) -> str:
        return "always_value"

    try:
        tagger = Tagger(mock_drive_service, mock_docs_service)
        file_with_prop = File(
            id="file1",
            name="test.pdf",
            properties={
                "tag_if_unset": "existing_value",
                "existing_prop": "existing_value",
            },
        )
        tagger.update_tags(file_with_prop)

        expected_properties = {
            "tag_if_unset": "existing_value",  # Should remain unchanged
            "always_tag": "always_value",  # Should be added
            "existing_prop": "existing_value",
        }
        expected_body = {"properties": expected_properties}
        mock_drive_service.files.return_value.update.assert_called_once_with(
            fileId="file1", body=expected_body, fields="properties"
        )

    finally:
        from . import tags

        tags._TAGGERS.pop()
        tags._TAGGERS.pop()


def test_only_if_unset_sets_new_tag(mock_drive_service, mock_docs_service):
    """Test that a tag with only_if_unset=True is set if it does not exist."""
    mock_drive_service.files.return_value.get.return_value.execute.return_value = {}

    @tag(only_if_unset=True)
    def tag_if_unset(ctx: Context) -> str:
        return "new_value"

    @tag
    def always_tag(ctx: Context) -> str:
        return "always_value"

    try:
        tagger = Tagger(mock_drive_service, mock_docs_service)
        file_without_prop = File(
            id="file2", name="test.pdf", properties={"existing_prop": "existing_value"}
        )
        tagger.update_tags(file_without_prop)

        expected_properties = {
            "tag_if_unset": "new_value",  # Should be set
            "always_tag": "always_value",  # Should be set
            "existing_prop": "existing_value",
        }
        expected_body = {"properties": expected_properties}
        mock_drive_service.files.return_value.update.assert_called_once_with(
            fileId="file2", body=expected_body, fields="properties"
        )

    finally:
        from . import tags

        tags._TAGGERS.pop()
        tags._TAGGERS.pop()


def test_update_tags_no_tags_defined(mock_drive_service, mock_docs_service):
    """Test behavior when no tags are defined (beyond the default status)."""
    mock_drive_service.files.return_value.get.return_value.execute.return_value = {}
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


# ---------------------------------------------------------------------------
# GCS metadata write tests
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_cache_bucket():
    """Create a mock GCS bucket object."""
    return MagicMock()


def _make_tagger_with_bucket(mock_drive_service, mock_docs_service, mock_cache_bucket):
    """Return a Tagger wired up with all three mock dependencies.

    Used by GCS-write tests to avoid repeating the constructor call.
    Returns a :class:`Tagger` instance with ``cache_bucket`` set.
    """
    return Tagger(mock_drive_service, mock_docs_service, cache_bucket=mock_cache_bucket)


def test_update_tags_writes_to_gcs_when_bucket_provided(
    mock_drive_service, mock_docs_service, mock_cache_bucket
):
    """When a cache_bucket is provided, tags should be written to GCS metadata."""
    mock_drive_service.files.return_value.get.return_value.execute.return_value = {}
    mock_blob = MagicMock()
    mock_blob.metadata = {}
    mock_cache_bucket.blob.return_value = mock_blob

    tagger = _make_tagger_with_bucket(
        mock_drive_service, mock_docs_service, mock_cache_bucket
    )
    file_to_tag = File(
        id="file123",
        name="test.pdf",
        parents=[FOLDER_ID_APPROVED],
    )
    tagger.update_tags(file_to_tag)

    # Drive update should still happen (backwards compat)
    mock_drive_service.files.return_value.update.assert_called_once()

    # GCS blob should be fetched and patched
    mock_cache_bucket.blob.assert_called_once_with("song-sheets/file123.pdf")
    mock_blob.reload.assert_called_once()
    mock_blob.patch.assert_called_once()

    # Confirm tag- prefix on GCS metadata key
    assert mock_blob.metadata.get(f"{GCS_TAG_PREFIX}status") == "APPROVED"


def test_update_tags_no_gcs_write_without_bucket(mock_drive_service, mock_docs_service):
    """When no cache_bucket is provided, no GCS calls should be made."""
    mock_drive_service.files.return_value.get.return_value.execute.return_value = {}
    tagger = Tagger(mock_drive_service, mock_docs_service)  # no cache_bucket
    file_to_tag = File(
        id="file123",
        name="test.pdf",
        parents=[FOLDER_ID_APPROVED],
    )
    tagger.update_tags(file_to_tag)
    # Drive update should still happen
    mock_drive_service.files.return_value.update.assert_called_once()


def test_update_tags_gcs_blob_not_found_does_not_raise(
    mock_drive_service, mock_docs_service, mock_cache_bucket
):
    """A missing GCS blob should be silently skipped (blob not cached yet)."""
    mock_drive_service.files.return_value.get.return_value.execute.return_value = {}
    mock_blob = MagicMock()
    mock_blob.reload.side_effect = gcp_exceptions.NotFound("not found")
    mock_cache_bucket.blob.return_value = mock_blob

    tagger = _make_tagger_with_bucket(
        mock_drive_service, mock_docs_service, mock_cache_bucket
    )
    file_to_tag = File(
        id="file123",
        name="test.pdf",
        parents=[FOLDER_ID_APPROVED],
    )
    # Should not raise
    tagger.update_tags(file_to_tag)

    # Drive update should still succeed
    mock_drive_service.files.return_value.update.assert_called_once()
    # GCS patch should NOT have been called
    mock_blob.patch.assert_not_called()


def test_update_tags_gcs_api_error_does_not_raise(
    mock_drive_service, mock_docs_service, mock_cache_bucket
):
    """A GCS API error during patch should be logged but not re-raised."""
    mock_drive_service.files.return_value.get.return_value.execute.return_value = {}
    mock_blob = MagicMock()
    mock_blob.metadata = {}
    mock_blob.patch.side_effect = gcp_exceptions.GoogleAPICallError("gcs error")
    mock_cache_bucket.blob.return_value = mock_blob

    tagger = _make_tagger_with_bucket(
        mock_drive_service, mock_docs_service, mock_cache_bucket
    )
    file_to_tag = File(
        id="file123",
        name="test.pdf",
        parents=[FOLDER_ID_APPROVED],
    )
    # Should not raise
    tagger.update_tags(file_to_tag)

    # Drive update should still have been called
    mock_drive_service.files.return_value.update.assert_called_once()


def test_update_tags_gcs_metadata_unchanged_skips_patch(
    mock_drive_service, mock_docs_service, mock_cache_bucket
):
    """When GCS metadata already contains the correct tags, no patch is needed."""
    mock_drive_service.files.return_value.get.return_value.execute.return_value = {}
    mock_blob = MagicMock()
    # Blob already has the tag we would write
    mock_blob.metadata = {f"{GCS_TAG_PREFIX}status": "APPROVED"}
    mock_cache_bucket.blob.return_value = mock_blob

    # File already has the tag too, so Drive update is also skipped
    tagger = _make_tagger_with_bucket(
        mock_drive_service, mock_docs_service, mock_cache_bucket
    )
    file_to_tag = File(
        id="file123",
        name="test.pdf",
        parents=[FOLDER_ID_APPROVED],
        properties={"status": "APPROVED"},
    )
    tagger.update_tags(file_to_tag)

    # Neither Drive nor GCS should be patched
    mock_drive_service.files.return_value.update.assert_not_called()
    mock_blob.patch.assert_not_called()
