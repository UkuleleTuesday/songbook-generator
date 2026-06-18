"""Tests for the Firestore-backed song metadata store.

Uses a small in-memory fake that mimics the subset of the Firestore client API
the store relies on (collection/document/set/get/stream + batched writes), so no
emulator or network is required.
"""

from google.cloud import firestore

from .metadata_store import SongMetadataStore


class _FakeSnapshot:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data

    @property
    def exists(self):
        return self._data is not None

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class _FakeDocRef:
    def __init__(self, store, collection, doc_id):
        self._store = store
        self._collection = collection
        self._id = doc_id

    def set(self, data, merge=False):
        bucket = self._store.setdefault(self._collection, {})
        if merge and self._id in bucket:
            merged = dict(bucket[self._id])
            merged.update(data)
            bucket[self._id] = merged
        else:
            bucket[self._id] = dict(data)

    def get(self):
        bucket = self._store.get(self._collection, {})
        return _FakeSnapshot(self._id, bucket.get(self._id))


class _FakeCollection:
    def __init__(self, store, name):
        self._store = store
        self._name = name

    def document(self, doc_id):
        return _FakeDocRef(self._store, self._name, doc_id)

    def stream(self):
        for doc_id, data in self._store.get(self._name, {}).items():
            yield _FakeSnapshot(doc_id, data)


class _FakeBatch:
    def __init__(self):
        self._ops = []

    def set(self, ref, data, merge=False):
        self._ops.append((ref, data, merge))

    def commit(self):
        for ref, data, merge in self._ops:
            ref.set(data, merge=merge)
        self._ops = []


class FakeFirestore:
    def __init__(self):
        self.data = {}

    def collection(self, name):
        return _FakeCollection(self.data, name)

    def batch(self):
        return _FakeBatch()


def _make_store():
    return SongMetadataStore(db=FakeFirestore(), collection="song-metadata")


def test_write_builds_expected_document():
    store = _make_store()
    store.write("file1", {"artist": "Queen", "status": "APPROVED"}, name="Song - Queen")

    doc = store.get("file1")
    assert doc["gdrive_file_id"] == "file1"
    assert doc["gdrive_file_name"] == "Song - Queen"
    assert doc["properties"] == {"artist": "Queen", "status": "APPROVED"}
    # A server-timestamp sentinel is recorded for the write time.
    assert doc["metadata_updated_at"] is firestore.SERVER_TIMESTAMP


def test_write_merges_and_preserves_existing_fields():
    store = _make_store()
    store.write("file1", {"artist": "Queen"}, name="orig")
    store.write("file1", {"artist": "Queen", "year": "1975"})

    doc = store.get("file1")
    # name from the first write is preserved (merge semantics)...
    assert doc["gdrive_file_name"] == "orig"
    # ...and the latest properties map is stored.
    assert doc["properties"] == {"artist": "Queen", "year": "1975"}


def test_get_missing_returns_none():
    store = _make_store()
    assert store.get("nope") is None
    assert store.get_properties("nope") is None


def test_get_properties_returns_only_the_properties_map():
    store = _make_store()
    store.write("file1", {"artist": "ABBA"}, name="x")
    assert store.get_properties("file1") == {"artist": "ABBA"}


def test_get_all_returns_every_document_keyed_by_id():
    store = _make_store()
    store.write("a", {"artist": "A"}, name="a")
    store.write("b", {"artist": "B"}, name="b")

    all_docs = store.get_all()
    assert set(all_docs) == {"a", "b"}
    assert all_docs["a"]["properties"] == {"artist": "A"}


def test_bulk_write_writes_all_documents():
    store = _make_store()
    items = [(f"id{i}", {"n": str(i)}, f"name{i}") for i in range(10)]

    written = store.bulk_write(items)

    assert written == 10
    all_docs = store.get_all()
    assert len(all_docs) == 10
    assert all_docs["id7"]["properties"] == {"n": "7"}
    assert all_docs["id7"]["gdrive_file_name"] == "name7"


def test_bulk_write_chunks_beyond_batch_limit(monkeypatch):
    import generator.common.metadata_store as ms

    monkeypatch.setattr(ms, "_BATCH_LIMIT", 3)
    store = _make_store()
    items = [(f"id{i}", {"n": str(i)}, None) for i in range(7)]

    written = store.bulk_write(items)

    assert written == 7
    assert len(store.get_all()) == 7
