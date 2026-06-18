# Spike #281 – Firestore for Song-Sheet Metadata

**Issue:** [#281 Tag updater messes with modified time and author](https://github.com/UkuleleTuesday/songbook-generator/issues/281)

**Companion document:** [`281-metadata-storage-analysis.md`](./281-metadata-storage-analysis.md)
already maps the current metadata storage in detail and evaluates four
GCS-centric options (A: GCS object metadata, B: per-file JSON sidecar,
C: shared JSON manifest, D: hybrid) plus GCS Object Contexts. It does **not**
evaluate Firestore. This document fills that gap: it assesses the *benefits and
feasibility* of moving song-sheet metadata into Firestore instead.

---

## 1. Problem Statement

Issue #281 is fundamentally about **decoupling metadata writes from the song-sheet
content**. Today the tag updater writes computed tags back to Drive via
`files().update(body={"properties": …})`
(`generator/tagupdater/tags.py`), which resets `modifiedTime` and
`lastModifyingUser` on every run and breaks the human tab-review workflow.

The fix is to stop writing metadata to Drive and store it somewhere else. The
companion spike proposes GCS-based stores. The question here: **is Firestore a
good fit, and how hard would it be?**

---

## 2. Why Firestore Is a Natural Candidate

Firestore is **already a first-class part of this stack**, which materially
lowers the cost of adopting it for metadata:

| Already in place | Evidence |
|---|---|
| Runtime dependency | `google-cloud-firestore>=2.21.0` in `pyproject.toml` |
| Provisioned in IaC | `deploy-gcs.sh` enables `firestore.googleapis.com`, runs `gcloud firestore databases create --type=firestore-native`, and configures a TTL policy on `expire_at` |
| Client + access patterns established | API (`generator/api/main.py:40`) and worker (`generator/worker/main.py`) both do `firestore.Client(project=project_id)` and use `collection(...).document(id).set/update/get` |
| IAM wired | the service accounts already have Firestore access for job tracking |

So unlike the GCS Object Contexts option (a preview feature with no first-class
Python SDK support as of the companion spike), Firestore needs **no new
infrastructure, dependency, IAM grant, or unfamiliar API** — only a new
collection and a handful of read/write call-site changes.

Firestore is currently used **only** for ephemeral job tracking (documents with
a 30-minute TTL). Using it for durable metadata is a new usage pattern but the
same client and primitives.

---

## 3. What the Metadata Looks Like (recap)

From the companion spike and `scripts/migrate_metadata.py`, the per-song fields are:

- **Computed by the tag updater (every run):** `status`, `chords`, `features`,
  `artist`, `song`, `bpm`, `time_signature`
- **Computed once / dated:** `tabber`, `ready_to_play_date`, `approved_date`
- **LLM-enriched (optional):** `year`, `duration`, `genre`, `language`
- **Human-managed via CLI:** `specialbooks` (comma-separated edition membership)
- **Migration / manual:** `difficulty`, `source`, `gender`, `type`, `date`

Every value is currently a **flat string**, because both Drive custom properties
and GCS object metadata only support `string → string` maps. Drive additionally
caps values at 124 bytes, keys at 30 chars, and 100 properties per file.

Crucially, all of this is carried through the pipeline in **one place** — the
`File.properties: Dict[str, str]` dict on the `File` dataclass
(`generator/worker/models.py:5-13`). Consumers
(`worker/difficulty.py`, `worker/toc.py`, `common/filters.py`) read from this
dict and **do not care where it came from**. This abstraction is the single most
important feasibility fact in this document.

---

## 4. Proposed Firestore Design

**Collection:** e.g. `song-metadata` (one per environment, like the existing
`FIRESTORE_COLLECTION` job collection).

**Document ID:** the Drive file ID — the same key already used for the GCS cache
blob (`song-sheets/<file_id>.pdf`) and the `gdrive-file-id` blob-metadata field.
This makes joins between Drive listing, GCS cache, and Firestore trivial.

**Document shape (illustrative):**

```json
{
  "song": "Let It Be",
  "artist": "The Beatles",
  "status": "READY_TO_PLAY",
  "chords": ["G", "C", "Am", "F"],
  "features": ["chucks", "swing"],
  "bpm": 120,
  "time_signature": "4/4",
  "year": 1970,
  "duration_seconds": 185,
  "genre": ["rock", "pop"],
  "language": "english",
  "difficulty": 3.5,
  "specialbooks": ["regular", "complete"],
  "tabber": "Mischa",
  "ready_to_play_date": "2026-06-18T14:30:00Z",
  "metadata_updated_at": "<server timestamp>"
}
```

Note the **typed values**: numbers, arrays, and timestamps instead of coerced
strings — something neither Drive properties nor GCS object metadata can do.

---

## 5. Benefits

### 5.1 Fully solves #281
The tag updater stops calling `files().update()` on Drive entirely and instead
does `collection("song-metadata").document(file_id).set(doc, merge=True)`.
Drive `modifiedTime` / `lastModifyingUser` are never touched by automated
metadata passes. This is the core requirement, and Firestore meets it as well as
any GCS option.

### 5.2 Real data types (vs flat strings)
- `difficulty` as a `float`, `year`/`bpm` as `int`, `chords`/`genre`/`specialbooks`
  as arrays, dates as real `Timestamp`s.
- Removes the string-coercion that `PropertyFilter.matches` currently works
  around (it does `float(prop_value)` for `gt/gte/lt/lte` and substring matching
  on comma-separated strings for `contains`).
- No 124-byte value cap and no 100-properties-per-file ceiling.

### 5.3 Server-side queries that map cleanly onto existing filters
This is the standout advantage over the GCS options. The companion spike notes
that GCS object metadata supports **no** server-side filtering (Option A's main
weakness), and that GCS Object Contexts (which do) are a preview feature with no
SDK. Firestore offers GA, SDK-backed queries that line up almost 1:1 with the
existing `FilterOperator` enum (`common/filters.py:9-18`):

| `FilterOperator` | Firestore query |
|---|---|
| `EQUALS` / `NOT_EQUALS` | `where(k, "==", v)` / `"!="` |
| `IN` | `where(k, "in", [...])` |
| `GREATER_THAN` etc. | `where(k, ">", v)`, `>=`, `<`, `<=` |
| `CONTAINS` (on a list) | `where(k, "array_contains", v)` |

The `specialbooks` edition-selection filter — today a server-side Drive
`properties has { key='specialbooks' and value='regular' }` query
(`gdrive.py:_build_property_filters`) — becomes
`where("specialbooks", "array_contains", "regular")`, preserving server-side
selection **without** the preview-feature dependency that Object Contexts
requires. (Compound queries need composite indexes, which Firestore can
auto-suggest.)

### 5.4 Atomic per-document writes
Each song is its own document. The tag updater patches exactly one document per
file — no read-modify-write race on a shared object, which is the central
weakness of the Option C single-manifest approach. Concurrent tag-updater and
CLI writes to *different* songs never contend.

### 5.5 Built-in operational features
Per-document `metadata_updated_at` gives the audit signal #281 wants (when did a
tag last change, independent of PDF content). Firestore also offers
point-in-time recovery, change/snapshot listeners (if a future feature needs
push updates), and a generous free tier.

