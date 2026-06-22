import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from ..worker.models import File
from .tags import (
    FOLDER_ID_APPROVED,
    FOLDER_ID_READY_TO_PLAY,
    THEME_VALUES,
    Tagger,
    _GENRE_ALIASES,
    _LLM_TAGGERS,
    _parse_duration,
    _run_llm_tags,
    approved_date,
    country,
    duration,
    genre,
    ready_to_play_date,
    split_specialbooks,
    status,
    tag,
    theme,
    year,
    Context,
    LlmTaggerConfig,
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


@patch("generator.tagupdater.tags._now_iso", return_value="2026-03-25T11:00:00Z")
def test_update_tags_with_status_tag(mock_now, mock_drive_service, mock_docs_service):
    """Test Tagger.update_tags with the status tag."""
    mock_drive_service.files.return_value.get.return_value.execute.return_value = {}
    tagger = Tagger(mock_drive_service, mock_docs_service)
    file_to_tag = File(
        id="file123",
        name="test.pdf",
        parents=[FOLDER_ID_APPROVED],
    )

    tagger.update_tags(file_to_tag)

    expected_body = {
        "properties": {"status": "APPROVED", "approved_date": "2026-03-25T11:00:00Z"}
    }
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
        properties={"status": "APPROVED", "approved_date": "2026-03-25T11:00:00Z"},
    )

    tagger.update_tags(file_to_tag)

    mock_drive_service.files.return_value.update.assert_not_called()


