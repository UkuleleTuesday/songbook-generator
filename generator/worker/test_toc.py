import pytest
from unittest.mock import MagicMock
import fitz
from .toc import (
    TocGenerator,
    difficulty_symbol,
)
from .models import File
from . import toc
from ..common.config import TocPostfix
from ..common.filters import PropertyFilter


@pytest.mark.parametrize(
    "difficulty_bin,expected_symbol",
    [
        (0, ""),  # Bin 0 is for invalid/no difficulty
        (1, "○"),
        (2, "◔"),
        (3, "◑"),
        (4, "◕"),
        (5, "●"),
        (6, ""),  # Out of range should return no symbol
        (-1, ""),  # Out of range should return no symbol
    ],
)
def test_difficulty_symbol(difficulty_bin, expected_symbol):
    """Test that difficulty_symbol returns the correct symbol for a given bin."""
    assert difficulty_symbol(difficulty_bin) == expected_symbol


@pytest.fixture
def toc_generator_for_title_tests(mocker):
    """Provides a basic TocGenerator for testing the title generation method."""
    mock_config = toc.Toc(max_toc_entry_length=50)
    mocker.patch("generator.worker.toc.resolve_font")
    return TocGenerator(config=mock_config)


def test_generate_toc_title_empty_string(toc_generator_for_title_tests):
    """Test with empty string."""
    title = ""
    result = toc_generator_for_title_tests._generate_toc_title(title, max_length=60)
    assert result == ""


def test_generate_toc_title_empty_string_ready_to_play(toc_generator_for_title_tests):
    """Test with empty string that is ready to play."""
    title = ""
    result = toc_generator_for_title_tests._generate_toc_title(
        title, max_length=60, is_ready_to_play=True
    )
    assert result == "*"


def test_generate_toc_title_very_short_max_length(toc_generator_for_title_tests):
    """Test with very short max length."""
    title = "Long Title"
    result = toc_generator_for_title_tests._generate_toc_title(title, max_length=3)
    assert len(result) == 3


# Sample of real titles from current-toc.txt with expected behavior
@pytest.mark.parametrize(
    "original_title,expected_title",
    [
        # Simple titles that should remain unchanged
        ("Hey Jude - The Beatles", "Hey Jude - The Beatles"),
        ("Imagine - John Lennon", "Imagine - John Lennon"),
        ("Jolene - Dolly Parton", "Jolene - Dolly Parton"),
        # Titles with version or edit information that should be removed
        ("Back for Good (Radio Mix) - Take That", "Back for Good - Take That"),
        ("Freedom! '90 (Edit) - George Michael", "Freedom! '90 - George Michael"),
        # Titles with parentheses that are part of the song name (should be preserved) but also stuff that needs cleaning up
        (
            "(Don't Fear) The Reaper (Single Version) - Blue Öyster Cult",
            "(Don't Fear) The Reaper - Blue Öyster Cult",
        ),
        (
            "(You're the) Devil in Disguise - Elvis Presley",
            "(You're the) Devil in Disguise - Elvis Presley",
        ),
        (
            "Build Me Up Buttercup (Mono) - The Foundations",
            "Build Me Up Buttercup - The Foundations",
        ),
        (
            "Everybody (Backstreet's Back) (Radio Edit) - Backstreet Boys",
            "Everybody (Backstreet's Back) - Backstreet Boys",
        ),
        # Titles with feat./featuring
        (
            "Get Lucky (Radio Edit) [feat. Pharrell Williams, Nile Rodgers] - Daft Punk",
            "Get Lucky - Daft Punk",
        ),
        (
            "Valerie (feat. Amy Winehouse) (Version Revisited) - Mark Ronson",
            "Valerie - Mark Ronson",
        ),
        # Titles with numbers
        ("9 to 5 - Dolly Parton", "9 to 5 - Dolly Parton"),
        ("99 Luftballons - Nena", "99 Luftballons - Nena"),
        # Should be preserved as they are
        (
            "Happy Birthday To You (in D) - Traditional",
            "Happy Birthday To You (in D) - Traditional",
        ),
        (
            "La Marseillaise (abridged) - Rouget de Lisle",
            "La Marseillaise (abridged) - Rouget de Lisle",
        ),
        # Should be truncated
        (
            "Lava - Kuana Torres Kahele, Napua Greig, James Ford Murphy",
            "Lava - Kuana Torres Kahele, Napua Greig, James...",
        ),
    ],
)
def test_generate_toc_title_real_world_samples(
    toc_generator_for_title_tests, original_title, expected_title
):
    """Test generate_toc_title with real titles from the TOC."""
    # Test with default max_length
    result = toc_generator_for_title_tests._generate_toc_title(
        original_title, max_length=50
    )
    assert result == expected_title


