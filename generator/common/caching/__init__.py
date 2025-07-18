import click
import os
from typing import Optional
import gcsfs
from .localstorage import LocalStorageCache
from fsspec.implementations.local import LocalFileSystem
from ..config import get_local_cache_dir


def init_cache(gcs_worker_cache_bucket: Optional[str] = None):
    """
    Initializes the cache, using either GCS or local filesystem.
    The GCS bucket can be specified via argument or environment variable.
    """
    bucket_name = gcs_worker_cache_bucket or os.getenv("GCS_WORKER_CACHE_BUCKET")
    gcp_region = os.getenv("GCP_REGION")

    if bucket_name and gcp_region:
        click.echo(f"Using GCS as cache: {bucket_name} {gcp_region}")
        fs = gcsfs.GCSFileSystem(default_location=gcp_region)
        return LocalStorageCache(fs, bucket_name)
    else:
        local_cache_dir = get_local_cache_dir()
        click.echo(f"Using cache dir: {local_cache_dir}")
        return LocalStorageCache(LocalFileSystem(), local_cache_dir)
