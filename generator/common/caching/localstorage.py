from datetime import datetime
from fsspec.spec import AbstractFileSystem
import os

from ..tracing import get_tracer

tracer = get_tracer(__name__)


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
        with tracer.start_as_current_span("cache.get") as span:
            path = f"{self.cache_dir}/{key}"
            span.set_attribute("cache.key", key)
            span.set_attribute("cache.path", path)
            span.set_attribute("cache.backend", type(self.fs).__name__)

            if not self.fs.exists(path):
                span.set_attribute("cache.hit", False)
                return None

            if newer_than:
                span.set_attribute("cache.newer_than_check", str(newer_than))
                info = self.fs.stat(path)
                # different fsspec backends are inconsistent in return type here:
                try:
                    mtime = datetime.fromtimestamp(
                        info.get("mtime", 0).timestamp(), tz=newer_than.tzinfo
                    )
                except AttributeError:
                    mtime = datetime.fromtimestamp(
                        info.get("mtime", 0), tz=newer_than.tzinfo
                    )
                span.set_attribute("cache.mtime", str(mtime))
                if mtime < newer_than:
                    span.set_attribute("cache.hit", False)
                    span.set_attribute("cache.stale", True)
                    return None

            # Read and return cached bytes
            with self.fs.open(path, "rb") as f:
                data = f.read()
                span.set_attribute("cache.hit", True)
                span.set_attribute("cache.bytes_read", len(data))
                return data

    def put(self, key: str, data: bytes, metadata: dict = None) -> str:
        """
        Store the given data under the key and return its path.
        Creates any necessary parent directories.
        """
        with tracer.start_as_current_span("cache.put") as span:
            path = f"{self.cache_dir}/{key}"
            span.set_attribute("cache.key", key)
            span.set_attribute("cache.path", path)
            span.set_attribute("cache.bytes_written", len(data))
            span.set_attribute("cache.backend", type(self.fs).__name__)

            # Ensure parent directories exist for nested keys
            parent_dir = os.path.dirname(path)
            if parent_dir:
                self.fs.makedirs(parent_dir, exist_ok=True)

            kwargs = {}
            if type(self.fs).__name__ == "GCSFileSystem":
                kwargs["metadata"] = metadata

            with self.fs.open(path, "wb", **kwargs) as f:
                f.write(data)

            return path
