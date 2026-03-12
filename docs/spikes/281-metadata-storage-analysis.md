# Spike #281 – Metadata Storage Analysis

**Issue:** [#281 Tag updater messes with modified time and author](https://github.com/UkuleleTuesday/songbook-generator/issues/281)

## Problem Statement

Every time the tag updater runs, it calls the Google Drive Files API with a
`files().update()` payload that includes a `properties` body key. The Drive API
treats this as a file modification, which:

1. Resets the file's `modifiedTime` to the current timestamp.
2. Overwrites `lastModifyingUser` with the service account identity.

This makes it impossible for song-sheet reviewers to tell whether the *content*
of a tab has changed, because the timestamp and author are both clobbered by
the automated metadata pass.

---

## 1. How Google Drive File Properties Are Currently Used

### 1.1 Data Model

`generator/worker/models.py` — the central `File` dataclass:

```python
@dataclass
class File:
    id: str
    name: str
    properties: Dict[str, str] = field(default_factory=dict)
    mimeType: Optional[str] = None
    parents: List[str] = field(default_factory=list)
```

All Drive custom properties are carried in the `properties` dict at every stage
of the pipeline.

### 1.2 Properties Written to Drive

#### Tag Updater (automated, root cause of the issue)

**`generator/tagupdater/tags.py` — `Tagger.update_tags()`**

After analysing the Google Doc content, the tagger calls:

```python
self.drive_service.files().update(
    fileId=file.id,
    body={"properties": updated_properties},
    fields="properties",
).execute()
```

This single call is what resets `modifiedTime` and `lastModifyingUser`.

Properties produced automatically:

| Property key | Source | Behaviour |
|---|---|---|
| `status` | Parent folder ID | Written every run |
| `chords` | Bold text in doc body | Written every run |
| `features` | Annotation paragraph | Written every run |
| `artist` | Doc title (right of ` - `) | Written every run |
| `song` | Doc title (left of ` - `) | Written every run |
| `bpm` | Annotation paragraph | Written every run |
| `time_signature` | Annotation paragraph | Written every run |
| `tabber` | File owner display name | Written once (`only_if_unset=True`) |

A read-modify-write pattern is used to preserve any existing properties not
produced by the tagger, and the update is skipped if the computed properties
are identical to the current ones (`update_tags`, lines 193–197).

#### `gdrive.py` — `set_file_property()`

`generator/common/gdrive.py` exposes a general-purpose helper that also uses
`files().update()`. This is invoked by:

- `generator/cli.py` — `tags set` command (manual operator use)
- `generator/cli.py` — `editions add-song` / `editions remove-song` (manages
  the `specialbooks` property)

#### Bulk Migration Script

`scripts/migrate_metadata.py` applies a CSV of metadata to Drive files in bulk,
writing: `artist`, `year`, `difficulty`, `duration`, `language`, `gender`,
`type`, `tabber`, `source`, `date`, `specialbooks`.

### 1.3 Properties Read from Drive

| Location | How | Purpose |
|---|---|---|
| `gdrive.py` `list_drive_files()` (line ~80) | `fields="files(…,properties,…)"` | Populate `File.properties` during folder listing |
| `gdrive.py` `query_drive_files()` (line ~139) | Same `fields` param | Used by cache sync and worker |
| `gdrive.py` `get_file_properties()` (line ~386) | `fields="properties"` only | CLI `tags get`, `editions list` |
| `gdrive.py` `get_files_metadata_by_ids()` (line ~338) | Full file metadata | Preface/postface pages in PDF |
| `gdrive.py` `query_drive_files()` (line ~127) | Server-side `properties has {…}` filter | File selection for editions |
| `worker/toc.py` (lines ~87, ~102, ~109) | `file.properties.get(…)` | Difficulty bin, custom filters, READY_TO_PLAY flag |
| `worker/difficulty.py` (lines ~30, ~39, ~66) | `file.properties.get("difficulty")` | Normalise difficulty across the set |
| `common/gdrive.py` (line ~210) | `client_filter.matches(file.properties)` | Client-side property filtering |

### 1.4 The `specialbooks` Property

Stored as a comma-separated string (e.g. `"regular,complete"`). It is the
primary mechanism for controlling which songs appear in each songbook edition.
It is currently queried server-side via the Drive API property filter syntax:

```
properties has { key='specialbooks' and value='regular' }
```

This property is read-only from the tag updater's perspective — it is managed
exclusively through the `editions` CLI commands.

---

## 2. How GCS Object Metadata Is Currently Used

### 2.1 Writing GCS Blob Metadata

#### During file download / cache population

`generator/common/gdrive.py` — `download_file_stream()` (line ~310):

```python
try:
    self.cache.put(cache_key, data, metadata={"gdrive-file-name": file_name})
except TypeError:
    self.cache.put(cache_key, data)
```

The `gdrive-file-name` key is set as a GCS object custom metadata attribute
whenever a file is downloaded into the cache. The `TypeError` fallback covers
local-filesystem caches that do not support metadata.

#### During cache metadata sync

`generator/cache_updater/sync.py` — `_sync_gcs_metadata_from_drive()`:

Iterates every blob in the `song-sheets/` prefix and writes:

```python
new_metadata["gdrive-file-id"]   = drive_file_id
new_metadata["gdrive-file-name"] = drive_file.name
```

This sync runs as part of `sync_cache()` (unless `--no-metadata` is passed).

#### Cache put helper

`generator/common/caching/localstorage.py` — `LocalStorageCache.put()`:

```python
kwargs = {}
if type(self.fs).__name__ == "GCSFileSystem":
    kwargs["metadata"] = metadata
with self.fs.open(path, "wb", **kwargs) as f:
    f.write(data)
```

The `metadata` kwarg is passed through to `gcsfs` which sets it as the GCS
object's `x-goog-meta-*` headers.

### 2.2 Reading GCS Blob Metadata

`generator/cache_updater/main.py` — `_download_blobs()` (line ~93):

```python
blob_metadata = blob.metadata or {}
song_name = blob_metadata.get("gdrive-file-name", "Unknown Song")
```

The `gdrive-file-name` value is used to label entries in the PDF Table of
Contents. It is the only GCS metadata key that is actively read back.

### 2.3 Current GCS Metadata Keys

| Key | Set by | Read by | Purpose |
|---|---|---|---|
| `gdrive-file-id` | `sync.py` | (not read back in code) | Traceability |
| `gdrive-file-name` | `gdrive.py`, `sync.py` | `cache_updater/main.py` | Song name in TOC |

No other Drive properties (status, chords, artist, etc.) are currently mirrored
into GCS blob metadata.

---

## 3. How JSON Metadata Files Are Currently Used

### 3.1 Writing

`generator/common/caching/localstorage.py` — `put_metadata()`:

```python
def put_metadata(self, key: str, metadata: dict) -> str:
    metadata_key = f"{key}.metadata.json"
    metadata_json = json.dumps(metadata, indent=2)
    return self.put(metadata_key, metadata_json.encode("utf-8"))
```

This produces a sidecar file alongside each cached object, e.g.:

```
song-sheets/abc123.pdf               ← the PDF
song-sheets/abc123.pdf.metadata.json ← {"gdrive-file-id": "abc123", "gdrive-file-name": "Song - Artist"}
```

`put_metadata()` is called in `cache_updater/sync.py` —
`download_gcs_cache_to_local()`:

```python
if with_metadata and blob.metadata:
    local_cache.put_metadata(blob.name, blob.metadata)
```

This only runs when the CLI flag `--with-metadata` is passed to
`download-cache`.

### 3.2 Reading

There is **no code in the current repository that reads `.metadata.json` files
back**. They exist solely as a local-development convenience so operators can
inspect the metadata of a cached file without making API calls. The authoritative
source is the GCS blob metadata in production.

---

## 4. End-to-End Data Flow

```
Google Drive Files
  (custom properties: status, chords, artist, difficulty, specialbooks, …)
         │
         │  [drivewatcher detects change, publishes CloudEvent]
         ▼
Tag Updater Service                ← ⚠️  writes back to Drive here
  1. Fetch file properties from Drive
  2. Fetch Google Doc content
  3. Run @tag functions (status, chords, artist, bpm, …)
  4. Merge with existing properties
  5. If changed → files().update(body={"properties": …})
                              ↑ this resets modifiedTime + lastModifyingUser
         │
         │  [cache_updater.sync_cache() runs on schedule or after drive change]
         ▼
Cache Updater
  1. query_drive_files() → reads all properties from Drive
  2. download_file_stream() → writes PDF to GCS + sets gdrive-file-name metadata
  3. _sync_gcs_metadata_from_drive() → writes gdrive-file-id + gdrive-file-name
         │
         ▼
GCS Cache Bucket  (song-sheets/<file_id>.pdf)
  Blob metadata: {gdrive-file-id, gdrive-file-name}
         │
         │  [worker generates songbook on demand or schedule]
         ▼
Worker / PDF Generator
  1. query_drive_files_with_client_filter()
     → uses file.properties (specialbooks, status, difficulty, …)
     to select + order songs
  2. assign_difficulty_bins() → reads difficulty property
  3. build_toc() → reads difficulty_bin, status properties
  4. download cached PDFs from GCS
  5. merge PDFs into final songbook
```

---

## 5. Summary of Findings

### What writes to Drive (and therefore breaks modified time)

| Component | Trigger | Drive write |
|---|---|---|
| Tag Updater | Pub/Sub CloudEvent from drivewatcher | `files().update({properties: …})` |
| CLI `tags set` | Manual operator | `files().update({properties: …})` |
| CLI `editions add-song` / `remove-song` | Manual operator | `files().update({properties: …})` |
| Migration script | Manual / one-off | `files().update({properties: …})` |

The **tag updater** is the only automated writer and therefore the primary
source of the reported problem.

### What already lives in GCS (not Drive)

Only two fields: `gdrive-file-id` and `gdrive-file-name`. Every other property
(`status`, `chords`, `artist`, `difficulty`, `specialbooks`, etc.) lives
exclusively in Drive custom properties.

### What depends on Drive properties being present on `File` objects

- File selection for a given edition — currently server-filtered by `specialbooks`
- Difficulty normalisation across the song set — reads `difficulty`
- TOC construction — reads `difficulty_bin` and `status`
- Client-side filtering — can filter on any property key

---

## 6. Options for Porting Metadata Away From Drive

### Option A — GCS object metadata (extend current pattern)

Mirror all Drive custom properties onto GCS blob metadata during the cache sync
pass, in addition to the two fields already synced. The tag updater would stop
writing to Drive and instead write to a GCS blob's metadata.

**Pros:**
- Minimal structural change; extends the existing `_sync_gcs_metadata_from_drive`
  pattern.
- Metadata stays co-located with the PDF blob.
- `LocalStorageCache.put()` already supports the `metadata=` kwarg.

**Cons:**
- GCS object metadata is a flat string→string map — same constraint as Drive
  properties.
- Updating metadata requires a `blob.patch()` call (re-reads and patches blob).
- No server-side filtering by GCS metadata; all filtering would become
  client-side (the `query_drive_files_with_client_filter` path already supports
  this).
- `specialbooks` server-side Drive filter would need to be replaced with a GCS
  list-and-filter approach.

### Option B — Separate GCS JSON sidecar file

Store all properties in a per-file JSON object in GCS, e.g.
`song-sheets/<file_id>.properties.json`. The `put_metadata()` helper in
`LocalStorageCache` already implements this pattern for `.metadata.json`.

**Pros:**
- Arbitrary nested structure possible (beyond flat string→string).
- Easy to read and debug locally.
- Can version or append history if needed.
- Already partially implemented (`put_metadata()` / `download_gcs_cache_to_local`).

**Cons:**
- Each file now has two GCS objects to manage.
- Cache invalidation: properties file and PDF file have independent object
  lifecycles.
- More code changes needed across the pipeline to read the JSON sidecar instead
  of `file.properties`.

### Option C — Single shared GCS JSON manifest

One JSON file (e.g. `song-sheets/properties.json`) maps file IDs to their
property dicts. Analogous to the drive watcher's
`drivewatcher/page_token.json` and `drivewatcher/channel_metadata.json` pattern
already in use.

**Pros:**
- Single object to manage; atomic read.
- Easy to version-control the whole metadata corpus in one snapshot.

**Cons:**
- Concurrent writes require careful locking or a compare-and-swap strategy.
- Grows unboundedly as the song catalogue grows.
- Harder to invalidate entries for deleted files.

### Option D — Hybrid: keep `specialbooks` in Drive, move computed tags to GCS

`specialbooks` and other curated properties are intentionally maintained by
humans (and the CLI). Only the *computed* tags (`chords`, `bpm`, `status`,
`artist`, `song`, `time_signature`, `features`) would move to GCS. Human-
managed properties stay on Drive.

**Pros:**
- Preserves Drive server-side filtering for `specialbooks` (used in edition
  selection).
- Smallest change to the human-facing workflow.
- Limits the blast radius — the tag updater is the only automated writer.

**Cons:**
- Two sources of truth for metadata: Drive (human) + GCS (computed).
- Read path must merge properties from both sources.

---

## 7. GCS Object Contexts (preview)

**Object Contexts** is a preview GCS feature that lets you attach key-value
pairs to objects in a dedicated `contexts` field — distinct from the existing
flat custom-metadata (`x-goog-meta-*`) map. Each context entry carries its own
`createTime`, `updateTime`, and `type` fields, and contexts can be queried
server-side when listing objects.

Reference:
<https://cloud.google.com/storage/docs/listing-objects#filter-by-object-contexts>

### How it differs from custom metadata

| Aspect | Custom metadata (`x-goog-meta-*`) | Object Contexts |
|---|---|---|
| Storage field | `metadata` (flat string→string map) | `contexts.custom` (structured per-key) |
| Per-entry audit trail | No | `createTime` + `updateTime` per key |
| Server-side listing filter | No (client-side only) | Yes — `contexts."KEY"="VALUE"` |
| IAM control over writes | Object-level `storage.objects.update` | Fine-grained: `createContext` / `updateContext` / `deleteContext` |
| Lifecycle persistence | Not automatically propagated | Preserved on copy / rewrite / compose / restore |
| Pricing | Included | Free during preview; pricing TBD at GA |

### Data model

Each context key-value pair is stored under `contexts.custom`:

```json
{
  "contexts": {
    "custom": {
      "specialbooks": { "value": "regular,complete" },
      "status":       { "value": "approved" },
      "chords":       { "value": "G,C,Am,F" }
    }
  }
}
```

### Writing contexts

Via the JSON API (`PATCH` the object):

```bash
curl -X PATCH \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "Content-Type: application/json" \
  --data '{"contexts":{"custom":{"specialbooks":{"value":"regular"}}}}' \
  "https://storage.googleapis.com/storage/v1/b/BUCKET/o/OBJECT_NAME"
```

Via the `gcloud alpha` CLI:

```bash
gcloud alpha storage objects update gs://BUCKET/song-sheets/abc123.pdf \
    --update-custom-contexts=specialbooks=regular
```

### Filtering when listing objects

Objects can be filtered by context at list time using the
`filter` query parameter:

```bash
# JSON API
curl -X GET \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  'https://storage.googleapis.com/storage/v1/b/BUCKET/o/?filter=contexts."specialbooks"%3D"regular"'

# gcloud alpha
gcloud alpha storage objects list gs://BUCKET/song-sheets/ \
    --metadata-filter='contexts."specialbooks"="regular"'
```

Supported filter predicates:

| Predicate | Meaning |
|---|---|
| `contexts."KEY":*` | Object has this context key (any value) |
| `contexts."KEY"="VALUE"` | Object has this exact key+value |
| `NOT contexts."KEY":*` | Object does not have this key |
| `NOT contexts."KEY"="VALUE"` | Object does not have this key+value |

### IAM permissions required

| Operation | Permission |
|---|---|
| Create object with contexts | `storage.objects.create` + `storage.objects.createContext` |
| Attach / update / delete contexts | `storage.objects.update` + `createContext` / `updateContext` / `deleteContext` |
| Read contexts | `storage.objects.get` or `storage.objects.list` |

### Status and constraints

- **Public preview** — no SLA; subject to change before GA.
- **Python SDK**: as of March 2026, Object Contexts are only exposed via the
  JSON API and `gcloud alpha`; the `google-cloud-storage` Python library does
  not yet have first-class helpers. Use `blob._patch_with_retries()` or a raw
  `requests` call against the JSON API until the SDK is updated.
- **Filter syntax**: equality and key-existence only; no `OR` across different
  context keys, no range predicates.
- **No predefinition required**: context keys are free-form strings.

### Relevance to this issue

Object Contexts directly address the two weaknesses that affect the other
options:

1. **Server-side filtering** (the gap in Option A): the edition-selection path
   currently uses a Drive `properties has { key='specialbooks' and value='…' }`
   server query. With Object Contexts, the equivalent GCS filter
   `contexts."specialbooks"="regular"` avoids pulling every blob to the client.

2. **Audit trail**: each context key records its own `createTime` and
   `updateTime`, so it is possible to tell when a computed tag last changed
   independently of when the PDF content changed — a cleaner separation of
   concerns than overloading Drive's `modifiedTime`.

Combined with the Option A or Option D approach, the tag updater would:

1. Stop calling `files().update()` on Drive entirely.
2. Write computed tags (`chords`, `bpm`, `status`, `artist`, …) as object
   contexts on the corresponding GCS blob via a `PATCH` request.
3. Mirror human-managed properties (`specialbooks`) from Drive into object
   contexts during the cache-sync pass.
4. Replace the Drive server-side `properties has {…}` query in the worker
   with `gcloud alpha` / JSON API `filter=contexts."specialbooks"="VALUE"`.

This eliminates all automated writes to Drive and resolves the
`modifiedTime` / `lastModifyingUser` corruption, while preserving
server-side filtering performance once the feature reaches GA.
