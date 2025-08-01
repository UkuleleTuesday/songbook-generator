import os
from functools import lru_cache
from typing import List, Optional

from pydantic import (
    BaseModel,
    Field,
    field_validator,
    model_validator,
)
from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
)


class SongSheets(BaseModel):
    folder_ids: List[str] = Field(
        default=[
            "1b_ZuZVOGgvkKVSUypkbRwBsXLVQGjl95",  # UT Song Sheets Google Docs
            "1bvrIMQXjAxepzn4Vx8wEjhk3eQS5a9BM",  # (3) Ready To Play
        ],
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
    worker_cache_bucket: Optional[str] = Field("songbook-generator-cache-europe-west1")
    region: Optional[str] = Field(None)


class CachingLocal(BaseModel):
    enabled: bool = Field(True)
    dir: Optional[str] = Field(
        os.path.join(os.path.expanduser("~/.cache"), "songbook-generator")
    )


class Caching(BaseModel):
    use_gcs: Optional[bool] = None
    gcs: CachingGcs = Field(default_factory=CachingGcs)
    local: CachingLocal = Field(default_factory=CachingLocal)


class GoogleCloudCredentials(BaseModel):
    principal: str
    scopes: List[str]


class GoogleCloud(BaseModel):
    project_id: Optional[str] = Field("songbook-generator")
    credentials: dict[str, GoogleCloudCredentials] = {
        "songbook-generator": GoogleCloudCredentials(
            principal="songbook-generator@songbook-generator.iam.gserviceaccount.com",
            scopes=[
                "https://www.googleapis.com/auth/drive",
                "https://www.googleapis.com/auth/documents",
            ],
        ),
        "songbook-metadata-writer": GoogleCloudCredentials(
            principal="songbook-metadata-writer@songbook-generator.iam.gserviceaccount.com",
            scopes=["https://www.googleapis.com/auth/drive.metadata"],
        ),
    }


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
    Application settings, loaded from environment variables.
    """

    google_cloud: GoogleCloud = Field(default_factory=GoogleCloud)
    song_sheets: SongSheets = Field(default_factory=SongSheets)
    cover: Cover = Field(default_factory=Cover)
    toc: Toc = Field(default_factory=Toc)
    caching: Caching = Field(default_factory=Caching)
    tracing: Tracing = Field(default_factory=Tracing)

    @model_validator(mode="after")
    def apply_env_overrides(self) -> "Settings":
        # Handle Google Cloud settings
        if gcp_project_id_env := (
            os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT_ID")
        ):
            self.google_cloud.project_id = gcp_project_id_env

        # Handle GDRIVE_SONG_SHEETS_FOLDER_IDS
        if folder_ids_env := os.getenv("GDRIVE_SONG_SHEETS_FOLDER_IDS"):
            self.song_sheets.folder_ids = folder_ids_env.split(",")

        # Handle GCS cache settings
        if gcs_bucket_env := os.getenv("GCS_WORKER_CACHE_BUCKET"):
            self.caching.gcs.worker_cache_bucket = gcs_bucket_env
        if gcp_region_env := os.getenv("GCP_REGION"):
            self.caching.gcs.region = gcp_region_env

        # Handle local cache settings
        if (local_cache_enabled_env := os.getenv("LOCAL_CACHE_ENABLED")) is not None:
            self.caching.local.enabled = local_cache_enabled_env.lower() in (
                "true",
                "1",
            )
        if local_cache_dir_env := os.getenv("LOCAL_CACHE_DIR"):
            self.caching.local.dir = local_cache_dir_env

        return self

    model_config = SettingsConfigDict(case_sensitive=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
