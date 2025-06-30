from pathlib import Path
from datetime import datetime


class LocalStorageCache:
    """
    Simple local filesystem cache.
    Stores items under a cache directory, keyed by a string.
    """

    def __init__(self, cache_dir: str):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get(self, key: str, newer_than: datetime | None = None) -> bytes | None:
        """
        Return the file path if it exists and (optionally) its
        modification time is >= newer_than. Otherwise return None.
        """
        cached_path = self.cache_dir / key
        if not cached_path.exists():
            return None

        if newer_than:
            mtime = datetime.fromtimestamp(
                cached_path.stat().st_mtime, tz=newer_than.tzinfo
            )
            if mtime < newer_than:
                return None

        return cached_path.read_bytes()

    def put(self, key: str, data: bytes) -> str:
        """
        Store the given data under the key and return its path.
        Creates any necessary parent directories.
        """
        cached_path = self.cache_dir / key
        # Ensure parent directories exist for nested keys
        cached_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cached_path, "wb") as f:
            f.write(data)
        return str(cached_path)
