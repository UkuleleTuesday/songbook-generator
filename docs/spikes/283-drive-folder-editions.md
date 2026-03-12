# 283 – Drive-folder-based songbook editions

## Problem statement

The current approach to creating a new songbook edition requires a developer to:

1. Clone the repository.
2. Add a YAML file to `generator/config/songbooks/` with the correct schema.
3. Commit and merge the change so the edition is picked up by the generation
   pipeline.

This is a friction-heavy, code-centric workflow.  The hypothesis explored here
is that a simpler, more accessible alternative exists: let a non-technical user
configure a songbook edition **entirely through a Google Drive folder**.

---

## Findings

### Current edition model

Each edition is defined by a YAML file (`generator/config/songbooks/*.yaml`)
containing:

| Field | Purpose |
|---|---|
| `id`, `title`, `description` | Identity metadata |
| `cover_file_id` | Drive file ID for the cover page |
| `preface_file_ids` | Ordered list of Drive IDs for preface pages |
| `postface_file_ids` | Ordered list of Drive IDs for postface pages |
| `filters` | Property-based filter expressions that select which songs from the global song-sheets folders are included |
| `table_of_contents` | Optional TOC layout overrides |

The filters approach requires knowledge of the Drive file property schema
(`specialbooks`, `status`, etc.) which is invisible to end-users in the Drive
UI.

### Drive folder approach

A Drive folder already provides a natural container for a songbook edition.
Key observations:

- **Google Drive shortcuts** (`mimeType =
  application/vnd.google-apps.shortcut`) let a user place a reference to an
  existing tab file into any folder without duplicating the PDF.  The shortcut
  retains its own display name and can be renamed independently of the original.
- Drive folder listing (via `files.list` with `'<folderId>' in parents`) returns
  both regular files and shortcuts in a single call.  Shortcuts expose a
  `shortcutDetails.targetId` and `shortcutDetails.targetMimeType` field.
- File ordering within a folder can be controlled by naming convention since
  Drive's `orderBy=name` sorts lexicographically.

### Naming convention for special files

To distinguish structural pages (cover, preface, postface) from song content
without requiring any Drive property metadata, a simple **filename prefix
convention** is sufficient:

| Prefix (case-insensitive) | Role |
|---|---|
| `_cover…` | Cover page – the alphabetically first matching file is used |
| `_preface…` | Preface pages – all matching files, sorted alphabetically |
| `_postface…` | Postface pages – all matching files, sorted alphabetically |
| *(anything else)* | Song body files, sorted with the standard song sort key |

Examples of valid folder contents:

```
My Special Songbook/
├── _cover.gdoc
├── _preface - Welcome note.gdoc
├── Amazing Grace - Traditional.pdf       ← direct PDF
├── Don't Stop Me Now - Queen.pdf         ← shortcut to the file in the main tab library
├── Wonderwall - Oasis.pdf                ← shortcut
└── _postface - Credits.gdoc
```

Because shortcuts resolve to the target file's ID and MIME type, the downstream
download logic in `GoogleDriveClient.download_file_stream` works unchanged.
The shortcut's display name (e.g. `Don't Stop Me Now - Queen.pdf`) is used for
sorting and for matching against the merged-PDF table of contents.

### Integration with the existing pipeline

The existing `generate_songbook` function already accepts:

- A pre-determined `cover_file_id`
- `preface_file_ids` / `postface_file_ids` (resolved to `File` objects
  internally)
- The songs to include (previously derived from Drive property filters)

The only missing piece was a way to pass **pre-determined song files** so the
Drive query step could be skipped.  Adding an optional `files` parameter to
`generate_songbook` (when supplied, the query step is bypassed) completes the
integration with zero breaking changes to the existing edition-based workflow.

The new `generate_songbook_from_drive_folder` function ties it all together:

```
list_folder_contents(folder_id)
    → categorize_folder_files(all_files)
        → { cover, preface, songs, postface }
            → generate_songbook(files=songs, cover_file_id=…, …)
```

### Cache dependency

The songs in the edition folder must already be present in the merged-PDF cache
(`merged-pdf/latest.pdf` in GCS).  This cache is built from all files in the
main song-sheets source folders.  For the folder-based approach to work, every
song referenced (directly or via shortcut) must have been synced into the
cache.

In practice this is satisfied for Ukulele Tuesday because:
1. All tabs live in the shared Drive song-sheets folders which are already
   synced to GCS.
2. Shortcuts resolve to the same Drive file IDs, so their cache entries
   already exist.

If a user adds a _brand-new_ tab only to their edition folder (not in the main
song-sheets folders), it will not be in the cache and generation will fail with
a `PdfCacheMissException`.  A future improvement could auto-sync missing files
on demand.

---

## Options

### Option A – Folder as edition (this spike) ✅

**How it works**: A Drive folder _is_ the edition.  No YAML file needed.
Cover / preface / postface identified by naming convention.  Songs = everything
else (direct files or shortcuts).  A new CLI command and `generate_songbook_from_drive_folder`
function expose the capability.

**CLI usage**:
```bash
uv run songbook-tools generate-from-folder <FOLDER_ID> \
    --title "My Special Songbook" \
    --destination-path out/my-special.pdf
```

**Pros**:
- Zero technical setup for end-users – create a folder in Drive, add files and
  shortcuts, run the command.
- Works with existing cache and download infrastructure.
- Shortcuts avoid file duplication across editions.
- Naming convention is intuitive and Drive-native.
- Fully backward-compatible: existing YAML-based editions continue to work.

**Cons / open questions**:
- TOC layout cannot yet be configured per-folder edition (no equivalent of
  the `table_of_contents` YAML block).  Could be addressed with a `_config.json`
  or `_config.toml` metadata file in the folder.
- No title/description auto-detection from the folder name yet (the caller must
  supply `--title`; a sensible default could be the folder name fetched via
  `drive.files().get`).
- Requires songs to already be in the merged-PDF cache.  A future improvement
  could trigger an on-demand sync for missing files.
- The pipeline currently uses the song's `name` as its cache lookup key, which
  is the shortcut's display name.  If a user renames a shortcut, the lookup will
  fail until the cache is rebuilt.

### Option B – Folder-triggered YAML generation

**How it works**: A background service watches a designated "edition config"
Drive folder.  When the user creates a subfolder there, it auto-generates a YAML
edition file and commits it to the repo.

**Pros**: Keeps the existing YAML-based model; non-technical users only touch
Drive.

**Cons**: More infrastructure complexity; requires a GitHub integration; slower
feedback loop (PR / CI must complete before the edition is usable).

### Option C – Google Sheets as edition config

**How it works**: A shared Google Sheet lists edition IDs and their
configuration.  The generator reads it at build time.

**Pros**: Familiar spreadsheet UI for non-technical users; easy to add new
editions by adding a row.

**Cons**: Requires a Sheets API integration; ordering of songs still requires
explicit IDs or a separate filter; no support for shortcuts.

---

## Recommendation

**Option A is a good starting point** and has been implemented as part of this
spike.  It delivers the core hypothesis (Drive-only configuration, no code
changes needed to create an edition) with minimal complexity.

The natural next steps are:

1. Auto-derive the edition title from the Drive folder name.
2. Support an optional `_config.toml` in the folder for TOC overrides.
3. Explore surfacing `generate-from-folder` as an API/worker job so non-CLI
   users can trigger generation from the UI.
4. Handle the cache-miss case by triggering a targeted sync before generation.
