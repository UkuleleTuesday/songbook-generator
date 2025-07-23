import os
from functools import lru_cache
from pathlib import Path
from typing import List, Tuple

from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

DEFAULT_LOCAL_CACHE_DIR = os.path.join(
    os.path.expanduser("~/.cache"), "songbook-generator"
)


class SongSheets(BaseModel):
    folder_ids: List[str] = Field(
        default=[
            "1b_ZuZVOGgvkKVSUypkbRwBsXLVQGjl95",  # UT Song Sheets Google Docs
            "1bvrIMQXjAxepzn4Vx8wEjhk3eQS5a9BM",  # (3) Ready To Play
        ]
    )


class Cover(BaseModel):
    file_id: str = "1HB1fUAY3uaARoHzSDh2TymfvNBvpKOEE221rubsjKoQ"


class Settings(BaseSettings):
    """
    Application settings, loaded from config files, environment variables, etc.
    """

    song_sheets: SongSheets = Field(default_factory=SongSheets)
    cover: Cover = Field(default_factory=Cover)

    model_config = SettingsConfigDict(
        env_prefix="SONGBOOK_",
        env_nested_delimiter="__",
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


def get_local_cache_dir():
    local_cache_dir = os.getenv("LOCAL_CACHE_DIR", DEFAULT_LOCAL_CACHE_DIR)
    return local_cache_dir
