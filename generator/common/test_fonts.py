import fitz
import pytest
from unittest.mock import patch, MagicMock

from .fonts import (
    find_font_path,
    resolve_font,
)


@patch("generator.common.fonts.find_font_path")
@patch("importlib.resources.files")
@patch("fitz.Font")
def test_resolve_font_from_package_resources(
    mock_fitz_font, mock_importlib_files, mock_find_font_path
):
    """Test that a font is loaded from package resources if available."""
    # Setup mock for importlib.resources
    mock_font_file = MagicMock()
    mock_font_file.read_bytes.return_value = b"font_data"
    mock_importlib_files.return_value.joinpath.return_value = mock_font_file

    resolve_font("SomeFont.ttf")

    mock_importlib_files.assert_called_once_with("generator.fonts")
    mock_importlib_files.return_value.joinpath.assert_called_once_with("SomeFont.ttf")
    mock_fitz_font.assert_called_once_with(fontbuffer=b"font_data")
    mock_find_font_path.assert_not_called()


@patch("generator.common.fonts.find_font_path")
@patch("importlib.resources.files", side_effect=FileNotFoundError)
@patch("fitz.Font")
def test_resolve_font_from_system_path(
    mock_fitz_font, mock_importlib_files, mock_find_font_path
):
    """Test that a font is loaded from a system path when not in resources."""
    mock_find_font_path.return_value = "/fake/path/to/font.ttf"

    resolve_font("SomeFont.ttf")

    mock_find_font_path.assert_called_once_with("SomeFont.ttf")
    mock_fitz_font.assert_called_once_with(fontfile="/fake/path/to/font.ttf")


@patch("generator.common.fonts.find_font_path", return_value=None)
@patch("importlib.resources.files", side_effect=FileNotFoundError)
@patch("fitz.Font")
def test_resolve_font_fallback_to_fitz_search(
    mock_fitz_font, mock_importlib_files, mock_find_font_path
):
    """Test that it falls back to fitz's built-in search."""
    resolve_font("SomeFont-Bold")

    mock_fitz_font.assert_called_once_with("SomeFont-Bold")


@patch("generator.common.fonts.find_font_path", return_value=None)
@patch("importlib.resources.files", side_effect=FileNotFoundError)
def test_resolve_font_total_failure(mock_importlib_files, mock_find_font_path):
    """Test that an exception is raised when all methods fail."""

    def fitz_font_side_effect(font_name, *args, **kwargs):
        if font_name == "NonExistentFont":
            raise RuntimeError("Font not found")
        return MagicMock()

    with patch(
        "fitz.Font", side_effect=fitz_font_side_effect
    ) as mock_fitz_font, pytest.raises(FileNotFoundError):
        resolve_font("NonExistentFont")

    mock_fitz_font.assert_called_once_with("NonExistentFont")
