import click
import os
from typing import Optional
import gcsfs
from .localstorage import LocalStorageCache
from fsspec.implementations.local import LocalFileSystem
from ..config import get_local_cache_dir


def init_cache(
    gcs_worker_cache_bucket: Optional[str] = None, use_gcs: Optional[bool] = None
):
    """
    Initializes the cache, using either GCS or local filesystem.
    The GCS bucket can be specified via argument or environment variable.
    Can be forced to use GCS or local via `use_gcs` boolean.
    """
    # Determine whether to use GCS based on the use_gcs flag or auto-detection
    should_use_gcs = use_gcs
    bucket_name = gcs_worker_cache_bucket or os.getenv("GCS_WORKER_CACHE_BUCKET")
    gcp_region = os.getenv("GCP_REGION")

    if should_use_gcs is None:
        should_use_gcs = bool(bucket_name and gcp_region)

    if should_use_gcs:
        click.echo(f"Using GCS as cache: {bucket_name} {gcp_region}")
        fs = gcsfs.GCSFileSystem(default_location=gcp_region)
        return LocalStorageCache(fs, bucket_name)
    else:
        local_cache_dir = get_local_cache_dir()
        click.echo(f"Using cache dir: {local_cache_dir}")
        return LocalStorageCache(LocalFileSystem(), local_cache_dir)
