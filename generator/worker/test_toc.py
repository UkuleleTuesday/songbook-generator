import pytest
from unittest.mock import MagicMock, ANY
import fitz
from .toc import (
    resolve_font,
    generate_toc_title,
    DEFAULT_FONT_NAME,
    TocGenerator,
    load_toc_config,
    difficulty_symbol,
)
from .models import File
from .exceptions import TocGenerationException


def test_resolve_font_valid_font(mocker):
    """Test that a valid font file is loaded correctly."""
    # Mock importlib.resources to avoid file system access
    mock_files = mocker.patch("importlib.resources.files")
    mock_path = mock_files.return_value.joinpath.return_value
    mock_path.read_bytes.return_value = b"font_data"
    mock_fitz_font = mocker.patch("fitz.Font")

    font_name = DEFAULT_FONT_NAME
    resolve_font(font_name)

    mock_files.assert_called_once_with("generator.fonts")
    mock_files.return_value.joinpath.assert_called_once_with(font_name)
    mock_path.read_bytes.assert_called_once()
    mock_fitz_font.assert_called_once_with(fontbuffer=b"font_data")


def test_resolve_font_fallback_to_path(mocker):
    """Test that font loading falls back to file path on ModuleNotFoundError."""
    # First, mock importlib.resources to fail
    mocker.patch(
        "importlib.resources.files", side_effect=ModuleNotFoundError("test error")
    )

    # Then, mock the file-based loading to succeed
    mock_open = mocker.patch("builtins.open", mocker.mock_open(read_data=b"font_data"))
    mocker.patch("os.path.join", return_value="/fake/path/to/font.ttf")
    mocker.patch("os.path.abspath")
    mock_fitz_font = mocker.patch("fitz.Font")

    resolve_font("font.ttf")

    mock_open.assert_called_once_with("/fake/path/to/font.ttf", "rb")
    mock_fitz_font.assert_called_once_with(fontbuffer=b"font_data")


def test_resolve_font_total_failure(mocker):
    """Test that it raises TocGenerationException when all methods fail."""
    # Mock both importlib.resources and file-based loading to fail
    mocker.patch(
        "importlib.resources.files", side_effect=ModuleNotFoundError("test error")
    )
    mocker.patch("builtins.open", side_effect=FileNotFoundError("test file not found"))
    mocker.patch("os.path.abspath")

    with pytest.raises(TocGenerationException) as excinfo:
        resolve_font("non_existent_font.ttf")

    assert "TOC font file not found: non_existent_font.ttf" in str(excinfo.value)


@pytest.mark.parametrize(
    "difficulty,expected_symbol",
    [
        (0, "○"),
        (0.9, "○"),
        (1, "◔"),
        (1.9, "◔"),
        (2, "◑"),
        (2.9, "◑"),
        (3, "◕"),
        (3.9, "◕"),
        (4, "●"),
        (5, "●"),
        (100, "●"),
    ],
)
def test_difficulty_symbol(difficulty, expected_symbol):
    """Test that difficulty_symbol returns the correct symbol for a given value."""
    assert difficulty_symbol(difficulty) == expected_symbol


def test_generate_toc_title_empty_string():
    """Test with empty string."""
    title = ""
    result = generate_toc_title(title, max_length=60)
    assert result == ""


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
def toc_layout():
    """Provides a default TocLayout with a mocked font."""
    layout = load_toc_config()
    # Mock font to control text_length for predictable testing
    layout.text_font = MagicMock()
    layout.text_font.text_length.side_effect = lambda text, fontsize: len(text) * 5
    return layout


def test_add_toc_entry(toc_layout):
    """Test that _add_toc_entry correctly formats and adds a TOC entry."""
    generator = TocGenerator(toc_layout)
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

    # Check that title is appended
    mock_tw.append.assert_called_with(
        (25, 70), "A Short Title - Artist", font=ANY, fontsize=ANY
    )

    # Check that fill_textbox is called for dots and page number
    # The text should be a number of dots, a space, and "1"
    mock_tw.fill_textbox.assert_called_once()
    args, kwargs = mock_tw.fill_textbox.call_args
    dots_and_page = args[1]
    assert dots_and_page.endswith(" 1")
    assert dots_and_page.startswith(".")
    assert kwargs["align"] == fitz.TEXT_ALIGN_RIGHT


def test_add_toc_entry_title_truncation(toc_layout):
    """Test that a long title is truncated correctly."""
    generator = TocGenerator(toc_layout)
    mock_tw = MagicMock(spec=fitz.TextWriter)

    long_title = "This is a very long song title that will definitely need to be truncated - The Long Winded Singers"
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
    appended_title = mock_tw.append.call_args[0][1]
    assert len(appended_title) < len(long_title)
    assert appended_title.endswith("...")


def test_add_toc_entry_with_difficulty(toc_layout):
    """Test that a difficulty symbol is added to the TOC entry."""
    generator = TocGenerator(toc_layout)
    mock_tw = MagicMock(spec=fitz.TextWriter)

    file_with_difficulty = File(
        id="1", name="Easy Song", properties={"difficulty": "1.5"}
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
    appended_title = mock_tw.append.call_args[0][1]
    assert appended_title.startswith("◔ ")
    assert "Easy Song" in appended_title


def test_add_toc_entry_ready_to_play_status(toc_layout):
    """Test that a '*' is added for READY_TO_PLAY status."""
    generator = TocGenerator(toc_layout)
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
    appended_title = mock_tw.append.call_args[0][1]
    assert "Ready Song *" in appended_title
