import click
import os
from typing import Optional
import gcsfs
from .localstorage import LocalStorageCache
from fsspec.implementations.local import LocalFileSystem
from ..config import get_settings


def init_cache(
    gcs_worker_cache_bucket: Optional[str] = None, use_gcs: Optional[bool] = None
):
    """
    Initializes the cache, using either GCS or local filesystem.
    The GCS bucket can be specified via argument or environment variable.
    Can be forced to use GCS or local via `use_gcs` boolean.
    """
    settings = get_settings()
    caching_settings = settings.caching

    # CLI arguments take precedence over config settings
    should_use_gcs = use_gcs if use_gcs is not None else caching_settings.use_gcs
    bucket_name = gcs_worker_cache_bucket or caching_settings.gcs_worker_cache_bucket
    gcp_region = caching_settings.gcp_region

    if should_use_gcs is None:
        should_use_gcs = bool(bucket_name and gcp_region)

    if should_use_gcs:
        if not bucket_name or not gcp_region:
            raise ValueError(
                "GCS caching is enabled, but bucket name or GCP region is not configured."
            )
        click.echo(f"Using GCS as cache: {bucket_name} {gcp_region}")
        fs = gcsfs.GCSFileSystem(default_location=gcp_region)
        return LocalStorageCache(fs, bucket_name)
    else:
        local_cache_dir = os.path.expanduser(caching_settings.local_cache_dir)
        click.echo(f"Using cache dir: {local_cache_dir}")
        return LocalStorageCache(LocalFileSystem(), local_cache_dir)
