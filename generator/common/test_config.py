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


def test_gdrive_songbook_editions_folder_ids_override(monkeypatch):
    """Test that GDRIVE_SONGBOOK_EDITIONS_FOLDER_IDS overrides songbook_editions.folder_ids."""
    monkeypatch.setenv(
        "GDRIVE_SONGBOOK_EDITIONS_FOLDER_IDS", "editions_folder1,editions_folder2"
    )
    config.get_settings.cache_clear()
    settings = config.get_settings()
    assert settings.songbook_editions.folder_ids == [
        "editions_folder1",
        "editions_folder2",
    ]


def test_gdrive_songbook_editions_folder_ids_default(monkeypatch):
    """Test that songbook_editions.folder_ids defaults to an empty list."""
    monkeypatch.delenv("GDRIVE_SONGBOOK_EDITIONS_FOLDER_IDS", raising=False)
    config.get_settings.cache_clear()
    settings = config.get_settings()
    assert settings.songbook_editions.folder_ids == []


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
    """Test that drive_client.api_retries has a default value of 3."""
    config.get_settings.cache_clear()
    settings = config.get_settings()
    assert settings.google_cloud.drive_client.api_retries == 3


def test_google_drive_api_retries_override(monkeypatch):
    """Test that GOOGLE_DRIVE_API_RETRIES overrides drive_client.api_retries."""
    monkeypatch.setenv("GOOGLE_DRIVE_API_RETRIES", "5")
    config.get_settings.cache_clear()
    settings = config.get_settings()
    assert settings.google_cloud.drive_client.api_retries == 5


def test_google_drive_api_retries_invalid_override(monkeypatch):
    """Test that invalid GOOGLE_DRIVE_API_RETRIES values are ignored."""
    monkeypatch.setenv("GOOGLE_DRIVE_API_RETRIES", "invalid")
    config.get_settings.cache_clear()
    settings = config.get_settings()
    assert settings.google_cloud.drive_client.api_retries == 3  # Default value


def test_editions_loaded_from_songbooks_directory():
    """Test that editions are loaded from the songbooks/ directory."""
    config.get_settings.cache_clear()
    settings = config.get_settings()
    assert len(settings.editions) > 0
    edition_ids = [e.id for e in settings.editions]
    assert "current" in edition_ids
    assert "complete" in edition_ids


def test_each_edition_file_loads_as_single_edition():
    """Test that each file in the songbooks/ directory loads as one edition."""
    config.get_settings.cache_clear()
    settings = config.get_settings()
    ids = [e.id for e in settings.editions]
    # No duplicate IDs should exist
    assert len(ids) == len(set(ids))


def test_edition_filters_optional_when_use_folder_components():
    """filters can be omitted when use_folder_components is True."""
    edition = config.Edition(
        id="test",
        title="Test",
        description="Test",
        use_folder_components=True,
    )
    assert edition.filters is None


def test_edition_filters_required_without_folder_components():
    """filters is required when use_folder_components is False (the default)."""
    import pydantic

    with pytest.raises(pydantic.ValidationError, match="filters is required"):
        config.Edition(
            id="test",
            title="Test",
            description="Test",
        )


def test_edition_empty_filters_allowed_without_folder_components():
    """An explicit empty filters list is valid even without use_folder_components."""
    edition = config.Edition(
        id="test",
        title="Test",
        description="Test",
        filters=[],
    )
    assert edition.filters == []


@pytest.mark.parametrize(
    "env_value, expected",
    [
        (None, False),  # Off by default
        ("true", True),
        ("True", True),
        ("1", True),
        ("false", False),
        ("0", False),
    ],
)
def test_tagupdater_llm_tagging_enabled_override(monkeypatch, env_value, expected):
    """Test that TAGUPDATER_LLM_TAGGING_ENABLED controls llm_tagging_enabled."""
    if env_value is not None:
        monkeypatch.setenv("TAGUPDATER_LLM_TAGGING_ENABLED", env_value)
    else:
        monkeypatch.delenv("TAGUPDATER_LLM_TAGGING_ENABLED", raising=False)
    config.get_settings.cache_clear()
    settings = config.get_settings()
    assert settings.tag_updater.llm_tagging_enabled is expected


def test_tagupdater_dry_run_default(monkeypatch):
    """Test that dry_run defaults to False."""
    monkeypatch.delenv("TAGUPDATER_DRY_RUN", raising=False)
    config.get_settings.cache_clear()
    settings = config.get_settings()
    assert settings.tag_updater.dry_run is False


def test_edition_filters_and_folder_components_together():
    """filters can be provided alongside use_folder_components=True."""
    from generator.common.filters import PropertyFilter, FilterOperator

    f = PropertyFilter(key="status", operator=FilterOperator.EQUALS, value="active")
    edition = config.Edition(
        id="test",
        title="Test",
        description="Test",
        use_folder_components=True,
        filters=[f],
    )
    assert edition.filters == [f]