@pytest.fixture
def mock_toc_generator(mocker):
    """Provides a TocGenerator with mocked fonts and config."""
    mock_config = toc.Toc(
        max_toc_entry_length=60,
        text_fontsize=10.0,
        column_width=250,
    )

    mock_resolve_font = mocker.patch("generator.worker.toc.resolve_font")

    mock_font = MagicMock()
    mock_font.text_length.side_effect = lambda text, fontsize: len(text) * 5
    mock_resolve_font.return_value = mock_font

    generator = TocGenerator(config=mock_config)
    return generator


PAGE_RECT = fitz.Rect(0, 0, 595, 842)


def _writers(mock_tw):
    """Helper: writers dict with mock as the default (None-color) writer."""
    return {None: mock_tw}


def test_add_toc_entry(mock_toc_generator):
    """Test that _add_toc_entry correctly formats and adds a TOC entry."""
    generator = mock_toc_generator
    mock_tw = MagicMock(spec=fitz.TextWriter)

    generator._add_toc_entry(
        writers=_writers(mock_tw),
        page_rect=PAGE_RECT,
        file_index=0,
        page_offset=0,
        file=File(id="1", name="A Short Title - Artist"),
        x_start=25,
        y_pos=70,
        current_page_index=0,
    )

    # Check that append is called multiple times (for title, page number, dots)
    assert mock_tw.append.call_count > 1
    calls = mock_tw.append.call_args_list

    # Check title call
    title_call = calls[0]
    assert title_call.args[1] == "A Short Title - Artist"
    assert title_call.kwargs["font"] == generator.text_font

    # Check page number call (page number font)
    page_num_call = calls[1]
    assert page_num_call.args[1] == "1"
    assert page_num_call.kwargs["font"] == generator.page_number_font

    # Check dots call
    dots_call = calls[2]
    assert dots_call.args[1].startswith(".")
    assert dots_call.kwargs["font"] == generator.text_font


def test_add_toc_entry_title_truncation(mock_toc_generator):
    """Test that a long title is truncated correctly."""
    generator = mock_toc_generator
    mock_tw = MagicMock(spec=fitz.TextWriter)

    long_title = "This is a very long song title that will definitely need to be truncated - The Long Winded Singers"
    generator.config.max_toc_entry_length = 50
    generator._add_toc_entry(
        writers=_writers(mock_tw),
        page_rect=PAGE_RECT,
        file_index=0,
        page_offset=0,
        file=File(id="1", name=long_title),
        x_start=25,
        y_pos=70,
        current_page_index=0,
    )

    # Check that the appended title is shorter than the original and ends with "..."
    appended_title = mock_tw.append.call_args_list[0].args[1]
    assert len(appended_title) < len(long_title)
    assert appended_title.endswith("...")


def test_add_toc_entry_with_difficulty(mock_toc_generator):
    """Test that a difficulty symbol is added to the TOC entry."""
    generator = mock_toc_generator
    mock_tw = MagicMock(spec=fitz.TextWriter)

    file_with_difficulty = File(
        id="1", name="Medium Song", properties={"difficulty_bin": "3"}
    )

    generator._add_toc_entry(
        writers=_writers(mock_tw),
        page_rect=PAGE_RECT,
        file_index=0,
        page_offset=0,
        file=file_with_difficulty,
        x_start=25,
        y_pos=70,
        current_page_index=0,
    )

    # Check that title is appended with the correct symbol
    appended_title = mock_tw.append.call_args_list[0].args[1]
    assert appended_title.startswith("◑ ")
    assert "Medium Song" in appended_title


def test_generate_toc_title_truncation_with_ready_to_play(
    toc_generator_for_title_tests,
):
    """Test that a long title is truncated and still gets a '*'."""
    long_title = "This is a very long song title that will definitely need to be truncated to see the effect"
    generator = toc_generator_for_title_tests
    generator.config.include_wip_marker = True  # Explicitly set for test clarity
    result = generator._generate_toc_title(
        long_title, max_length=50, is_ready_to_play=True
    )
    assert result.endswith("...*")
    assert len(result) < len(long_title)


