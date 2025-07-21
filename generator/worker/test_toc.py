import pytest
from .toc import resolve_font, generate_toc_title, DEFAULT_FONT_NAME


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


def test_resolve_font_fallback(mocker):
    """Test that it falls back to a built-in font on failure."""
    # Mock importlib.resources to simulate file not found
    mock_files = mocker.patch("importlib.resources.files")
    mock_files.return_value.joinpath.side_effect = FileNotFoundError

    mock_fitz_font = mocker.patch("fitz.Font")
    mock_echo = mocker.patch("click.echo")

    font_name = "non_existent_font.ttf"
    resolve_font(font_name)

    mock_echo.assert_called_once()
    assert "Falling back to default font 'helv'" in mock_echo.call_args[0][0]
    mock_fitz_font.assert_called_once_with("helv")


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
