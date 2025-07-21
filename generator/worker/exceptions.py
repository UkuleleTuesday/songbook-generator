class SongbookGenerationException(Exception):
    """Base exception for all songbook generation errors."""

    pass


class TocGenerationException(SongbookGenerationException):
    """Custom exception for errors during toc generation."""

    pass


class CoverGenerationException(SongbookGenerationException):
    """Custom exception for errors during cover generation."""

    pass


class PdfCopyException(SongbookGenerationException):
    """Custom exception for errors during pdf copy."""

    pass


class PdfCacheNotFound(PdfCopyException):
    """Custom exception for errors during pdf copy."""

    pass


class PdfCacheMissException(PdfCopyException):
    """Custom exception for errors during pdf copy."""

    pass