@patch("generator.tagupdater.tags._now_iso", return_value="2026-03-25T11:00:00Z")
def test_update_tags_with_multiple_tags_and_preserves_existing(
    mock_now, mock_drive_service, mock_docs_service
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
            "approved_date": "2026-03-25T11:00:00Z",
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


def test_trigger_field_skips_write_when_field_unchanged(
    mock_drive_service, mock_docs_service
):
    """Test that no write occurs when trigger_field value is unchanged."""
    mock_drive_service.files.return_value.get.return_value.execute.return_value = {}
    tagger = Tagger(mock_drive_service, mock_docs_service, trigger_field="status")
    # status is already APPROVED, and parents still point to APPROVED folder
    file_to_tag = File(
        id="file123",
        name="test.pdf",
        parents=[FOLDER_ID_APPROVED],
        properties={"status": "APPROVED"},
    )

    tagger.update_tags(file_to_tag)

    mock_drive_service.files.return_value.update.assert_not_called()


def test_trigger_field_writes_when_field_changes(mock_drive_service, mock_docs_service):
    """Test that a write occurs when trigger_field value changes."""
    mock_drive_service.files.return_value.get.return_value.execute.return_value = {}
    tagger = Tagger(mock_drive_service, mock_docs_service, trigger_field="status")
    # status was READY_TO_PLAY, now file is in APPROVED folder
    file_to_tag = File(
        id="file123",
        name="test.pdf",
        parents=[FOLDER_ID_APPROVED],
        properties={"status": "READY_TO_PLAY"},
    )

    tagger.update_tags(file_to_tag)

    mock_drive_service.files.return_value.update.assert_called_once()


def test_trigger_field_writes_when_field_goes_from_absent_to_set(
    mock_drive_service, mock_docs_service
):
    """Test that a missing trigger field value counts as a change when set."""
    mock_drive_service.files.return_value.get.return_value.execute.return_value = {}
    tagger = Tagger(mock_drive_service, mock_docs_service, trigger_field="status")
    # status not yet set, file is in APPROVED folder
    file_to_tag = File(
        id="file123",
        name="test.pdf",
        parents=[FOLDER_ID_APPROVED],
        properties={},
    )

    tagger.update_tags(file_to_tag)

    mock_drive_service.files.return_value.update.assert_called_once()


def test_trigger_field_skips_write_even_when_other_properties_change(
    mock_drive_service, mock_docs_service
):
    """Test that other property changes don't trigger a write when trigger_field is set and unchanged."""
    mock_drive_service.files.return_value.get.return_value.execute.return_value = {
        "owners": [{"displayName": "Test Owner"}]
    }

    @tag
    def extra_tag(ctx: Context) -> str:
        return "new_value"

    try:
        tagger = Tagger(mock_drive_service, mock_docs_service, trigger_field="status")
        # status is already APPROVED (unchanged), but extra_tag is new
        file_to_tag = File(
            id="file123",
            name="test.pdf",
            parents=[FOLDER_ID_APPROVED],
            properties={"status": "APPROVED"},
        )

        tagger.update_tags(file_to_tag)

        mock_drive_service.files.return_value.update.assert_not_called()
    finally:
        from . import tags

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


@patch("generator.tagupdater.tags._now_iso", return_value="2026-03-25T11:00:00Z")
def test_ready_to_play_date_set_when_in_ready_to_play_folder(mock_now):
    """ready_to_play_date is returned when file is in the ready to play folder."""
    file = File(id="1", name="f", parents=[FOLDER_ID_READY_TO_PLAY])
    assert ready_to_play_date(Context(file=file)) == "2026-03-25T11:00:00Z"


def test_ready_to_play_date_not_set_for_other_folder():
    """ready_to_play_date returns None when file is not in the ready to play folder."""
    file = File(id="1", name="f", parents=[FOLDER_ID_APPROVED])
    assert ready_to_play_date(Context(file=file)) is None


@patch("generator.tagupdater.tags._now_iso", return_value="2026-03-25T11:00:00Z")
def test_approved_date_set_when_in_approved_folder(mock_now):
    """approved_date is returned when file is in the approved folder."""
    file = File(id="1", name="f", parents=[FOLDER_ID_APPROVED])
    assert approved_date(Context(file=file)) == "2026-03-25T11:00:00Z"


def test_approved_date_not_set_for_other_folder():
    """approved_date returns None when file is not in the approved folder."""
    file = File(id="1", name="f", parents=[FOLDER_ID_READY_TO_PLAY])
    assert approved_date(Context(file=file)) is None


@patch("generator.tagupdater.tags._now_iso", return_value="2026-03-25T11:00:00Z")
def test_status_date_not_overwritten_once_set(
    mock_now, mock_drive_service, mock_docs_service
):
    """ready_to_play_date and approved_date are not overwritten if already set."""
    mock_drive_service.files.return_value.get.return_value.execute.return_value = {}
    tagger = Tagger(mock_drive_service, mock_docs_service, trigger_field="status")
    file_to_tag = File(
        id="file123",
        name="test.pdf",
        parents=[FOLDER_ID_APPROVED],
        properties={
            "status": "READY_TO_PLAY",
            "approved_date": "2025-01-01T00:00:00Z",
        },
    )

    tagger.update_tags(file_to_tag)

    call_body = mock_drive_service.files.return_value.update.call_args[1]["body"]
    assert call_body["properties"]["approved_date"] == "2025-01-01T00:00:00Z"


# --- year validator tests ---


def _make_ctx() -> Context:
    file = File(
        id="1",
        name="Psycho Killer - Talking Heads",
        properties={"song": "Psycho Killer", "artist": "Talking Heads"},
    )
    return Context(file=file)


def test_year_returns_valid_year():
    assert year(_make_ctx(), "1977") == "1977"


def test_year_returns_none_for_none_raw():
    assert year(_make_ctx(), None) is None


@pytest.mark.parametrize(
    "raw",
    [
        "The song was released in 1977.",
        "circa 1970s",
        "unknown",
        "N/A",
        "",
        "   ",
        "19777",
        "77",
        "abcd",
    ],
)
def test_year_rejects_garbage(raw):
    assert year(_make_ctx(), raw) is None


# --- duration validator tests ---


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("3:45", "00:03:45"),
        ("0:30", "00:00:30"),
        ("65:00", "01:05:00"),
        (None, None),
        ("", None),
        ("not a duration", None),
        ("1:60", None),  # invalid seconds
    ],
)
def test_duration_validator(raw, expected):
    assert duration(_make_ctx(), raw) == expected


# --- _run_llm_tags tests ---


def _make_genai_client(response_json: str) -> Mock:
    client = Mock()
    client.models.generate_content.return_value.text = response_json
    return client


def test_run_llm_tags_returns_empty_without_client():
    ctx = Context(file=File(id="1", name="test"), genai_client=None)
    year_config = LlmTaggerConfig(func=year, prompt="What year?")
    assert _run_llm_tags(ctx, [year_config]) == {}


def test_run_llm_tags_returns_empty_for_no_taggers():
    ctx = Context(file=File(id="1", name="test"), genai_client=_make_genai_client("{}"))
    assert _run_llm_tags(ctx, []) == {}


