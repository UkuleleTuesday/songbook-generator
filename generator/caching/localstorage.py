from datetime import datetime
from fsspec.spec import AbstractFileSystem
import os


class LocalStorageCache:
    """
    Simple cache layer over an fsspec filesystem.
    Stores items under a cache directory, keyed by a string.
    """

    def __init__(self, fs: AbstractFileSystem, cache_dir: str):
        """
        :param fs: An fsspec filesystem instance
        :param cache_dir: Base directory on the filesystem for cache storage
        """
        self.fs = fs
        self.cache_dir = cache_dir.rstrip("/")
        # Ensure cache base directory exists
        self.fs.makedirs(self.cache_dir, exist_ok=True)

    def get(self, key: str, newer_than: datetime | None = None) -> bytes | None:
        """
        Return the cached data if it exists and (optionally) its
        modification time is >= newer_than. Otherwise return None.
        """
        path = f"{self.cache_dir}/{key}"
        if not self.fs.exists(path):
            return None

        if newer_than:
            info = self.fs.stat(path)
            # fsspec returns mtime in seconds since epoch
            mtime = datetime.fromtimestamp(info.get("mtime", 0).timestamp(), tz=newer_than.tzinfo)
            if mtime < newer_than:
                return None

        # Read and return cached bytes
        with self.fs.open(path, "rb") as f:
            return f.read()

    def put(self, key: str, data: bytes) -> str:
        """
        Store the given data under the key and return its path.
        Creates any necessary parent directories.
        """
        path = f"{self.cache_dir}/{key}"
        # Ensure parent directories exist for nested keys
        parent_dir = os.path.dirname(path)
        if parent_dir:
            self.fs.makedirs(parent_dir, exist_ok=True)

        with self.fs.open(path, "wb") as f:
            f.write(data)

        return path
