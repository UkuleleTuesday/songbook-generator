import pytest
from ..toc import resolve_font, DEFAULT_FONT, load_toc_config, generate_toc_title


def test_resolve_font_valid_fontfile(mocker):
    # Mock fitz.Font to simulate successful font loading
    mock_font = mocker.patch("fitz.Font")
    fontfile = "valid_font.ttf"
    result = resolve_font(fontfile, DEFAULT_FONT)
    assert result == fontfile
    mock_font.assert_called_once_with(fontfile=fontfile)


def test_resolve_font_invalid_fontfile(mocker):
    # Mock fitz.Font to simulate font loading failure
    mock_font = mocker.patch("fitz.Font", side_effect=Exception("Invalid font"))
    fontfile = "invalid_font.ttf"
    result = resolve_font(fontfile, DEFAULT_FONT)
    assert result == DEFAULT_FONT
    mock_font.assert_called_once_with(fontfile=fontfile)


def test_resolve_font_no_fontfile(mocker):
    # Test with no fontfile provided
    mock_font = mocker.patch("fitz.Font")
    result = resolve_font(None, DEFAULT_FONT)
    assert result == DEFAULT_FONT
    mock_font.assert_not_called()


def test_load_toc_config_with_existing_file_but_invalid_font(mocker):
    mock_config = {
        "toc": {
            "text-font": "custom-font",
            "text-fontsize": 12,
            "title-font": "custom-title-font",
            "title-fontsize": 18,
        }
    }
    mock_load_config = mocker.patch("generator.worker.toc.load_config", return_value=mock_config)
    config = load_toc_config()
    assert config.text_font == DEFAULT_FONT
    assert config.text_fontsize == 12
    assert config.title_font == DEFAULT_FONT
    assert config.title_fontsize == 18
    mock_load_config.assert_called_once()


def test_load_toc_config_with_missing_file(mocker):
    mock_load_config = mocker.patch("generator.worker.toc.load_config", return_value={})
    config = load_toc_config()
    assert config.text_font == DEFAULT_FONT
    assert config.text_fontsize == 9
    assert config.title_font == DEFAULT_FONT
    assert config.title_fontsize == 16
    mock_load_config.assert_called_once()


def test_load_toc_config_partial_override(mocker):
    mock_config = {
        "toc": {
            "text-fontsize": 14,
        }
    }
    mock_load_config = mocker.patch("generator.worker.toc.load_config", return_value=mock_config)
    config = load_toc_config()
    assert config.text_font == DEFAULT_FONT
    assert config.text_fontsize == 14
    assert config.title_font == DEFAULT_FONT
    assert config.title_fontsize == 16
    mock_load_config.assert_called_once()


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
