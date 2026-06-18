# Reading all song metadata from Firestore (external implementor guide)

This describes how to read **all** song-sheet metadata directly from the
Songbook Generator's Firestore database, for an implementor who has **read
permission** on the database but **cannot reuse any code from this repo**
(e.g. the `ukuleletuesday/songs` explorer site).

Everything here is implemented against Google Firestore's **public APIs**
(REST or any official client SDK) — no project-internal libraries required.

---

## 1. Connection parameters

| Parameter | Value | Source |
|---|---|---|
| GCP project ID | `songbook-generator` | `.env` `GCP_PROJECT_ID`; `config.py:281` default |
| Firestore database | `(default)` in production | `deploy.yaml:178/224/344` — `FIRESTORE_DATABASE` is empty on `main`, so the default DB is used (PR previews use named DBs `pr-<N>`) |
| Database mode | **Firestore Native** | created with `gcloud firestore databases create --type=firestore-native` (`deploy-gcs.sh`) — required; the REST `documents` API does not work in Datastore mode |
| Collection | `song-metadata` | `.env` `SONG_METADATA_FIRESTORE_COLLECTION`; `config.py:251` default |
| Document ID | the Google **Drive file ID** of the song sheet | `metadata_store.py` (`_doc(file_id)`) |
| Region | `europe-west1` | `.env` `GCP_REGION` — irrelevant to reads; the REST endpoint is global |

> The collection is a **top-level** collection (not a sub-collection).
> Resource path: `projects/songbook-generator/databases/(default)/documents/song-metadata`.

---

## 2. Document shape

Each document is one song, keyed by its Drive file ID:

```jsonc
{
  "gdrive_file_id":   "1AbCdEf...",          // string, == document ID
  "gdrive_file_name": "Let It Be - The Beatles", // string
  "properties": {                            // map<string,string>
    "artist": "The Beatles",
    "song": "Let It Be",
    "year": "1970",
    "status": "READY_TO_PLAY",
    "difficulty": "3.5",
    "key": "C",
    "genre": "rock",
    "duration": "185",
    "specialbooks": "regular,complete",
    "tabber": "Mischa"
    // ...etc — see note below
  },
  "metadata_updated_at": "2026-06-18T14:30:00Z" // timestamp
}
```

**Important about `properties`:**

- It is a flat `map<string, string>` — **every value is a string**, even
  numbers, dates and lists. `year` is `"1970"`, `difficulty` is `"3.5"`,
  list-like fields (`genre`, `specialbooks`, `chords`) are
  comma-separated strings. You must coerce/split client-side.
- The **key set is whatever the Drive custom properties had** — it is not a
  fixed schema. Treat unknown keys as optional. Commonly present keys include:
  `artist`, `song`, `year`, `status`, `difficulty`, `difficulty_bin`,
  `tabber`, `duration`, `gender`, `genre`, `key`, `songbooks`,
  `specialbooks`, `song_in_subfolder`, `chords`, `features`, `bpm`,
  `time_signature`, `language`, `ready_to_play_date`, `approved_date`.
- The top-level fields you can rely on are exactly three:
  `gdrive_file_id`, `gdrive_file_name`, `metadata_updated_at`, plus the
  `properties` map.

---

## 3. Permissions / authentication

You need an identity with read access to the database. The minimal IAM role is
**`roles/datastore.viewer`** (read-only); `roles/datastore.user` also works.

OAuth scope required: `https://www.googleapis.com/auth/datastore`
(or `cloud-platform`).

Pick whichever applies:

- **Server-side (recommended):** a service account key, or workload identity /
  ADC. Exchange it for an OAuth2 access token (every official SDK does this for
  you; for raw REST, mint a Bearer token).
- **Quick manual test:** `gcloud auth print-access-token` (uses your gcloud
  identity, which must have the role above).
- **Browser / fully client-side (the explorer case):** you cannot use a GCP
  service account in a browser. You must use the **Firebase Web SDK**, which
  means the project must be registered with Firebase and the `song-metadata`
  collection must be exposed by **Firestore Security Rules** (e.g.
  `allow read: if true;` for a public catalog). The Firebase "API key" is just a
  project identifier, safe to ship; access is governed by the security rules,
  **not** the key. This is a project-side prerequisite, not something the
  implementor can do alone.

---

## 4. Reading every document

### Option A — REST (no SDK, language-agnostic)

List the collection with pagination. The default DB id `(default)` is used
literally in the path.

```
GET https://firestore.googleapis.com/v1/projects/songbook-generator/databases/(default)/documents/song-metadata?pageSize=300
Authorization: Bearer <ACCESS_TOKEN>
```

Response:

```jsonc
{
  "documents": [
    {
      "name": ".../documents/song-metadata/1AbCdEf...",
      "fields": {
        "gdrive_file_id":   { "stringValue": "1AbCdEf..." },
        "gdrive_file_name": { "stringValue": "Let It Be - The Beatles" },
        "properties": {
          "mapValue": {
            "fields": {
              "artist": { "stringValue": "The Beatles" },
              "year":   { "stringValue": "1970" }
              // ...
            }
          }
        },
        "metadata_updated_at": { "timestampValue": "2026-06-18T14:30:00Z" }
      },
      "createTime": "...",
      "updateTime": "..."
    }
    // ...
  ],
  "nextPageToken": "..."   // present only if more pages remain
}
```

Loop: repeat the request adding `&pageToken=<nextPageToken>` until the response
has no `nextPageToken`.

**REST gotcha — the typed-value envelope.** Every field is wrapped in a type
tag (`stringValue`, `timestampValue`, `mapValue` → `fields`). You must unwrap
it. The document ID is the last path segment of `name`.

`curl` smoke test:

```bash
TOKEN=$(gcloud auth print-access-token)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://firestore.googleapis.com/v1/projects/songbook-generator/databases/(default)/documents/song-metadata?pageSize=300"
```

> For a **named** database (e.g. a PR preview), replace `(default)` with the
> database id, e.g. `.../databases/pr-395/documents/song-metadata`.

### Option B — Official client SDK (server-side)

Any language SDK works; you only supply project + database + collection. The
SDK handles auth (ADC), pagination, and value decoding.

**Node.js (`@google-cloud/firestore`):**

```js
const { Firestore } = require('@google-cloud/firestore');
const db = new Firestore({
  projectId: 'songbook-generator',
  databaseId: '(default)',           // or 'pr-395' for a preview DB
});

const snap = await db.collection('song-metadata').get();
const songs = snap.docs.map(d => {
  const data = d.data();
  return {
    id: d.id,                        // Drive file ID
    name: data.gdrive_file_name,
    updatedAt: data.metadata_updated_at, // JS Date
    properties: data.properties || {},   // {string: string}
  };
});
```

**Python (`google-cloud-firestore`):**

```python
from google.cloud import firestore

db = firestore.Client(project="songbook-generator", database="(default)")
songs = []
for doc in db.collection("song-metadata").stream():
    data = doc.to_dict()
    songs.append({
        "id": doc.id,                        # Drive file ID
        "name": data.get("gdrive_file_name"),
        "updated_at": data.get("metadata_updated_at"),
        "properties": data.get("properties", {}),
    })
```

### Option C — Browser (Firebase Web SDK)

Only viable if the project exposes the collection via Firebase + security rules
(see §3). Then:

```js
import { initializeApp } from 'firebase/app';
import { getFirestore, collection, getDocs } from 'firebase/firestore';

const app = initializeApp({ projectId: 'songbook-generator', /* apiKey, etc. */ });
const db = getFirestore(app);           // pass databaseId for a non-default DB
const snap = await getDocs(collection(db, 'song-metadata'));
const songs = snap.docs.map(d => ({ id: d.id, ...d.data() }));
```

---

## 5. Post-processing checklist

1. **Coerce strings.** `Number(properties.year)`, `parseFloat(properties.difficulty)`.
2. **Split list fields** on `,` (`genre`, `specialbooks`, `chords`, `features`).
3. **Treat keys as optional** — do not assume any `properties` key exists.
4. **Join to the PDF (optional).** The document ID is the Drive file ID, which is
   also the cached PDF object key in the public cache bucket:
   `https://storage.googleapis.com/songbook-generator-cache-europe-west1/song-sheets/<docId>.pdf`
   (public-read, 90-day TTL).

---

## 6. Cost & scale

The catalogue is on the order of a few hundred songs, so a full read is a few
hundred document reads — trivially inside Firestore's free tier. But note that
**a full collection scan happens on every read**: if this backs a public,
client-side site, each visitor triggers hundreds of reads. For a browse UI,
prefer reading once and caching, or have the project publish a periodic JSON
snapshot to its public GCS bucket and fetch that instead (single cached HTTP
request, no per-visitor read amplification, no Firebase/security-rules setup).

---

## 7. Caveats / gotchas summary

- Production uses the **default** database; preview environments use **named**
  databases `pr-<N>`. Make the database id configurable.
- The DB must be **Firestore Native** mode for the `documents` REST API — it is.
- Values are **all strings** inside `properties`; there is no typed/array data
  despite some fields being conceptually numbers or lists.
- The **key set is not fixed** — it mirrors whatever Drive custom properties
  existed per song.
- Browser-direct reads require **Firebase + security rules** on the project
  side; an external implementor cannot enable that alone.