def test_add_toc_entry_ready_to_play_status(mock_toc_generator):
    """Test that a '*' is added for READY_TO_PLAY status."""
    generator = mock_toc_generator
    generator.config.include_wip_marker = True
    mock_tw = MagicMock(spec=fitz.TextWriter)

    file = File(id="1", name="Ready Song", properties={"status": "READY_TO_PLAY"})

    generator._add_toc_entry(
        writers=_writers(mock_tw),
        page_rect=PAGE_RECT,
        file_index=0,
        page_offset=0,
        file=file,
        x_start=25,
        y_pos=70,
        current_page_index=0,
    )

    # Check that title is appended with the '*'
    appended_title = mock_tw.append.call_args_list[0].args[1]
    assert "Ready Song*" in appended_title


def test_add_toc_entry_with_postfix(mock_toc_generator, mocker):
    """Test that a postfix is added to the TOC entry when filters match."""
    generator = mock_toc_generator
    mock_tw = MagicMock(spec=fitz.TextWriter)

    # Mock filter logic
    mock_filter = mocker.MagicMock(spec=PropertyFilter)
    mock_filter.matches.return_value = True
    postfix_config = TocPostfix(postfix=" 🎃", filters=[mock_filter])
    generator.config.postfixes = [postfix_config]

    file = File(id="1", name="Monster Mash", properties={"tags": "halloween"})

    generator._add_toc_entry(
        writers=_writers(mock_tw),
        page_rect=PAGE_RECT,
        file_index=0,
        page_offset=0,
        file=file,
        x_start=25,
        y_pos=70,
        current_page_index=0,
    )

    appended_title = mock_tw.append.call_args_list[0].args[1]
    assert "Monster Mash 🎃" in appended_title


def test_add_toc_entry_with_postfix_no_match(mock_toc_generator, mocker):
    """Test that a postfix is NOT added to the TOC entry if filters don't match."""
    generator = mock_toc_generator
    mock_tw = MagicMock(spec=fitz.TextWriter)

    # Mock filter logic
    mock_filter = mocker.MagicMock(spec=PropertyFilter)
    mock_filter.matches.return_value = False
    postfix_config = TocPostfix(postfix=" 🎃", filters=[mock_filter])
    generator.config.postfixes = [postfix_config]

    file = File(id="1", name="Jingle Bells", properties={"tags": "christmas"})

    generator._add_toc_entry(
        writers=_writers(mock_tw),
        page_rect=PAGE_RECT,
        file_index=0,
        page_offset=0,
        file=file,
        x_start=25,
        y_pos=70,
        current_page_index=0,
    )

    appended_title = mock_tw.append.call_args_list[0].args[1]
    assert "Jingle Bells" in appended_title
    assert "🎃" not in appended_title


def test_add_toc_entry_ready_to_play_status_marker_disabled(mock_toc_generator):
    """Test that a '*' is NOT added for READY_TO_PLAY if setting is false."""
    generator = mock_toc_generator
    generator.config.include_wip_marker = False
    mock_tw = MagicMock(spec=fitz.TextWriter)

    file = File(id="1", name="Ready Song", properties={"status": "READY_TO_PLAY"})

    generator._add_toc_entry(
        writers=_writers(mock_tw),
        page_rect=PAGE_RECT,
        file_index=0,
        page_offset=0,
        file=file,
        x_start=25,
        y_pos=70,
        current_page_index=0,
    )

    # Check that title is appended without the '*'
    appended_title = mock_tw.append.call_args_list[0].args[1]
    assert appended_title == "Ready Song"


