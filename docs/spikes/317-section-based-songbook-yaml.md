# 317 – Improved songbook.yaml structure with section-based blocks

## Problem statement

The current `songbook.yaml` schema places all edition configuration fields at
the top level:

```yaml
id: "current"
title: "Ukulele Tuesday - Current Songbook"
description: "..."
cover_file_id: "1rxn4Kl6..."
preface_file_ids:
  - "1ZxYst-..."
filters:
  - key: "specialbooks"
    operator: "contains"
    value: "regular"
table_of_contents:
  postfixes:
    - postfix: " ☘"
      filters:
        - key: "specialbooks"
          operator: "contains"
          value: "ireland"
```

As the number of edition options grows, this flat structure becomes hard to
read, hard to extend, and makes the relationships between fields implicit.
For example, `filters` (which selects songs) sits at the same level as
`table_of_contents` (which only controls rendering), and `cover_file_id` sits
alongside identity fields such as `id` and `title` even though it is strictly
a content/layout concern.

The hypothesis explored here is that grouping configuration into explicit
**section blocks** improves clarity, reduces ambiguity, and provides a natural
extension point for future per-section features.

---

## Proposed new structure

```yaml
id: "current"
title: "Ukulele Tuesday - Current Songbook"
description: "..."
sections:
  cover:
    file_id: "1rxn4Kl6..."
  preface:
    file_ids:
      - "1ZxYst-..."
  table_of_contents:
    postfixes:
      - postfix: " ☘"
        filters:
          - key: "specialbooks"
            operator: "contains"
            value: "ireland"
  songs:
    filters:
      - key: "specialbooks"
        operator: "contains"
        value: "regular"
  postface:
    file_ids:
      - "1Abc123..."
```

### Section inventory

| Section | Fields | Purpose |
|---|---|---|
| `cover` | `file_id` | Single Drive file ID for the cover page |
| `preface` | `file_ids` | Ordered Drive file IDs prepended before the TOC |
| `table_of_contents` | all existing `Toc` fields + `postfixes` | TOC rendering / layout settings |
| `songs` | `filters` | Property-based filter expressions that select which songs are included |
| `postface` | `file_ids` | Ordered Drive file IDs appended after the song pages |

All configuration that varies per-edition now lives under `sections`.  The only
remaining top-level fields are the identity fields (`id`, `title`,
`description`) and the operational flag `use_folder_components`.

---

## Implementation

### New Pydantic models (`generator/common/config.py`)

Five new models were added:

```python
class CoverSection(BaseModel):
    file_id: Optional[str] = None

class PrefaceSection(BaseModel):
    file_ids: Optional[List[str]] = None

class PostfaceSection(BaseModel):
    file_ids: Optional[List[str]] = None

class SongsSection(BaseModel):
    filters: List[Union[FilterGroup, PropertyFilter]] = Field(default_factory=list)

class EditionSections(BaseModel):
    cover: Optional[CoverSection] = None
    preface: Optional[PrefaceSection] = None
    table_of_contents: Optional[Toc] = None
    songs: SongsSection = Field(default_factory=SongsSection)
    postface: Optional[PostfaceSection] = None
```

The `Edition` model was updated to replace all the flat fields with a single
`sections: EditionSections` field.  A `cover_file_id` property is retained on
`Edition` as a convenience accessor (`sections.cover.file_id`) so that all
downstream code and tests continue to work without modification.

### Backward compatibility migration

A `model_validator(mode="before")` on `Edition` automatically migrates old
flat-format YAML to the new sections structure at parse time:

```python
@model_validator(mode="before")
@classmethod
def migrate_legacy_format(cls, data):
    sections = data.pop("sections", {})
    # cover_file_id → sections.cover.file_id
    if (fid := data.pop("cover_file_id", None)) and "cover" not in sections:
        sections["cover"] = {"file_id": fid}
    # preface_file_ids → sections.preface.file_ids
    if (ids := data.pop("preface_file_ids", None)) and "preface" not in sections:
        sections["preface"] = {"file_ids": ids}
    # postface_file_ids → sections.postface.file_ids
    if (ids := data.pop("postface_file_ids", None)) and "postface" not in sections:
        sections["postface"] = {"file_ids": ids}
    # table_of_contents → sections.table_of_contents
    if (toc := data.pop("table_of_contents", None)) and "table_of_contents" not in sections:
        sections["table_of_contents"] = toc
    # filters → sections.songs.filters
    if (filters := data.pop("filters", None)) and "songs" not in sections:
        sections["songs"] = {"filters": filters}
    if sections:
        data["sections"] = sections
    return data
```