def test_run_llm_tags_batches_into_single_call():
    client = _make_genai_client('{"year": "1977", "duration": "03:45"}')
    file = File(
        id="1",
        name="test",
        properties={"song": "Psycho Killer", "artist": "Talking Heads"},
    )
    ctx = Context(file=file, genai_client=client)

    year_config = LlmTaggerConfig(
        func=year,
        prompt="What year?",
    )
    duration_config = LlmTaggerConfig(
        func=duration,
        prompt="What duration?",
    )

    results = _run_llm_tags(ctx, [year_config, duration_config])

    # Only one LLM call was made
    assert client.models.generate_content.call_count == 1
    assert results["year"] == "1977"
    assert results["duration"] == "00:03:45"


def test_run_llm_tags_handles_invalid_json():
    client = _make_genai_client("not valid json at all")
    ctx = Context(file=File(id="1", name="test"), genai_client=client)
    year_config = LlmTaggerConfig(func=year, prompt="What year?")

    results = _run_llm_tags(ctx, [year_config])

    assert results == {}


def test_run_llm_tags_strips_markdown_fences():
    client = _make_genai_client('```json\n{"year": "1984"}\n```')
    file = File(id="1", name="test", properties={"song": "1984", "artist": "Someone"})
    ctx = Context(file=file, genai_client=client)
    year_config = LlmTaggerConfig(func=year, prompt="What year?")

    results = _run_llm_tags(ctx, [year_config])

    assert results == {"year": "1984"}


def test_run_llm_tags_skips_null_values():
    client = _make_genai_client('{"year": null, "duration": "03:45"}')
    file = File(id="1", name="test", properties={"song": "test", "artist": "test"})
    ctx = Context(file=file, genai_client=client)

    year_config = LlmTaggerConfig(func=year, prompt="What year?")
    duration_config = LlmTaggerConfig(func=duration, prompt="What duration?")

    results = _run_llm_tags(ctx, [year_config, duration_config])

    assert "year" not in results
    assert results["duration"] == "00:03:45"


def test_run_llm_tags_skips_invalid_values():
    client = _make_genai_client('{"year": "not-a-year"}')
    ctx = Context(file=File(id="1", name="test"), genai_client=client)
    year_config = LlmTaggerConfig(func=year, prompt="What year?")

    results = _run_llm_tags(ctx, [year_config])

    assert results == {}


# --- _parse_duration tests ---


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("3:45", "00:03:45"),
        ("0:30", "00:00:30"),
        ("65:00", "01:05:00"),
        ("1:60", None),
        ("no time here", None),
    ],
)
def test_parse_duration(raw, expected):
    assert _parse_duration(raw) == expected


# --- genre validator tests ---


def test_genre_validator_respects_max_genres():
    assert genre(_make_ctx(), "Rock,Pop,Folk,Country", max_genres=2) == "rock,pop"


def test_run_llm_tags_passes_extra_to_validator():
    client = _make_genai_client('{"genre": "Rock,Pop,Folk,Jazz"}')
    file = File(id="1", name="test", properties={"song": "test", "artist": "test"})
    ctx = Context(file=file, genai_client=client)

    genre_config = LlmTaggerConfig(
        func=genre, prompt="What genres?", extra={"max_genres": 2}
    )
    results = _run_llm_tags(ctx, [genre_config])

    assert results == {"genre": "rock,pop"}


def test_run_llm_tags_interpolates_extra_in_prompt():
    client = _make_genai_client('{"genre": "Rock"}')
    file = File(id="1", name="test", properties={"song": "test", "artist": "test"})
    ctx = Context(file=file, genai_client=client)

    genre_config = LlmTaggerConfig(
        func=genre, prompt="List up to {max_genres} genres.", extra={"max_genres": 2}
    )
    _run_llm_tags(ctx, [genre_config])

    call_args = client.models.generate_content.call_args
    assert "List up to 2 genres." in call_args.kwargs["contents"]


@patch("generator.tagupdater.tags._now_iso", return_value="2026-03-25T11:00:00Z")
def test_dual_write_mirrors_properties_to_metadata_store(
    mock_now, mock_drive_service, mock_docs_service
):
    """When a metadata store is provided, the same properties are mirrored to it."""
    mock_drive_service.files.return_value.get.return_value.execute.return_value = {
        "name": "test.pdf"
    }
    metadata_store = Mock()
    tagger = Tagger(
        mock_drive_service, mock_docs_service, metadata_store=metadata_store
    )
    file_to_tag = File(id="file123", name="test.pdf", parents=[FOLDER_ID_APPROVED])

    tagger.update_tags(file_to_tag)

    # Drive remains the source of truth and is still written.
    mock_drive_service.files.return_value.update.assert_called_once()
    # The mirror receives the exact same updated properties.
    metadata_store.write.assert_called_once_with(
        "file123",
        {"status": "APPROVED", "approved_date": "2026-03-25T11:00:00Z"},
        name="test.pdf",
    )


