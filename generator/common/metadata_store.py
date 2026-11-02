"""Firestore-backed store for song-sheet metadata (issue #281).

This is the only source of song metadata. It replaced Google Drive custom file
properties, whose writes reset ``modifiedTime``/``lastModifyingUser`` and broke
tab review (#281); Drive properties are no longer read or written (#481).

Each song is one document keyed by its Drive file ID::

    {
        "gdrive_file_id": "<file id>",
        "gdrive_file_name": "Song - Artist",
        "properties": { ...string key/value tags... },
        "metadata_updated_at": <server timestamp>,
    }

``SongSheetSource`` loads ``properties`` into ``File.properties``.
"""

from __future__ import annotations

from typing import Dict, Iterable, Optional, Tuple

from google.cloud import firestore

from .tracing import get_tracer

tracer = get_tracer(__name__)

# Firestore caps a single batched write at 500 operations.
_BATCH_LIMIT = 500


class SongMetadataStore:
    """Reads and writes song-sheet metadata documents in Firestore."""

    def __init__(self, db: firestore.Client, collection: str):
        self._db = db
        self._collection = collection

    @property
    def collection(self) -> str:
        return self._collection

    def _doc(self, file_id: str):
        return self._db.collection(self._collection).document(file_id)

    def _build_doc(
        self, file_id: str, properties: Dict[str, str], name: Optional[str]
    ) -> dict:
        doc = {
            "gdrive_file_id": file_id,
            "properties": dict(properties),
            "metadata_updated_at": firestore.SERVER_TIMESTAMP,
        }
        if name is not None:
            doc["gdrive_file_name"] = name
        return doc

    def write(
        self,
        file_id: str,
        properties: Dict[str, str],
        *,
        name: Optional[str] = None,
    ) -> None:
        """Upsert a single song's metadata document (merge semantics)."""
        with tracer.start_as_current_span("metadata_store.write") as span:
            span.set_attribute("file.id", file_id)
            span.set_attribute("properties_count", len(properties))
            self._doc(file_id).set(
                self._build_doc(file_id, properties, name), merge=True
            )

    def delete_property(self, file_id: str, key: str) -> bool:
        """Remove a single key from the properties map. Returns False if doc missing."""
        with tracer.start_as_current_span("metadata_store.delete_property") as span:
            span.set_attribute("file.id", file_id)
            span.set_attribute("property.key", key)
            doc_ref = self._doc(file_id)
            if not doc_ref.get().exists:
                return False
            doc_ref.update(
                {
                    f"properties.{key}": firestore.DELETE_FIELD,
                    "metadata_updated_at": firestore.SERVER_TIMESTAMP,
                }
            )
            return True

    def get(self, file_id: str) -> Optional[dict]:
        """Return the full stored document for ``file_id``, or None."""
        snapshot = self._doc(file_id).get()
        if not snapshot.exists:
            return None
        return snapshot.to_dict()

    def get_properties(self, file_id: str) -> Optional[Dict[str, str]]:
        """Return just the mirrored Drive ``properties`` map, or None."""
        data = self.get(file_id)
        if data is None:
            return None
        return data.get("properties", {})

    def get_all(self) -> Dict[str, dict]:
        """Return every metadata document keyed by Drive file ID."""
        return {
            snap.id: snap.to_dict()
            for snap in self._db.collection(self._collection).stream()
        }

    def bulk_write(
        self, items: Iterable[Tuple[str, Dict[str, str], Optional[str]]]
    ) -> int:
        """Upsert many documents using chunked Firestore batches.

        ``items`` yields ``(file_id, properties, name)`` tuples. Returns the
        number of documents written.
        """
        with tracer.start_as_current_span("metadata_store.bulk_write") as span:
            count = 0
            pending = 0
            batch = self._db.batch()
            for file_id, properties, name in items:
                batch.set(
                    self._doc(file_id),
                    self._build_doc(file_id, properties, name),
                    merge=True,
                )
                pending += 1
                count += 1
                if pending >= _BATCH_LIMIT:
                    batch.commit()
                    batch = self._db.batch()
                    pending = 0
            if pending:
                batch.commit()
            span.set_attribute("documents_written", count)
            return count


def get_metadata_store(
    collection: Optional[str] = None,
    *,
    project_id: Optional[str] = None,
    database: Optional[str] = None,
    db: Optional[firestore.Client] = None,
) -> SongMetadataStore:
    """Build a :class:`SongMetadataStore` from settings/env.

    ``db`` can be injected for tests; otherwise a real Firestore client is
    created. ``collection`` and ``database`` default to the configured values.
    """
    from .config import get_settings

    settings = get_settings()
    collection = collection or settings.metadata_store.firestore_collection
    if db is None:
        db = firestore.Client(
            project=project_id or settings.google_cloud.project_id,
            database=database or settings.google_cloud.firestore_database,
        )
    return SongMetadataStore(db=db, collection=collection)