def test_add_toc_entry_postfix_filter_matches_on_name(mock_toc_generator):
    """Test that postfix filters can match on the file name (not just properties)."""
    generator = mock_toc_generator
    mock_tw = MagicMock(spec=fitz.TextWriter)

    name_filter = PropertyFilter(key="name", operator="in", value=["Confirmed Song"])
    postfix_config = TocPostfix(
        postfix=" ✓", filters=[name_filter], color=(0.6, 0.6, 0.6)
    )
    generator.config.postfixes = [postfix_config]

    # Confirmed song: routes to a dedicated color writer, not mock_tw
    writers = _writers(mock_tw)
    generator._add_toc_entry(
        writers,
        PAGE_RECT,
        0,
        0,
        File(id="1", name="Confirmed Song", properties={}),
        25,
        70,
        0,
    )
    assert (0.6, 0.6, 0.6) in writers
    mock_tw.append.assert_not_called()

    # Candidate song: routes to the default writer
    writers2 = _writers(mock_tw)
    generator._add_toc_entry(
        writers2,
        PAGE_RECT,
        1,
        0,
        File(id="2", name="Candidate Song", properties={}),
        25,
        70,
        0,
    )
    assert (0.6, 0.6, 0.6) not in writers2
    assert " ✓" not in mock_tw.append.call_args_list[0].args[1]


def test_add_toc_entry_with_postfix_color(mock_toc_generator, mocker):
    """Test that a matching postfix color routes the entry to a dedicated writer."""
    generator = mock_toc_generator
    mock_tw = MagicMock(spec=fitz.TextWriter)

    mock_filter = mocker.MagicMock(spec=PropertyFilter)
    mock_filter.matches.return_value = True
    postfix_config = TocPostfix(
        postfix=" ✓", filters=[mock_filter], color=(0.6, 0.6, 0.6)
    )
    generator.config.postfixes = [postfix_config]

    writers = _writers(mock_tw)
    generator._add_toc_entry(
        writers,
        PAGE_RECT,
        0,
        0,
        File(id="1", name="Confirmed Song", properties={}),
        25,
        70,
        0,
    )

    # A separate writer keyed by color was created
    assert (0.6, 0.6, 0.6) in writers
    # The default writer was not used for this colored entry
    mock_tw.append.assert_not_called()


def test_add_toc_entry_no_color_when_postfix_unmatched(mock_toc_generator, mocker):
    """Test that an unmatched entry uses the default writer (no color routing)."""
    generator = mock_toc_generator
    mock_tw = MagicMock(spec=fitz.TextWriter)

    mock_filter = mocker.MagicMock(spec=PropertyFilter)
    mock_filter.matches.return_value = False
    postfix_config = TocPostfix(
        postfix=" ✓", filters=[mock_filter], color=(0.6, 0.6, 0.6)
    )
    generator.config.postfixes = [postfix_config]

    writers = _writers(mock_tw)
    generator._add_toc_entry(
        writers,
        PAGE_RECT,
        0,
        0,
        File(id="1", name="Candidate Song", properties={}),
        25,
        70,
        0,
    )

    # No color writer created; only the default None key remains
    assert list(writers.keys()) == [None]
    mock_tw.append.assert_called()


def test_add_toc_entry_first_matched_color_wins(mock_toc_generator, mocker):
    """Test that when multiple postfixes match, only the first color's writer is used."""
    generator = mock_toc_generator
    mock_tw = MagicMock(spec=fitz.TextWriter)

    matching_filter = mocker.MagicMock(spec=PropertyFilter)
    matching_filter.matches.return_value = True

    postfix_first = TocPostfix(
        postfix=" ✓", filters=[matching_filter], color=(0.6, 0.6, 0.6)
    )
    postfix_second = TocPostfix(
        postfix=" 🌈", filters=[matching_filter], color=(1.0, 0.0, 0.5)
    )
    generator.config.postfixes = [postfix_first, postfix_second]

    writers = _writers(mock_tw)
    generator._add_toc_entry(
        writers,
        PAGE_RECT,
        0,
        0,
        File(id="1", name="Double Match", properties={}),
        25,
        70,
        0,
    )

    # Only the first matched color's writer should be created
    assert (0.6, 0.6, 0.6) in writers
    assert (1.0, 0.0, 0.5) not in writers
    # Default writer not used
    mock_tw.append.assert_not_called()


def test_build_table_of_contents_calls_assign_difficulty_bins(mocker):
    """Verify that assign_difficulty_bins is called."""
    mock_assign_bins = mocker.patch("generator.worker.toc.assign_difficulty_bins")
    mocker.patch("generator.worker.toc.get_settings")
    mocker.patch("generator.worker.toc.TocGenerator")

    files = [File(id="1", name="Song 1")]
    toc.build_table_of_contents(files)

    mock_assign_bins.assert_called_once_with(files)


