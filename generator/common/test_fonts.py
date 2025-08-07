import fitz
import pytest
from unittest.mock import patch, MagicMock

from .fonts import resolve_font


@patch("importlib.resources.files")
@patch("fitz.Font")
def test_resolve_font_from_package_resources(mock_fitz_font, mock_importlib_files):
    """Test that a font is loaded from package resources if available."""
    # Setup mock for importlib.resources
    mock_font_file = MagicMock()
    mock_font_file.read_bytes.return_value = b"font_data"
    mock_importlib_files.return_value.joinpath.return_value = mock_font_file

    resolve_font("SomeFont.ttf")

    mock_importlib_files.assert_called_once_with("generator.fonts")
    mock_importlib_files.return_value.joinpath.assert_called_once_with("SomeFont.ttf")
    mock_fitz_font.assert_called_once_with(fontbuffer=b"font_data")


@patch("importlib.resources.files", side_effect=FileNotFoundError)
@patch("os.path.dirname")
@patch("builtins.open")
@patch("fitz.Font")
def test_resolve_font_fallback_to_filesystem(
    mock_fitz_font, mock_open, mock_dirname, mock_importlib_files
):
    """Test that it falls back to filesystem for GCF-like environments."""
    mock_dirname.return_value = "/fake/path/to/common"
    mock_file = MagicMock()
    mock_file.read.return_value = b"font_data_from_file"
    mock_open.return_value.__enter__.return_value = mock_file

    resolve_font("SomeFont.ttf")

    mock_importlib_files.assert_called_once_with("generator.fonts")
    # Normalize path for assertion to avoid issues with '..'
    called_path = mock_open.call_args[0][0]
    normalized_path = os.path.normpath(called_path)
    assert normalized_path == "/fake/path/to/fonts/SomeFont.ttf"
    mock_fitz_font.assert_called_once_with(fontbuffer=b"font_data_from_file")


@patch("importlib.resources.files", side_effect=FileNotFoundError)
@patch("builtins.open", side_effect=FileNotFoundError)
def test_resolve_font_total_failure(mock_open, mock_importlib_files):
    """Test that an exception is raised when all methods fail."""
    with pytest.raises(FileNotFoundError) as excinfo:
        resolve_font("NonExistentFont.ttf")

    assert "Font file not found for: NonExistentFont.ttf" in str(excinfo.value)
