import click
import os
from typing import Optional
import gcsfs
from .localstorage import LocalStorageCache
from fsspec.implementations.local import LocalFileSystem
from ..config import get_settings


def init_cache(
    gcs_worker_cache_bucket: Optional[str] = None,
    use_gcs: Optional[bool] = None,
):
    """
    Initializes the cache, using either GCS or local filesystem.
    The GCS bucket can be specified via argument or environment variable.
    Can be forced to use GCS or local via `use_gcs` boolean.
    """
    click.echo(
        f"[CACHE DEBUG] init_cache called with: use_gcs={use_gcs}, gcs_worker_cache_bucket={gcs_worker_cache_bucket}"
    )
    settings = get_settings()
    caching_settings = settings.caching

    # CLI arguments take precedence over config settings
    should_use_gcs = use_gcs if use_gcs is not None else caching_settings.use_gcs
    bucket_name = (
        gcs_worker_cache_bucket
        if gcs_worker_cache_bucket is not None
        else caching_settings.gcs.worker_cache_bucket
    )
    final_gcp_region = caching_settings.gcs.region

    if should_use_gcs is None:
        click.echo(
            "[CACHE DEBUG] should_use_gcs is None, determining from bucket_name and region..."
        )
        should_use_gcs = bool(bucket_name and final_gcp_region)

    click.echo(f"[CACHE DEBUG] Final decision: should_use_gcs={should_use_gcs}")
    click.echo(f"[CACHE DEBUG] Bucket name: {bucket_name}")
    click.echo(f"[CACHE DEBUG] GCS Region: {final_gcp_region}")
    click.echo(f"[CACHE DEBUG] Local cache dir: {caching_settings.local.dir}")

    if should_use_gcs:
        if not bucket_name or not final_gcp_region:
            raise ValueError(
                "GCS caching is enabled, but bucket name or GCP region is not configured."
            )
        click.echo(f"Using GCS as cache: {bucket_name} {final_gcp_region}")
        fs = gcsfs.GCSFileSystem(default_location=final_gcp_region)
        return LocalStorageCache(fs, bucket_name)
    else:
        if not caching_settings.local.enabled:
            raise ValueError(
                "Local cache is disabled and GCS cache is not configured. "
                "No cache backend available."
            )

        final_local_cache_dir = os.path.expanduser(caching_settings.local.dir)
        click.echo(f"Using cache dir: {final_local_cache_dir}")
        return LocalStorageCache(LocalFileSystem(), final_local_cache_dir)
