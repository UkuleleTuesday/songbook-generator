class SongbookGenerationException(Exception):
    """Base exception for all songbook generation errors."""

    pass


class CoverGenerationException(SongbookGenerationException):
    """Custom exception for errors during cover generation."""

    pass
