"""Song sheet source abstraction: Drive for file existence, Firestore for properties."""

from typing import List, Optional, Union

from .gdrive import GoogleDriveClient
from .metadata_store import SongMetadataStore
from ..worker.models import File
from .filters import FilterGroup, PropertyFilter


class SongSheetSource:
    """Provides song sheet file lists with properties sourced from Drive or Firestore.

    Drive is always used for file existence (id, name, mimeType, parents). When a
    ``metadata_store`` is provided, ``File.properties`` is overlaid from Firestore
    after the Drive file list is fetched, making Firestore the authoritative source
    for metadata. Without a store, Drive properties are used unchanged.
    """

    def __init__(
        self,
        gdrive: GoogleDriveClient,
        metadata_store: Optional[SongMetadataStore] = None,
    ):
        self._gdrive = gdrive
        self._metadata_store = metadata_store

    def collect_files(
        self,
        source_folders: List[str],
        client_filter: Optional[Union[PropertyFilter, FilterGroup]] = None,
    ) -> List[File]:
        """Return song sheet files, optionally filtered, with properties from the configured source.

        Drive and Firestore mirror properties 1:1, so client-side filtering (which
        uses properties) produces the same result regardless of which source is active.
        """
        files = self._gdrive.query_drive_files_with_client_filter(
            source_folders, client_filter
        )
        if self._metadata_store is not None:
            self._overlay_properties(files)
        return files

    def _overlay_properties(self, files: List[File]) -> None:
        all_metadata = self._metadata_store.get_all()
        for file in files:
            if file.id in all_metadata:
                file.properties = all_metadata[file.id].get("properties", {})
