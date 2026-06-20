import os
import yaml
from enum import Enum
from functools import lru_cache
from typing import List, Literal, Optional, Union

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


class TocSymbol(str, Enum):
    """A symbol we draw ourselves as a TOC badge (crisp at any size)."""

    PRIDE_FLAG = "pride-flag"


class TocBadge(BaseModel):
    """A single trailing badge on a TOC entry.

    Exactly one kind: inline ``text`` (an emoji/glyph rendered in the TOC font)
    or a ``symbol`` we draw ourselves. They are the same idea — a small mark
    after the title — differing only in how they're rendered.
    """

    text: Optional[str] = None
    symbol: Optional[TocSymbol] = None

    @model_validator(mode="after")
    def _exactly_one_kind(self):
        if (self.text is None) == (self.symbol is None):
            raise ValueError("TocBadge requires exactly one of 'text' or 'symbol'")
        return self


class TocDecoration(BaseModel):
    """A decoration applied to TOC entries whose properties match ``filters``.

    Tints the row with ``color`` and/or appends one or more ``badges`` (inline
    text or drawn symbols) after the title.
    """

    filters: List[Union[FilterGroup, PropertyFilter]]
    color: Optional[tuple[float, float, float]] = None
    """RGB color (0–1 scale) applied to the entire TOC row when this matches."""
    badges: List[TocBadge] = []
    """Trailing badges drawn after the title, in order."""


class Toc(BaseModel):
    columns_per_page: int = 2
    column_width: int = 250
    column_spacing: int = 20
    margin_top: int = 20
    margin_bottom: int = 20
    margin_left: int = 25
    margin_right: int = 25
    title_height: int = 50
    title_margin_bottom: int = 20
    line_spacing: int = 12
    text_font: str = "RobotoCondensed-Regular.ttf"
    page_number_font: str = "RobotoCondensed-SemiBold.ttf"
    text_fontsize: float = 10.0
    title_font: str = "RobotoCondensed-Bold.ttf"
    title_fontsize: int = 16
    max_toc_entry_length: int = 52
    include_difficulty: bool = True
    include_wip_marker: bool = True
    postfixes: Optional[List[TocDecoration]] = None

    @field_validator(
        "*",
        mode="before",
    )
    def empty_str_to_none(cls, v):
        if v == "":
            return None
        return v


class PublishConfig(BaseModel):
    visibility: Literal["public", "unlisted"] = "public"
    pinned: bool = False


class CoverSection(BaseModel):
    """Configuration for the cover section of a songbook edition."""

    file_id: Optional[str] = None


class PrefaceSection(BaseModel):
    """Configuration for the preface section of a songbook edition."""

    file_ids: Optional[List[str]] = None


class PostfaceSection(BaseModel):
    """Configuration for the postface section of a songbook edition."""

    file_ids: Optional[List[str]] = None


class SongsSection(BaseModel):
    """Configuration for the songs section of a songbook edition."""

    filters: List[Union[FilterGroup, PropertyFilter]] = Field(default_factory=list)


class EditionSections(BaseModel):
    """Section-based configuration blocks for a songbook edition."""

    cover: Optional[CoverSection] = None
    preface: Optional[PrefaceSection] = None
    table_of_contents: Optional[Toc] = None
    songs: SongsSection = Field(default_factory=SongsSection)
    postface: Optional[PostfaceSection] = None


