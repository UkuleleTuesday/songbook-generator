"""Song sheet source abstraction: Drive for file existence, Firestore for properties."""

from datetime import datetime
from typing import List, Optional, Union

import click

from .gdrive import GoogleDriveClient
from .metadata_store import SongMetadataStore
from ..worker.models import File
from .filters import FilterGroup, PropertyFilter


class SongSheetSource:
    """Lists song sheets from Drive with their properties from the metadata store."""

    def __init__(self, gdrive: GoogleDriveClient, metadata_store: SongMetadataStore):
        self._gdrive = gdrive
        self._metadata_store = metadata_store

    def collect_files(
        self,
        source_folders: List[str],
        client_filter: Optional[Union[PropertyFilter, FilterGroup]] = None,
        modified_after: Optional[datetime] = None,
    ) -> List[File]:
        """Return song sheet files with Firestore properties, optionally filtered."""
        files = self._gdrive.query_drive_files(
            source_folders, modified_after=modified_after
        )
        missing = self._load_properties(files)
        if missing:
            click.echo(
                f"WARNING: {len(missing)} song sheet(s) have no Firestore metadata "
                "and are treated as untagged:",
                err=True,
            )
            for file in missing:
                click.echo(f"  - {file.name} ({file.id})", err=True)
        if not client_filter:
            return files

        filtered = [
            f for f in files if client_filter.matches({**f.properties, "name": f.name})
        ]
        click.echo(
            f"Client-side filtering: {len(filtered)} files match out of {len(files)} total"
        )
        return filtered

    def list_folder(
        self, folder_id: str, resolve_shortcuts: bool = False
    ) -> List[File]:
        """Return the files in a Drive folder with their properties."""
        files = self._gdrive.list_folder_contents(
            folder_id, resolve_shortcuts=resolve_shortcuts
        )
        self._load_properties(files)
        return files

    def get_files(self, file_ids: List[str]) -> List[File]:
        """Return the files with the given Drive IDs with their properties."""
        files = self._gdrive.get_files_metadata_by_ids(file_ids)
        self._load_properties(files)
        return files

    def _load_properties(self, files: List[File]) -> List[File]:
        """Set each file's properties from the store; return files with no document.

        A file with no document is untagged, so property filters leave it out.
        """
        all_metadata = self._metadata_store.get_all()
        missing = []
        for file in files:
            doc = all_metadata.get(file.id)
            if doc is None:
                missing.append(file)
            file.properties = dict((doc or {}).get("properties", {}))
        return missing
