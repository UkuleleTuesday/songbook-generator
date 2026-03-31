import os
import yaml
from functools import lru_cache
from typing import List, Optional, Union

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

from .filters import FilterGroup, PropertyFilter


class SongSheets(BaseModel):
    folder_ids: List[str] = Field(
        default=[
            "1b_ZuZVOGgvkKVSUypkbRwBsXLVQGjl95",  # UT Song Sheets Google Docs
            "1bvrIMQXjAxepzn4Vx8wEjhk3eQS5a9BM",  # (3) Ready To Play
        ],
    )


class SongbookEditions(BaseModel):
    """Configuration for Drive-based songbook edition discovery."""

    folder_ids: List[str] = Field(
        default=[],
        description=(
            "Drive folder IDs to restrict .songbook.yaml discovery to. "
            "When empty, the search is performed across all of Drive."
        ),
    )


class Cover(BaseModel):
    file_id: Optional[str] = None


class TocPostfix(BaseModel):
    """Configuration for a single TOC entry postfix."""

    postfix: str
    filters: List[Union[FilterGroup, PropertyFilter]]


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
    max_toc_entry_length: int = 52
    include_difficulty: bool = True
    include_wip_marker: bool = True
    postfixes: Optional[List[TocPostfix]] = None

    @field_validator(
        "*",
        mode="before",
    )
    def empty_str_to_none(cls, v):
        if v == "":
            return None
        return v


class Edition(BaseModel):
    id: str
    title: str
    description: str
    cover_file_id: Optional[str] = None
    preface_file_ids: Optional[List[str]] = None
    postface_file_ids: Optional[List[str]] = None
    filters: Optional[List[Union[FilterGroup, PropertyFilter]]] = None
    table_of_contents: Optional[Toc] = None
    use_folder_components: bool = False
    source_file: Optional[str] = None
    inherit_metadata_from_edition: Optional[str] = None

    @model_validator(mode="after")
    def filters_required_without_folder_components(self) -> "Edition":
        if not self.use_folder_components and self.filters is None:
            raise ValueError("filters is required when use_folder_components is False")
        return self


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


class GoogleDriveClientConfig(BaseModel):
    """Configuration for Google Drive client operations."""

    api_retries: int = Field(
        default=3,
        description="Number of retries for Google Drive API calls with exponential backoff",
    )


class TagUpdater(BaseModel):
    """Configuration for the tag updater service."""

    trigger_field: Optional[str] = Field(
        default=None,
        description=(
            "When set, metadata is only written if the value of this field changes. "
            "If unset, any property change triggers a write."
        ),
    )
    dry_run: bool = Field(
        default=False,
        description=(
            "When True, tags are computed but no writes are made to Google Drive. "
            "Set TAGUPDATER_DRY_RUN=true for preview deployments."
        ),
    )
    llm_tagging_enabled: bool = Field(
        default=False,
        description=(
            "When True, LLM-backed tags (@llm_tag) are computed. "
            "Disabled by default as this is an experimental feature. "
            "Set TAGUPDATER_LLM_TAGGING_ENABLED=true to enable."
        ),
    )


class GoogleCloud(BaseModel):
    project_id: Optional[str] = Field("songbook-generator")
    drive_client: GoogleDriveClientConfig = Field(
        default_factory=GoogleDriveClientConfig
    )
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
        "tag-updater": GoogleCloudCredentials(
            principal="songbook-metadata-writer@songbook-generator.iam.gserviceaccount.com",
            scopes=[
                "https://www.googleapis.com/auth/drive.metadata",
                "https://www.googleapis.com/auth/documents.readonly",
            ],
        ),
        "songbook-cache-updater": GoogleCloudCredentials(
            principal="songbook-generator@songbook-generator.iam.gserviceaccount.com",
            scopes=["https://www.googleapis.com/auth/drive.readonly"],
        ),
        "api": GoogleCloudCredentials(
            principal="songbook-generator@songbook-generator.iam.gserviceaccount.com",
            scopes=["https://www.googleapis.com/auth/drive.readonly"],
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
    songbook_editions: SongbookEditions = Field(default_factory=SongbookEditions)
    cover: Cover = Field(default_factory=Cover)
    toc: Toc = Field(default_factory=Toc)
    caching: Caching = Field(default_factory=Caching)
    tracing: Tracing = Field(default_factory=Tracing)
    tag_updater: TagUpdater = Field(default_factory=TagUpdater)
    editions: List[Edition] = Field(default_factory=list)

    @model_validator(mode="before")
    def load_editions_from_yaml(cls, values):
        config_dir = os.path.join(
            os.path.dirname(__file__), "..", "config", "songbooks"
        )
        if os.path.isdir(config_dir):
            editions_data = []
            for filename in sorted(os.listdir(config_dir)):
                if filename.endswith(".yaml") or filename.endswith(".yml"):
                    filepath = os.path.join(config_dir, filename)
                    with open(filepath, "r") as f:
                        edition = yaml.safe_load(f)
                        if edition:
                            edition["source_file"] = filepath
                            editions_data.append(edition)
            if editions_data:
                values["editions"] = editions_data
        return values

    @model_validator(mode="after")
    def apply_env_overrides(self) -> "Settings":
        # Handle Google Cloud settings
        if gcp_project_id_env := (
            os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT_ID")
        ):
            self.google_cloud.project_id = gcp_project_id_env

        # Handle GDRIVE_SONG_SHEETS_FOLDER_IDS
        if folder_ids_env := os.getenv("GDRIVE_SONG_SHEETS_FOLDER_IDS"):
            self.song_sheets.folder_ids = [
                f for f in folder_ids_env.split(",") if f.strip()
            ]

        # Handle GDRIVE_SONGBOOK_EDITIONS_FOLDER_IDS
        if editions_folder_ids_env := os.getenv("GDRIVE_SONGBOOK_EDITIONS_FOLDER_IDS"):
            self.songbook_editions.folder_ids = [
                f for f in editions_folder_ids_env.split(",") if f.strip()
            ]

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

        # Handle Google Drive client settings
        if google_drive_api_retries_env := os.getenv("GOOGLE_DRIVE_API_RETRIES"):
            try:
                self.google_cloud.drive_client.api_retries = int(
                    google_drive_api_retries_env
                )
            except ValueError:
                # Ignore invalid values, keep the default
                pass

        # Handle tag updater settings
        if tagupdater_trigger_field_env := os.getenv("TAGUPDATER_TRIGGER_FIELD"):
            self.tag_updater.trigger_field = tagupdater_trigger_field_env
        if (tagupdater_dry_run_env := os.getenv("TAGUPDATER_DRY_RUN")) is not None:
            self.tag_updater.dry_run = tagupdater_dry_run_env.lower() in ("true", "1")
        if (
            tagupdater_llm_tagging_enabled_env := os.getenv(
                "TAGUPDATER_LLM_TAGGING_ENABLED"
            )
        ) is not None:
            self.tag_updater.llm_tagging_enabled = (
                tagupdater_llm_tagging_enabled_env.lower() in ("true", "1")
            )

        return self

    model_config = SettingsConfigDict(case_sensitive=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
