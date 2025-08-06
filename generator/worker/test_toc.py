import pytest
from unittest.mock import MagicMock
import fitz
from .toc import (
    resolve_font,
    generate_toc_title,
    TocGenerator,
    difficulty_symbol,
)
from .models import File
from . import toc


def test_resolve_font_valid_font(mocker):
    """Test that a valid font file is loaded correctly."""
    mock_find_font = mocker.patch("generator.worker.toc.find_font_path")
    mock_find_font.return_value = "/fake/path/to/font.ttf"

    mock_fitz_font = mocker.patch("fitz.Font")

    resolve_font("SomeFont.ttf")

    mock_find_font.assert_called_once_with("SomeFont.ttf")
    mock_fitz_font.assert_called_once_with(fontfile="/fake/path/to/font.ttf")


def test_resolve_font_fallback_to_path(mocker):
    """Test that font loading falls back to a different font."""
    mock_find_font = mocker.patch("generator.worker.toc.find_font_path")
    # First find fails, second for "Verdana" succeeds.
    mock_find_font.side_effect = [None, "/system/fonts/Verdana.ttf"]

    mock_fitz_font = mocker.patch("fitz.Font")

    resolve_font("MissingFont.ttf")

    assert mock_find_font.call_count == 2
    mock_find_font.assert_any_call("MissingFont.ttf")
    mock_find_font.assert_any_call("Verdana")
    mock_fitz_font.assert_called_once_with(fontfile="/system/fonts/Verdana.ttf")


def test_resolve_font_total_failure(mocker):
    """Test that it falls back to built-in font when all methods fail."""
    mock_find_font = mocker.patch("generator.worker.toc.find_font_path")
    mock_find_font.return_value = None  # All lookups fail

    mock_fitz_font = mocker.patch("fitz.Font")

    resolve_font("non_existent_font.ttf")

    # Should have tried original font, then fallback Verdana
    assert mock_find_font.call_count == 2
    # Should have created a built-in font
    mock_fitz_font.assert_called_once_with("helv")


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


def test_generate_toc_title_empty_string():
    """Test with empty string."""
    title = ""
    result = generate_toc_title(title, max_length=60)
    assert result == ""


def test_generate_toc_title_empty_string_ready_to_play():
    """Test with empty string that is ready to play."""
    title = ""
    result = generate_toc_title(title, max_length=60, is_ready_to_play=True)
    assert result == "*"


def test_generate_toc_title_very_short_max_length():
    """Test with very short max length."""
    title = "Long Title"
    result = generate_toc_title(title, max_length=3)
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
def test_generate_toc_title_real_world_samples(original_title, expected_title):
    """Test generate_toc_title with real titles from the TOC."""
    # Test with default max_length
    result = generate_toc_title(original_title, max_length=50)
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


def test_add_toc_entry(mock_toc_generator):
    """Test that _add_toc_entry correctly formats and adds a TOC entry."""
    generator = mock_toc_generator
    mock_tw = MagicMock(spec=fitz.TextWriter)

    generator._add_toc_entry(
        tw=mock_tw,
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
        tw=mock_tw,
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
        tw=mock_tw,
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


def test_generate_toc_title_truncation_with_ready_to_play():
    """Test that a long title is truncated and still gets a '*'."""
    long_title = "This is a very long song title that will definitely need to be truncated to see the effect"
    result = generate_toc_title(long_title, max_length=50, is_ready_to_play=True)
    assert result.endswith("...*")
    assert len(result) < len(long_title)


def test_add_toc_entry_ready_to_play_status(mock_toc_generator):
    """Test that a '*' is added for READY_TO_PLAY status."""
    generator = mock_toc_generator
    mock_tw = MagicMock(spec=fitz.TextWriter)

    file = File(id="1", name="Ready Song", properties={"status": "READY_TO_PLAY"})

    generator._add_toc_entry(
        tw=mock_tw,
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


def test_build_table_of_contents_calls_assign_difficulty_bins(mocker):
    """Verify that assign_difficulty_bins is called."""
    mock_assign_bins = mocker.patch("generator.worker.toc.assign_difficulty_bins")
    mocker.patch("generator.worker.toc.get_settings")
    mocker.patch("generator.worker.toc.TocGenerator")

    files = [File(id="1", name="Song 1")]
    toc.build_table_of_contents(files)

    mock_assign_bins.assert_called_once_with(files)
