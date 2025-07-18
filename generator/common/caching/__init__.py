import click
import os
import gcsfs
from .localstorage import LocalStorageCache
from fsspec.implementations.local import LocalFileSystem
from ..config import DEFAULT_LOCAL_CACHE_DIR


def init_cache():
    if os.getenv("GCS_WORKER_CACHE_BUCKET") and os.getenv("GCP_REGION"):
        bucket = os.getenv("GCS_WORKER_CACHE_BUCKET")
        region = os.getenv("GCP_REGION")
        click.echo(f"Using GCS as cache: {bucket} {region}")
        return LocalStorageCache(gcsfs.GCSFileSystem(default_location=region), bucket)
    else:
        local_cache_dir = os.getenv("LOCAL_CACHE_DIR", DEFAULT_LOCAL_CACHE_DIR)
        click.echo(f"Using cache dir: {local_cache_dir}")
        return LocalStorageCache(LocalFileSystem(), local_cache_dir)