def test_dual_write_not_attempted_when_no_drive_write(
    mock_drive_service, mock_docs_service
):
    """No mirror write happens when the Drive write is skipped (tags identical)."""
    mock_drive_service.files.return_value.get.return_value.execute.return_value = {}
    metadata_store = Mock()
    tagger = Tagger(
        mock_drive_service, mock_docs_service, metadata_store=metadata_store
    )
    # status already APPROVED and parents point to APPROVED -> identical, no write
    file_to_tag = File(
        id="file123",
        name="test.pdf",
        parents=[FOLDER_ID_APPROVED],
        properties={"status": "APPROVED", "approved_date": "2026-01-01T00:00:00Z"},
    )

    tagger.update_tags(file_to_tag)

    mock_drive_service.files.return_value.update.assert_not_called()
    metadata_store.write.assert_not_called()


def test_dual_write_failure_does_not_break_drive_write(
    mock_drive_service, mock_docs_service
):
    """A Firestore mirror failure must not propagate or block the Drive write."""
    mock_drive_service.files.return_value.get.return_value.execute.return_value = {
        "name": "test.pdf"
    }
    metadata_store = Mock()
    metadata_store.write.side_effect = RuntimeError("firestore unavailable")
    tagger = Tagger(
        mock_drive_service, mock_docs_service, metadata_store=metadata_store
    )
    file_to_tag = File(id="file123", name="test.pdf", parents=[FOLDER_ID_APPROVED])

    # Should not raise despite the mirror failing.
    tagger.update_tags(file_to_tag)

    mock_drive_service.files.return_value.update.assert_called_once()
    metadata_store.write.assert_called_once()


def test_dry_run_skips_both_drive_and_firestore_writes(
    mock_drive_service, mock_docs_service
):
    """dry_run is the master override: no writes to either sink."""
    mock_drive_service.files.return_value.get.return_value.execute.return_value = {
        "name": "test.pdf"
    }
    metadata_store = Mock()
    tagger = Tagger(
        mock_drive_service, mock_docs_service, metadata_store=metadata_store
    )
    file_to_tag = File(id="file123", name="test.pdf", parents=[FOLDER_ID_APPROVED])

    tagger.update_tags(file_to_tag, dry_run=True)

    mock_drive_service.files.return_value.update.assert_not_called()
    metadata_store.write.assert_not_called()


@patch("generator.tagupdater.tags._now_iso", return_value="2026-03-25T11:00:00Z")
def test_drive_write_disabled_writes_firestore_only(
    mock_now, mock_drive_service, mock_docs_service
):
    """With drive_write_enabled=False, only Firestore is written."""
    mock_drive_service.files.return_value.get.return_value.execute.return_value = {
        "name": "test.pdf"
    }
    metadata_store = Mock()
    tagger = Tagger(
        mock_drive_service,
        mock_docs_service,
        metadata_store=metadata_store,
        drive_write_enabled=False,
    )
    file_to_tag = File(id="file123", name="test.pdf", parents=[FOLDER_ID_APPROVED])

    tagger.update_tags(file_to_tag)

    mock_drive_service.files.return_value.update.assert_not_called()
    metadata_store.write.assert_called_once_with(
        "file123",
        {"status": "APPROVED", "approved_date": "2026-03-25T11:00:00Z"},
        name="test.pdf",
    )


# --- country / theme validator tests ---


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("ireland", "ireland"),
        ("Ireland", "ireland"),
        ("  france  ", "france"),
        ("puerto rico", "puerto rico"),
        ("usa", "united states"),  # canonicalized via pycountry
        ("uk", "united kingdom"),  # canonicalized via alias
        ("russia", "russian federation"),  # canonicalized via alias
        ("scotland", "scotland"),  # supported sub-national region
        ("brazil", "brazil"),  # any ISO-3166 country is accepted
        ("ireland,usa", "ireland,united states"),
        ("ireland,ireland", "ireland"),  # de-duplicated
        ("ireland,atlantis", "ireland"),  # unknown dropped
        ("atlantis", None),  # not a recognized country/region
        (None, None),
        ("", None),
        ("  ,  ", None),
    ],
)
def test_country_validator(raw, expected):
    assert country(_make_ctx(), raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("pride", "pride"),
        ("Pride", "pride"),
        ("christmas", "christmas"),
        ("pride,halloween", "pride,halloween"),
        ("pride,pride", "pride"),  # de-duplicated
        ("pride,birthday", "pride,birthday"),
        ("birthday", "birthday"),
        (None, None),
        ("", None),
    ],
)
def test_theme_validator(raw, expected):
    assert theme(_make_ctx(), raw) == expected


