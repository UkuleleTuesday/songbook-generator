import pytest
from generator.common import config


@pytest.mark.parametrize(
    "otel_sdk_disabled_value, expected_tracing_enabled",
    [
        (None, False),  # Default behavior: disabled
        ("true", False),  # Explicitly disabled
        ("TRUE", False),  # Case-insensitive disabled
        ("false", True),  # Explicitly enabled
        ("FALSE", True),  # Case-insensitive enabled
        ("other", False),  # Any other value is disabled
    ],
)
def test_tracing_config_respects_otel_sdk_disabled(
    monkeypatch, otel_sdk_disabled_value, expected_tracing_enabled
):
    """
    Tests that the Tracing config model correctly interprets
    the OTEL_SDK_DISABLED environment variable.
    """
    if otel_sdk_disabled_value is not None:
        monkeypatch.setenv("OTEL_SDK_DISABLED", otel_sdk_disabled_value)
    else:
        monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)

    # Clear the cache to force reloading settings
    config.get_settings.cache_clear()
    settings = config.get_settings()

    assert settings.tracing.enabled is expected_tracing_enabled


def test_gdrive_song_sheets_folder_ids_override(monkeypatch):
    """Test that GDRIVE_SONG_SHEETS_FOLDER_IDS overrides song_sheets.folder_ids."""
    monkeypatch.setenv("GDRIVE_SONG_SHEETS_FOLDER_IDS", "folder1,folder2")
    config.get_settings.cache_clear()
    settings = config.get_settings()
    assert settings.song_sheets.folder_ids == ["folder1", "folder2"]


def test_gcs_worker_cache_bucket_override(monkeypatch):
    """Test that GCS_WORKER_CACHE_BUCKET overrides caching.gcs.worker_cache_bucket."""
    monkeypatch.setenv("GCS_WORKER_CACHE_BUCKET", "my-test-bucket")
    config.get_settings.cache_clear()
    settings = config.get_settings()
    assert settings.caching.gcs.worker_cache_bucket == "my-test-bucket"


def test_gcp_region_override(monkeypatch):
    """Test that GCP_REGION overrides caching.gcs.region."""
    monkeypatch.setenv("GCP_REGION", "my-test-region")
    config.get_settings.cache_clear()
    settings = config.get_settings()
    assert settings.caching.gcs.region == "my-test-region"


@pytest.mark.parametrize(
    "env_value, expected_bool",
    [
        ("true", True),
        ("false", False),
    ],
)
def test_local_cache_enabled_override(monkeypatch, env_value, expected_bool):
    """Test that LOCAL_CACHE_ENABLED overrides caching.local.enabled."""
    monkeypatch.setenv("LOCAL_CACHE_ENABLED", env_value)
    config.get_settings.cache_clear()
    settings = config.get_settings()
    assert settings.caching.local.enabled is expected_bool


def test_local_cache_dir_override(monkeypatch):
    """Test that LOCAL_CACHE_DIR overrides caching.local.dir."""
    monkeypatch.setenv("LOCAL_CACHE_DIR", "/tmp/my-cache")
    config.get_settings.cache_clear()
    settings = config.get_settings()
    assert settings.caching.local.dir == "/tmp/my-cache"


def test_google_drive_api_retries_default():
    """Test that google_drive_api_retries has a default value of 3."""
    config.get_settings.cache_clear()
    settings = config.get_settings()
    assert settings.google_cloud.google_drive_api_retries == 3
