import pytest
import fitz
from songbook_generator.toc import resolve_font, DEFAULT_FONT, load_toc_config
from unittest.mock import patch, mock_open


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


def test_load_toc_config_with_existing_file():
    mock_config = """
    [toc]
    text-font = "custom-font"
    text-fontsize = 12
    title-font = "custom-title-font"
    title-fontsize = 18
    """
    with patch("builtins.open", mock_open(read_data=mock_config)):
        with patch("os.path.exists", return_value=True):
            text_font, text_fontsize, title_font, title_fontsize = load_toc_config()
            assert text_font == "custom-font"
            assert text_fontsize == 12
            assert title_font == "custom-title-font"
            assert title_fontsize == 18


def test_load_toc_config_with_missing_file():
    with patch("os.path.exists", return_value=False):
        text_font, text_fontsize, title_font, title_fontsize = load_toc_config()
        assert text_font == DEFAULT_FONT
        assert text_fontsize == 9
        assert title_font == DEFAULT_FONT
        assert title_fontsize == 16


def test_load_toc_config_partial_override():
    mock_config = """
    [toc]
    text-fontsize = 14
    """
    with patch("builtins.open", mock_open(read_data=mock_config)):
        with patch("os.path.exists", return_value=True):
            text_font, text_fontsize, title_font, title_fontsize = load_toc_config()
            assert text_font == DEFAULT_FONT
            assert text_fontsize == 14
            assert title_font == DEFAULT_FONT
            assert title_fontsize == 16
