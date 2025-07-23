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