This means existing `.songbook.yaml` files hosted in Google Drive work without
any changes.

### Config YAML files updated

All five config-managed editions were migrated to the new format:

- `generator/config/songbooks/current.yaml`
- `generator/config/songbooks/complete.yaml`
- `generator/config/songbooks/wexford-2026.yaml`
- `generator/config/songbooks/womens-2026.yaml`
- `generator/config/songbooks/ukulele-hooley-2025.yaml`

### Downstream code updated

| File | Change |
|---|---|
| `generator/worker/pdf.py` | `generate_songbook_from_edition`, `_resolve_folder_components`, `_build_generation_manifest` use `edition.sections.*` |
| `generator/cli/editions.py` | `_edition_to_yaml_bytes` strips `sections.preface`/`sections.postface` when `use_folder_components=True`; filter access updated |
| `generator/cli/songs.py` | Filter lookup updated to `edition.sections.songs.filters` |

---

## Options considered

### Option A – Section-based blocks at the `sections` key (this spike) ✅

**How it works**: A top-level `sections` key contains named sub-keys
(`preface`, `table_of_contents`, `songs`, `postface`).  A migration validator
converts old flat files transparently.

**Pros**:
- Explicit grouping makes relationships obvious.
- Each section is independently optional with clean defaults.
- Natural extension point: new per-section fields can be added without
  polluting the top-level namespace.
- Fully backward-compatible: old flat files continue to work via the migration
  validator.
- Enables per-section feature additions in the future (e.g. `songs.sort_by`,
  `preface.include_cover_in_toc`, `table_of_contents.enabled: false`).

**Cons**:
- More nesting depth; simple editions have slightly more boilerplate.
- Existing hand-written `.songbook.yaml` files in Drive will still parse, but
  produce the new structure when re-serialized by the CLI.

### Option B – Keep flat structure, add typed sub-models only internally

**How it works**: Leave the YAML schema unchanged; only reorganize the internal
Python models.

**Pros**: Zero YAML migration required.

**Cons**: The flat schema problem remains visible to users who write YAML by
hand or inspect Drive-hosted files.  Internal refactoring without user benefit.

### Option C – Rename fields without grouping (e.g. `songs_filters`, `preface_file_ids`)

**How it works**: Replace `filters` with `songs_filters`, `preface_file_ids`
stays, etc.

**Pros**: Single-level; no nesting.

**Cons**: Does not solve the scalability problem; adding new song-selection
options (e.g. `songs_sort_by`, `songs_limit`) still pollutes the top level.

---

## Findings

### Backward compatibility is straightforward

The Pydantic `model_validator(mode="before")` hook cleanly separates the
migration concern from the model definition.  Old files parsed via
`Edition.model_validate(yaml_data)` are migrated transparently; no
call-site changes are needed in the worker or CLI.

### Drive-hosted files remain valid

The migration validator runs any time an `Edition` is constructed from a dict
(the typical path via `yaml.safe_load`).  Files in Google Drive with the old
flat format continue to work without requiring a manual migration in Drive.

### Re-serialization reflects new structure

When the CLI serializes an edition back to YAML (e.g. during
`editions convert`), the output uses the new `sections` structure.  Users who
inspect or edit the re-uploaded `.songbook.yaml` will see the new format.

### The `filters` rename is the most user-visible change

Moving `filters` under `sections.songs.filters` is the change most likely to
confuse users who hand-edit `.songbook.yaml` files.  The migration validator
handles the transition, but documentation and any user-facing schema
documentation will need updating.

---

## Recommendation

**Option A has been implemented as part of this spike.**  The section-based
structure is live for all config-managed editions and the backward-compat
migration ensures no breakage for Drive-hosted editions.

Suggested follow-on steps:

1. **Document the new schema** in the project's user-facing documentation so
   users who hand-write `.songbook.yaml` files know the preferred structure.
2. **Add per-section feature flags** now that the structure supports them — for
   example `songs.limit` (cap number of songs), `table_of_contents.enabled`
   (skip TOC generation), `preface.include_in_toc: false`.
3. **Extend `SongsSection`** with a `sort_by` field to allow per-edition song
   ordering without code changes.
4. **Warn on old flat format** — the migration validator could emit a
   deprecation warning when it detects legacy flat fields, guiding users to
   update their Drive-hosted files.
5. **Update the `editions add` CLI command** (when created) to generate YAML in
   the new sections format by default.
