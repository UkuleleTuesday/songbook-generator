from toc import resolve_font, DEFAULT_FONT, load_toc_config


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
    mock_load_config = mocker.patch("toc.load_config", return_value=mock_config)
    text_font, text_fontsize, title_font, title_fontsize = load_toc_config()
    assert text_font == DEFAULT_FONT
    assert text_fontsize == 12
    assert title_font == DEFAULT_FONT
    assert title_fontsize == 18
    mock_load_config.assert_called_once()


def test_load_toc_config_with_missing_file(mocker):
    mock_load_config = mocker.patch("toc.load_config", return_value={})
    text_font, text_fontsize, title_font, title_fontsize = load_toc_config()
    assert text_font == DEFAULT_FONT
    assert text_fontsize == 9
    assert title_font == DEFAULT_FONT
    assert title_fontsize == 16
    mock_load_config.assert_called_once()


def test_load_toc_config_partial_override(mocker):
    mock_config = {
        "toc": {
            "text-fontsize": 14,
        }
    }
    mock_load_config = mocker.patch("toc.load_config", return_value=mock_config)
    text_font, text_fontsize, title_font, title_fontsize = load_toc_config()
    assert text_font == DEFAULT_FONT
    assert text_fontsize == 14
    assert title_font == DEFAULT_FONT
    assert title_fontsize == 16
    mock_load_config.assert_called_once()