### 5.6 Negligible cost at this scale
The catalogue is on the order of a few hundred songs (`tabdb.csv` ≈ 500 rows). A
full songbook generation reads the whole collection once (~hundreds of document
reads); tag updates write a handful of documents per Drive change. This sits
comfortably inside Firestore's free daily quotas; cost is effectively zero.

---

## 6. Feasibility

### 6.1 Read path — small, localized change
The pipeline already funnels everything through `File.properties`. The minimal
integration keeps **Drive as the source of truth for which files exist** (names,
parents, mimeType — needed for cache keys, shortcut resolution, and deriving
`status` from the parent folder) and **hydrates `properties` from Firestore**
instead of from the Drive `properties` field.

Concretely:
1. `query_drive_files()` / `list_folder_contents()` keep returning `File`
   objects but stop relying on Drive's `properties`.
2. A new step batch-reads the matching Firestore documents
   (one `collection.stream()` or a chunked `get_all`) and populates
   `file.properties` from them.
3. `common/filters.py`, `worker/difficulty.py`, and `worker/toc.py` need **zero
   changes** — they still read `file.properties.get(...)`. (If we expose typed
   values, `filters.py` simplifies, but it is not required.)

The server-side `specialbooks` Drive filter (`_build_property_filters`) is the
one read path that must move; it either becomes a Firestore query (§5.3) or
falls back to the already-existing client-side
`query_drive_files_with_client_filter` path.

