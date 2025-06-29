import pytest
import fitz
from src.songbook_generator.toc import resolve_font, DEFAULT_FONT

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