def _toc_entry(target_page, toc_page_index, title, text="display"):
    """Build a TocEntry for outline tests (geometry is irrelevant here)."""
    return toc.TocEntry(
        page_number=target_page + 1,
        target_page=target_page,
        text=text,
        rect=fitz.Rect(0, 0, 10, 10),
        toc_page_index=toc_page_index,
        title=title,
    )


def test_add_toc_entry_stores_full_title_for_outline(mock_toc_generator):
    """The full, untruncated song name is kept for bookmarks even when the
    displayed TOC text is shortened."""
    generator = mock_toc_generator
    generator.config.max_toc_entry_length = 20
    mock_tw = MagicMock(spec=fitz.TextWriter)

    long_name = "A Really Quite Long Song Title - The Artist Band"
    generator._add_toc_entry(
        tw=mock_tw,
        file_index=3,
        page_offset=10,
        file=File(id="1", name=long_name),
        x_start=25,
        y_pos=70,
        current_page_index=0,
    )

    entry = generator.get_toc_entries()[-1]
    assert entry.title == long_name  # full title preserved
    assert len(entry.text) < len(long_name)  # displayed text truncated
    assert entry.target_page == 3
    assert entry.page_number == 14  # file_index + 1 + page_offset


def test_build_pdf_outline_page_math_and_titles():
    """Outline pages are 1-based and account for cover/preface + TOC pages."""
    entries = [
        _toc_entry(0, 0, "Song A - Artist"),
        _toc_entry(1, 0, "Song B - Artist"),
        _toc_entry(2, 1, ""),  # empty title falls back to display text
    ]
    entries[2].text = "Song C short"

    # toc_page_offset=2 (cover+preface), 2 distinct TOC pages -> songs start at
    # 0-based index 4, so 1-based pages 5, 6, 7.
    outline = toc.build_pdf_outline(entries, toc_page_offset=2)
    assert outline == [
        [1, "Song A - Artist", 5],
        [1, "Song B - Artist", 6],
        [1, "Song C short", 7],
    ]


def test_build_pdf_outline_skips_out_of_range_pages():
    entries = [_toc_entry(i, 0, f"Song {i}") for i in range(3)]
    # 1 TOC page, offset 2 -> 0-based targets 3, 4, 5. page_count=5 drops the last.
    outline = toc.build_pdf_outline(entries, toc_page_offset=2, page_count=5)
    assert [o[2] for o in outline] == [4, 5]


def test_build_pdf_outline_skips_empty_titles():
    entry = _toc_entry(0, 0, "", text="")
    assert toc.build_pdf_outline([entry], toc_page_offset=0) == []


def test_set_pdf_outline_sets_bookmarks_on_document():
    doc = fitz.open()
    for _ in range(8):
        doc.new_page()
    entries = [
        _toc_entry(0, 0, "Song A - Artist"),
        _toc_entry(1, 0, "Song B - Artist"),
    ]
    # offset 1 (cover) + 1 TOC page -> 0-based targets 2, 3 -> 1-based pages 3, 4.
    applied = toc.set_pdf_outline(doc, entries, toc_page_offset=1)
    expected = [[1, "Song A - Artist", 3], [1, "Song B - Artist", 4]]
    assert applied == expected
    assert doc.get_toc() == expected
    doc.close()


def test_set_pdf_outline_no_entries_is_noop():
    doc = fitz.open()
    doc.new_page()
    assert toc.set_pdf_outline(doc, [], toc_page_offset=0) == []
    assert doc.get_toc() == []
    doc.close()


def test_outline_and_links_resolve_to_the_same_pages():
    """Bookmarks and clickable TOC links must point at identical pages."""
    doc = fitz.open()
    for _ in range(10):
        doc.new_page()
    entries = [_toc_entry(i, 0, f"Song {i}") for i in range(3)]
    toc_page_offset = 2  # cover + preface

    toc.add_toc_links_to_merged_pdf(doc, entries, toc_page_offset)
    outline = toc.set_pdf_outline(doc, entries, toc_page_offset)

    toc_page = doc[toc_page_offset]  # all entries are on the first TOC page
    link_pages = sorted(
        ln["page"] for ln in toc_page.get_links() if ln.get("kind") == fitz.LINK_GOTO
    )
    outline_pages = sorted(o[2] - 1 for o in outline)  # 1-based -> 0-based
    assert link_pages == outline_pages == [3, 4, 5]
    doc.close()