### 6.2 Write path — replaces the offending Drive call
- **Tag updater** (`tagupdater/tags.py`): swap the `files().update()` call for a
  Firestore `document(file_id).set(doc, merge=True)`. The existing
  read-modify-write and "skip if unchanged" logic carries over (Firestore `merge`
  handles the merge; an equality check still avoids no-op writes).
- **CLI** `tags set`, `specialbooks add-song/remove-song`
  (`cli/specialbooks.py`, `common/gdrive.py:set_file_property`): write to
  Firestore instead of Drive.
- Some fields are *derived from Drive structure* (`status` ← parent folder,
  `tabber` ← file owner). The tag updater still **reads** Drive to compute them,
  then stores the result in Firestore — no Drive write.

### 6.3 Migration — one-off, low risk
A backfill script reads current Drive properties for every song and writes the
Firestore documents. `scripts/migrate_metadata.py` already enumerates the exact
field set and the Drive-read pattern, so this is a straightforward adaptation.

### 6.4 The real friction: local / offline development
This is the **main feasibility cost**, and where the GCS options have an edge.
Today `songbook-tools cache download` pulls the PDFs *and* their metadata
(via blob metadata / `.metadata.json` sidecars) to the local filesystem, so the
CLI generates songbooks fully offline. Metadata-in-Firestore breaks that unless
we add one of:
- the **Firestore emulator** for local runs (extra setup), or
- a periodic **export of the collection to a JSON file in GCS** that the cache
  download fetches alongside the PDFs (keeps offline parity; the loader reads the
  JSON when Firestore is unreachable).

The export-to-GCS approach is recommended — it preserves today's offline UX and
incidentally gives a git-diffable snapshot of the corpus.

---

## 7. Drawbacks and Risks

- **Local/offline dev regression** unless the emulator or JSON-export mitigation
  (§6.4) is implemented. This is the biggest practical downside relative to
  Option A/B/C, where metadata travels with the cached blob automatically.
- **Two stores to reason about.** Drive remains the source of truth for file
  content and folder structure; Firestore holds metadata. Not a single source of
  truth — but the same is true of every #281 option, since the PDF content must
  stay in Drive regardless.
- **Loss of Drive-UI visibility.** `specialbooks` and other tags are currently
  inspectable in the Drive properties UI. After the move they live only in
  Firestore (inspect via console/CLI). For curated, human-edited fields this is a
  minor workflow change; the fields are already managed exclusively through the
  CLI in practice.
- **Composite indexes** are needed for multi-field server-side queries. Low
  effort (Firestore emits the index definition on first failing query), but it is
  config to maintain.
- **Durable data in a job-tracking database.** The existing collection is
  ephemeral with a TTL; metadata is permanent. Keep them as separate collections
  and ensure the TTL policy is **not** applied to the metadata collection.

---

## 8. Comparison With the Companion Spike's Options

| Criterion | Firestore | A: GCS object metadata | C: GCS JSON manifest | GCS Object Contexts |
|---|---|---|---|---|
| Solves #281 (no Drive write) | ✅ | ✅ | ✅ | ✅ |
| Already provisioned + SDK | ✅ (in use today) | ✅ | ✅ | ❌ preview, no Python SDK |
| Typed / nested values | ✅ | ❌ flat strings | ✅ | ❌ flat strings |
| Server-side filtering | ✅ GA, rich operators | ❌ none | ❌ none | ✅ but preview/equality-only |
| Atomic per-song write | ✅ | ✅ (per blob) | ❌ shared-object race | ✅ |
| Metadata travels with cache (offline dev) | ❌ needs export/emulator | ✅ | ✅ | ✅ |
| Co-located with PDF | ❌ | ✅ | ✅ | ✅ |
| New infra/concepts | low (new collection) | low | low | high |

Firestore wins on **typed data + GA server-side querying + zero new
infrastructure**, and ties on solving #281. It loses on **offline-dev ergonomics
and PDF co-location**, which the GCS options get for free.

---

## 9. Recommendation

**Firestore is a feasible and attractive option, and arguably the cleanest fit
for the *read/query* and *typed-data* concerns** — primarily because it is
already provisioned and the `File.properties` abstraction means downstream
consumers need no changes. It fully resolves #281.

The decisive trade-off is **offline/local-dev parity**: the GCS options keep
metadata co-located with the cached PDFs automatically, whereas Firestore
requires either the emulator or a JSON export-to-GCS step.