def _theme_tagger_config() -> LlmTaggerConfig:
    """Locate the registered theme @llm_tag config (with its real prompt/extra)."""
    for config in _LLM_TAGGERS:
        if config.func is theme:
            return config
    raise AssertionError("theme tagger is not registered in _LLM_TAGGERS")


def test_theme_prompt_defers_to_per_theme_criteria():
    """The theme prompt must not impose one shared basis, and must surface the
    pride artist-identity criterion so artist-qualified songs (e.g. Dusty
    Springfield, Kylie) can be tagged. Pins the assembled prompt, not model output.
    """
    client = _make_genai_client('{"theme": "pride"}')
    file = File(
        id="1",
        name="test",
        properties={
            "song": "I Only Want To Be With You",
            "artist": "Dusty Springfield",
        },
    )
    ctx = Context(file=file, genai_client=client)

    _run_llm_tags(ctx, [_theme_tagger_config()])

    compound_prompt = client.models.generate_content.call_args.kwargs["contents"]
    # The old generic framing forced a lyrics-only judgement; it must be gone.
    assert "based on its lyrics or subject matter" not in compound_prompt
    # The pride artist-identity criterion (from THEME_VALUES) must reach the model.
    assert "publicly identifies as LGBTQ+" in compound_prompt
    assert THEME_VALUES["pride"] in compound_prompt


# --- split_specialbooks tests ---


@pytest.mark.parametrize(
    "specialbooks,expected_country,expected_theme,expected_unknown",
    [
        ("ireland", "ireland", None, []),
        ("pride", None, "pride", []),
        ("pride,ireland,regular", "ireland", "pride", []),
        ("pride,halloween", None, "pride,halloween", []),
        ("scottish", "scotland", None, []),  # alias normalization
        ("pride.uk", None, "pride", []),  # alias normalization
        ("xmas", None, "christmas", []),  # legacy xmas -> christmas
        ("womens-2026,hooley-2025,can2025,nocan2025,womens", None, None, []),  # dropped
        (
            "USA, UK",
            "united states,united kingdom",
            None,
            [],
        ),  # canonicalized + whitespace
        ("ireland,ireland", "ireland", None, []),  # de-duplicated
        ("new", None, None, ["new"]),  # unknown leftover surfaced
        ("", None, None, []),
        (None, None, None, []),
    ],
)
def test_split_specialbooks(
    specialbooks, expected_country, expected_theme, expected_unknown
):
    assert split_specialbooks(specialbooks) == (
        expected_country,
        expected_theme,
        expected_unknown,
    )


# --- genre validator tests ---


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("rock", "rock"),
        ("Rock", "rock"),
        ("  pop , rock  ", "pop,rock"),
        # alias: spaced → hyphenated
        ("pop punk", "pop-punk"),
        ("dance pop", "dance-pop"),
        ("folk rock", "folk-rock"),
        ("alternative rock", "alternative-rock"),
        # alias: symbols
        ("rock & roll", "rock-and-roll"),
        ("rock 'n' roll", "rock-and-roll"),
        ("rock and roll", "rock-and-roll"),
        # blanket space→hyphen normalization
        ("hip hop", "hip-hop"),
        ("heavy metal", "heavy-metal"),
        ("adult contemporary", "adult-contemporary"),
        ("funk / soul", "funk-soul"),
        ("brass & military", "brass-military"),
        # alias: near-synonym
        ("christmas music", "christmas"),
        # deduplication
        ("rock,rock,pop", "rock,pop"),
        (
            "pop punk,pop-punk",
            "pop-punk",
        ),  # first entry normalized, second already canonical, deduped
        # max 3
        ("a,b,c,d", "a,b,c"),
        (None, None),
        ("", None),
    ],
)
def test_genre_validator(raw, expected):
    assert genre(_make_ctx(), raw) == expected


def test_genre_aliases_are_valid():
    for k, v in _GENRE_ALIASES.items():
        assert k == k.lower(), f"alias key {k!r} is not lowercase"
        assert v == v.lower(), f"alias value {v!r} is not lowercase"