class Edition(BaseModel):
    id: str
    title: str
    description: str
    publish: "PublishConfig" = Field(default_factory=PublishConfig)
    sections: EditionSections = Field(default_factory=EditionSections)
    include_difficulty_wheels: bool = True
    use_folder_components: bool = False
    source_file: Optional[str] = None
    inherit_metadata_from_edition: Optional[str] = None

    @property
    def cover_file_id(self) -> Optional[str]:
        """Convenience accessor for sections.cover.file_id."""
        return self.sections.cover.file_id if self.sections.cover else None

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_format(cls, data: object) -> object:
        """Migrate flat legacy fields to the new sections-based format.

        Accepts the old flat structure (``cover_file_id``, ``filters``,
        ``preface_file_ids``, ``postface_file_ids``, ``table_of_contents``
        at the top level) and converts it to the new ``sections``-based
        structure so that existing ``.songbook.yaml`` files hosted in Google
        Drive remain fully backward-compatible without any manual migration.
        """
        if not isinstance(data, dict):
            return data

        sections: dict = data.pop("sections", {})
        if isinstance(sections, dict):
            sections = dict(sections)

        cover_file_id = data.pop("cover_file_id", None)
        if cover_file_id is not None and "cover" not in sections:
            sections["cover"] = {"file_id": cover_file_id}

        preface_ids = data.pop("preface_file_ids", None)
        if preface_ids is not None and "preface" not in sections:
            sections["preface"] = {"file_ids": preface_ids}

        postface_ids = data.pop("postface_file_ids", None)
        if postface_ids is not None and "postface" not in sections:
            sections["postface"] = {"file_ids": postface_ids}

        toc = data.pop("table_of_contents", None)
        if toc is not None and "table_of_contents" not in sections:
            sections["table_of_contents"] = toc

        filters = data.pop("filters", None)
        if filters is not None and "songs" not in sections:
            sections["songs"] = {"filters": filters}

        if sections:
            data["sections"] = sections

        return data


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
        default=True,
        description=(
            "When True, LLM-backed tags (@llm_tag) are computed. "
            "Enabled by default. "
            "Set TAGUPDATER_LLM_TAGGING_ENABLED=false to disable."
        ),
    )


class MetadataStore(BaseModel):
    """Configuration for where song-sheet metadata is written (issue #281).

    Drive and Firestore writes are controlled independently, so the tag updater
    can target Drive only, Firestore only, both, or neither. ``TAGUPDATER_DRY_RUN``
    remains a master override that suppresses all writes.
    """

    firestore_collection: str = Field(
        default="song-metadata",
        description="Firestore collection holding song-sheet metadata documents.",
    )
    drive_write_enabled: bool = Field(
        default=False,
        description=(
            "When True, computed metadata is written back to Google Drive file "
            "properties (the historical behaviour). "
            "Set SONG_METADATA_DRIVE_WRITE_ENABLED=true to enable."
        ),
    )
    firestore_write_enabled: bool = Field(
        default=True,
        description=(
            "When True, computed metadata is written to the Firestore collection. "
            "Set SONG_METADATA_FIRESTORE_WRITE_ENABLED=false to disable."
        ),
    )
    firestore_read_enabled: bool = Field(
        default=True,
        description=(
            "When True, File.properties is sourced from Firestore instead of Drive. "
            "Drive remains the source for file existence (id, name, mimeType, parents). "
            "Set SONG_METADATA_FIRESTORE_READ_ENABLED=false to disable."
        ),
    )


class GoogleCloud(BaseModel):
    project_id: Optional[str] = Field("songbook-generator")
    firestore_database: Optional[str] = Field(
        default=None,
        description=(
            "Firestore database to use. Defaults to the Firestore default database. "
            "Set FIRESTORE_DATABASE to a named database (e.g. 'pr-395') for "
            "isolated preview environments."
        ),
    )
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
    metadata_store: MetadataStore = Field(default_factory=MetadataStore)
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
        if firestore_database_env := os.getenv("FIRESTORE_DATABASE"):
            self.google_cloud.firestore_database = firestore_database_env

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

        # Handle song metadata store settings
        if metadata_collection_env := os.getenv("SONG_METADATA_FIRESTORE_COLLECTION"):
            self.metadata_store.firestore_collection = metadata_collection_env
        if (
            drive_write_env := os.getenv("SONG_METADATA_DRIVE_WRITE_ENABLED")
        ) is not None:
            self.metadata_store.drive_write_enabled = drive_write_env.lower() in (
                "true",
                "1",
            )
        if (
            firestore_write_env := os.getenv("SONG_METADATA_FIRESTORE_WRITE_ENABLED")
        ) is not None:
            self.metadata_store.firestore_write_enabled = (
                firestore_write_env.lower() in ("true", "1")
            )
        if (
            firestore_read_env := os.getenv("SONG_METADATA_FIRESTORE_READ_ENABLED")
        ) is not None:
            self.metadata_store.firestore_read_enabled = firestore_read_env.lower() in (
                "true",
                "1",
            )

        return self

    model_config = SettingsConfigDict(case_sensitive=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
