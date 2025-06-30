import os
from datetime import datetime, timedelta, timezone
import pytest
from pathlib import Path
from fsspec.implementations.local import LocalFileSystem

from caching.localstorage import LocalStorageCache


@pytest.fixture
def cache_dir(tmp_path):
    return tmp_path / "cache"


@pytest.fixture
def cache(cache_dir):
    return LocalStorageCache(LocalFileSystem(), str(cache_dir))


def test_put_and_get_basic(cache):
    key = "foo.bin"
    data = b"hello world"
    # put should write file and return its path
    path = cache.put(key, data)
    assert os.path.exists(path)
    assert Path(path).read_bytes() == data

    # get without newer_than should return bytes
    result = cache.get(key)
    assert result == data


def test_get_nonexistent_returns_none(cache):
    assert cache.get("does_not_exist") is None


def test_get_with_newer_than(cache):
    key = "nested/dir/bar.bin"
    data = b"payload"
    # Put the file
    path = cache.put(key, data)

    # Ensure mtime is now, create a cutoff before now
    mtime = Path(path).stat().st_mtime
    file_dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
    older_cutoff = file_dt - timedelta(seconds=10)
    newer_cutoff = file_dt + timedelta(seconds=10)

    # newer_than older → should return bytes
    assert cache.get(key, newer_than=older_cutoff) == data

    # newer_than newer → stale, should return None
    assert cache.get(key, newer_than=newer_cutoff) is None


def test_put_creates_nested_directories(cache_dir):
    cache = LocalStorageCache(LocalFileSystem(), str(cache_dir))
    key = "a/b/c/test.bin"
    data = b"x"
    path = cache.put(key, data)
    # all parent dirs should exist
    assert (cache_dir / "a" / "b" / "c").is_dir()
    assert Path(path).read_bytes() == data


def test_cache_dir_created_on_init(tmp_path):
    dirpath = tmp_path / "does_not_exist_yet"
    # instantiate should create the directory
    LocalStorageCache(LocalFileSystem(), str(dirpath))
    assert dirpath.is_dir()
