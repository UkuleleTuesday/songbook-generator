"""Song sheet source abstraction: Drive for file existence, Firestore for properties."""

from datetime import datetime
from typing import List, Optional, Union

import click

from .gdrive import GoogleDriveClient
from .metadata_store import SongMetadataStore
from ..worker.models import File
from .filters import FilterGroup, PropertyFilter


class SongSheetSource:
    """Provides song sheet file lists with properties sourced from Drive or Firestore.

    Drive is always used for file existence (id, name, mimeType, parents). When a
    ``metadata_store`` is provided, ``File.properties`` is overlaid from Firestore
    after the Drive file list is fetched, making Firestore the authoritative source
    for metadata, including for filtering. Without a store, Drive properties are
    used unchanged.
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
        modified_after: Optional[datetime] = None,
    ) -> List[File]:
        """Return song sheet files, optionally filtered, with properties from the configured source.

        With a metadata store, the filter runs after the Firestore overlay. Drive
        properties are no longer written (#402), so filtering on them would drop
        any song whose metadata changed since.
        """
        if self._metadata_store is None:
            return self._gdrive.query_drive_files_with_client_filter(
                source_folders, client_filter, modified_after=modified_after
            )

        files = self._gdrive.query_drive_files_with_client_filter(
            source_folders, None, modified_after=modified_after
        )
        self._overlay_properties(files)
        if not client_filter:
            return files

        filtered = [
            f for f in files if client_filter.matches({**f.properties, "name": f.name})
        ]
        click.echo(
            f"Client-side filtering: {len(filtered)} files match out of {len(files)} total"
        )
        return filtered

    def _overlay_properties(self, files: List[File]) -> None:
        all_metadata = self._metadata_store.get_all()
        for file in files:
            if file.id in all_metadata:
                file.properties = all_metadata[file.id].get("properties", {})
