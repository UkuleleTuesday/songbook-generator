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
        self.hydrate(files)
        if not client_filter:
            return files

        filtered = [
            f for f in files if client_filter.matches({**f.properties, "name": f.name})
        ]
        click.echo(
            f"Client-side filtering: {len(filtered)} files match out of {len(files)} total"
        )
        return filtered

    def hydrate(self, files: List[File]) -> None:
        """Replace each file's properties with its Firestore metadata.

        A file with no metadata document is treated as untagged, so property
        filters leave it out. Each one is reported, since it usually means the
        tag updater missed the file (#468).
        """
        all_metadata = self._metadata_store.get_all()
        missing = []
        for file in files:
            doc = all_metadata.get(file.id)
            if doc is None:
                missing.append(file)
                file.properties = {}
            else:
                file.properties = dict(doc.get("properties", {}))
        if missing:
            click.echo(
                f"WARNING: {len(missing)} song sheet(s) have no Firestore metadata "
                "and are treated as untagged:",
                err=True,
            )
            for file in missing:
                click.echo(f"  - {file.name} ({file.id})", err=True)
