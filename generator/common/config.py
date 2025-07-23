import os
from functools import lru_cache
from pathlib import Path
from typing import List, Tuple, Optional

from pydantic import (
    AliasChoices,
    BaseModel,
    Field,
    field_validator,
    model_validator,
)
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)


class SongSheets(BaseModel):
    folder_ids: List[str] = Field(
        default=[
            "1b_ZuZVOGgvkKVSUypkbRwBsXLVQGjl95",  # UT Song Sheets Google Docs
            "1bvrIMQXjAxepzn4Vx8wEjhk3eQS5a9BM",  # (3) Ready To Play
        ],
        validation_alias=AliasChoices("GDRIVE_SONG_SHEETS_FOLDER_IDS"),
    )


class Cover(BaseModel):
    file_id: Optional[str] = "1HB1fUAY3uaARoHzSDh2TymfvNBvpKOEE221rubsjKoQ"


class Toc(BaseModel):
    columns_per_page: int = 2
    column_width: int = 250
    column_spacing: int = 20
    margin_top: int = 20
    margin_bottom: int = 20
    margin_left: int = 25
    margin_right: int = 25
    title_height: int = 50
    line_spacing: int = 12
    text_font: str = "RobotoCondensed-Regular.ttf"
    page_number_font: str = "RobotoCondensed-SemiBold.ttf"
    text_fontsize: float = 10.0
    title_font: str = "RobotoCondensed-Bold.ttf"
    title_fontsize: int = 16
    max_toc_entry_length: int = 60

    @field_validator(
        "*",
        mode="before",
    )
    def empty_str_to_none(cls, v):
        if v == "":
            return None
        return v


class CachingGcs(BaseModel):
    worker_cache_bucket: Optional[str] = Field(
        "songbook-generator-cache-europe-west1",
        alias="GCS_WORKER_CACHE_BUCKET",
    )
    region: Optional[str] = Field(None, alias="GCP_REGION")


class CachingLocal(BaseModel):
    enabled: bool = Field(True, validation_alias=AliasChoices("LOCAL_CACHE_ENABLED"))
    dir: Optional[str] = Field(
        os.path.join(os.path.expanduser("~/.cache"), "songbook-generator"),
        validation_alias=AliasChoices("LOCAL_CACHE_DIR"),
    )


class Caching(BaseModel):
    use_gcs: Optional[bool] = None
    gcs: CachingGcs = Field(default_factory=CachingGcs)
    local: CachingLocal = Field(default_factory=CachingLocal)


class Tracing(BaseModel):
    enabled: bool = Field(default=False)

    @model_validator(mode="before")
    def check_otel_sdk_disabled(cls, data):
        # This allows enabling tracing by setting OTEL_SDK_DISABLED=false
        # while keeping it disabled by default.
        if os.environ.get("OTEL_SDK_DISABLED", "true").lower() == "false":
            data = {"enabled": True}
        return data


class Settings(BaseSettings):
    """
    Application settings, loaded from config files, environment variables, etc.
    """

    song_sheets: SongSheets = Field(default_factory=SongSheets)
    cover: Cover = Field(default_factory=Cover)
    toc: Toc = Field(default_factory=Toc)
    caching: Caching = Field(default_factory=Caching)
    tracing: Tracing = Field(default_factory=Tracing)

    model_config = SettingsConfigDict(
        toml_file=Path(__file__).parent.parent / "config.toml",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            TomlConfigSettingsSource(settings_cls),
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