Suggested direction if Firestore is chosen:
1. New `song-metadata` collection keyed by Drive file ID, **separate** from the
   TTL'd job collection.
2. Tag updater and CLI write to Firestore; **no** Drive metadata writes.
3. Read path hydrates `File.properties` from Firestore; keep Drive as the source
   of truth for file existence/structure.
4. Replace the `specialbooks` server-side Drive filter with a Firestore query.
5. Add a Firestore→GCS JSON export consumed by `cache download` to preserve
   offline generation.
6. One-off backfill adapted from `scripts/migrate_metadata.py`.

If preserving the current offline-first, cache-co-located workflow with the
*smallest* change is the priority instead, Option A (GCS object metadata) or
Option D (hybrid) from the companion spike remain the lower-friction choices.

---

## 10. Implemented: hydrate + dual-write (first migration step)

The safe, additive first step of the Firestore migration is implemented behind a
flag. It populates Firestore and starts mirroring writes **without** changing the
read path — Drive remains the source of truth, so #281 is not yet resolved (Drive
writes continue) but the Firestore corpus is built and validated in production.

**Components**

- `generator/common/metadata_store.py` — `SongMetadataStore` (Firestore client
  wrapper: `write`, `get`, `get_properties`, `get_all`, `bulk_write`) and a
  `get_metadata_store()` factory. One document per song, keyed by Drive file ID;
  the `properties` map mirrors the Drive custom properties one-to-one.
- `generator/common/config.py` — new `MetadataStore` settings block
  (`firestore_collection`, `dual_write_enabled`).
- `generator/tagupdater/tags.py` — `Tagger` accepts an optional
  `metadata_store`; after each successful Drive `files().update()` it mirrors the
  same `updated_properties` to Firestore. The mirror is **best-effort**: a
  Firestore failure logs a warning and never breaks the Drive write.
- `generator/tagupdater/main.py` and `generator/cli/tags.py` construct the store
  only when dual-write is enabled.
- `generator/cli/metadata.py` — `songbook-tools metadata backfill` hydrates the
  collection from Drive properties (chunked batches; `--dry-run` supported), and
  `metadata get <file_id>` inspects a single document.

**Configuration (env)**

| Variable | Default | Effect |
|---|---|---|
| `SONG_METADATA_FIRESTORE_COLLECTION` | `song-metadata` | Collection holding metadata documents (use a per-PR name in preview envs). |
| `SONG_METADATA_DUAL_WRITE_ENABLED` | `false` | When `true`, the tag updater mirrors every write to Firestore. |

**Dry-run semantics.** `TAGUPDATER_DRY_RUN` suppresses only the **Drive** write
(the #281 problem). The Firestore mirror is the migration *target*, so it still
runs under dry-run. This lets PR preview environments — which deploy the tag
updater with `TAGUPDATER_DRY_RUN=true` — exercise the dual-write into an isolated
per-PR collection without ever touching Drive.

**Deployment.** The tag updater Cloud Function (`.github/workflows/deploy.yaml`)
deploys with `SONG_METADATA_DUAL_WRITE_ENABLED=true`. The collection is
`song-metadata` on `main` and `song-metadata-pr-<N>` on PR previews (same per-PR
isolation pattern as the Pub/Sub topics). No Firestore collection needs explicit
creation — Firestore creates it on first write — and the job-expiry TTL in
`deploy-gcs.sh` is scoped to the `jobs` collection only, so metadata documents
are never expired. The function's runtime service account already has
`roles/datastore.user` (it writes job docs today), so no new IAM grant is
required.

*Known limitation:* per-PR `song-metadata-pr-<N>` collections are not
auto-deleted on PR close (the cleanup job removes functions and topics, and
Firestore has no simple recursive collection delete). They are small and
isolated; a bulk-delete step can be added later if they accumulate.

**Rollout**

1. Deploy with `SONG_METADATA_DUAL_WRITE_ENABLED=false` (no behaviour change).
2. Run `songbook-tools metadata backfill` to hydrate the collection.
3. Set `SONG_METADATA_DUAL_WRITE_ENABLED=true` so new writes stay in sync.
4. Validate parity (Drive properties vs. Firestore `properties`) over time.
5. *(Future)* cut the read path over to Firestore and stop writing to Drive —
   the step that actually resolves #281.

**Not yet done (deliberately):** read-path hydration from Firestore, the
`specialbooks` Firestore query, the offline JSON export, and removal of Drive
writes. Those are the later phases from §9.
