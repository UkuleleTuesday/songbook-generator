import click
import os
import gcsfs
from caching.localstorage import LocalStorageCache
from fsspec.implementations.local import LocalFileSystem

LOCAL_CACHE_DIR = os.path.join(os.path.expanduser("~/.cache"), "songbook-generator")


def init_cache():
    if os.getenv("GCS_WORKER_CACHE_BUCKET") and os.getenv("GCP_REGION"):
        bucket = os.getenv("GCS_WORKER_CACHE_BUCKET")
        region = os.getenv("GCP_REGION")
        click.echo(f"Using GCS as cache: {bucket} {region}")
        return LocalStorageCache(gcsfs.GCSFileSystem(default_location=region), bucket)
    else:
        click.echo(f"Using cache dir: {LOCAL_CACHE_DIR}")
        return LocalStorageCache(LocalFileSystem(), LOCAL_CACHE_DIR)
